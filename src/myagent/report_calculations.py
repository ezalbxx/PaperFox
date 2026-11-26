"""Deterministic report calculations over registered workbook observations."""

from contextlib import closing
import json
import math
import re
from statistics import linear_regression, mean

from .jobs import atomic_json
from .report_context import fingerprint
from .spreadsheet_material import SPREADSHEETS
from .tools.base import ToolResult


class ReportCalculations:
    name = 'report_calculate'
    description = ('Calculate a linear fit or maximum absolute residual divided by the measured '
        'output at a specified x. Use original Excel cell pairs; an absent reference remains '
        'unavailable. Also returns the largest adjacent drop across the selected observations.')
    parameters = {'type': 'object', 'properties': {
        'source_id': {'type': 'string'}, 'sheet': {'type': 'string'},
        'metric': {'type': 'string', 'enum': ['linear_fit', 'normalized_max_deviation']},
        'pairs': {'type': 'array', 'minItems': 2, 'maxItems': 256, 'items': {
            'type': 'object', 'properties': {'x': {'type': 'string'}, 'y': {'type': 'string'}},
            'required': ['x', 'y']}},
        'reference_x': {'type': 'number', 'description': 'Required physical x value from the metric definition, not a cell or fitted value.'},
    }, 'required': ['source_id', 'sheet', 'metric', 'pairs']}

    def __init__(self, project):
        self.project = project

    def run(self, args, ctx):
        from openpyxl import load_workbook
        from openpyxl.utils.cell import coordinate_to_tuple

        source = next((s for s in self.project.data['report_sources'] if s['id'] == args['source_id']), None)
        if source is None:
            raise ValueError('请提供本项目登记的 Excel 材料 ID。')
        path = self.project.file(source['path'])
        if path.suffix.lower() not in SPREADSHEETS:
            raise ValueError('计算工具接受登记的 .xlsx 或 .xlsm 工作簿。')
        pairs = [{axis: pair[axis].strip().upper() for axis in ('x', 'y')} for pair in args['pairs']]
        if not 2 <= len(pairs) <= 256 or len({(p['x'], p['y']) for p in pairs}) != len(pairs):
            raise ValueError('请提供 2–256 对不同的实测单元格。')
        refs = {}
        for cell in {cell for pair in pairs for cell in pair.values()}:
            if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,6}', cell):
                raise ValueError(f'单元格地址无效：{cell}')
            refs[cell] = coordinate_to_tuple(cell)
        rows, cols = zip(*refs.values())
        if max(rows) > 1048576 or max(cols) > 16384 or (max(rows)-min(rows)+1)*(max(cols)-min(cols)+1) > 100000:
            raise ValueError('单元格地址越界或选区过大，请选择直接对应的数据区域。')
        with closing(load_workbook(path, read_only=True, data_only=True, keep_links=False)) as workbook:
            if args['sheet'] not in workbook.sheetnames:
                raise ValueError('无此工作表，可选工作表：' + '、'.join(workbook.sheetnames))
            sheet = workbook[args['sheet']]
            wanted = set(refs.values())
            values = {(r, c): value for r, row in enumerate(sheet.iter_rows(
                min_row=min(rows), max_row=max(rows), min_col=min(cols), max_col=max(cols), values_only=True), min(rows))
                for c, value in enumerate(row, min(cols)) if (r, c) in wanted}
        numbers = {}
        for cell, coord in refs.items():
            value = values.get(coord)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'{args["sheet"]}!{cell} 没有可用的数值。请核对原表；空单元格不能当作 0。')
            numbers[cell] = value
        observations = sorted(((numbers[p['x']], numbers[p['y']], p) for p in pairs), key=lambda row: row[0])
        metric = args['metric']
        reference_x = args.get('reference_x')
        if metric == 'normalized_max_deviation' and (type(reference_x) not in (int, float) or not math.isfinite(reference_x)):
            raise ValueError('计算相对最大偏差时须提供指标要求的 reference_x。')
        result = {'source_id': source['id'], 'sheet': args['sheet'], 'metric': metric,
            'status': 'computed', 'x_range': [observations[0][0], observations[-1][0]],
            'count': len(observations), 'pairs': [pair for _, _, pair in observations]}
        drops = [(b[1]-a[1], a[2], b[2]) for a, b in zip(observations, observations[1:]) if b[0]>a[0] and b[1]<a[1]]
        if drops:
            delta, before, after = min(drops, key=lambda drop: drop[0])
            result['largest_drop'] = {'from': before, 'to': after,
                'from_values': {axis: numbers[before[axis]] for axis in before},
                'to_values': {axis: numbers[after[axis]] for axis in after}, 'y_change': delta}
        references = [(y, pair['y']) for x, y, pair in observations if x == reference_x]
        reference_output = mean(y for y, _ in references) if references else None
        if metric == 'normalized_max_deviation':
            result['reference_x'] = reference_x
            if not references:
                result.update(status='unavailable', reason='required_reference_not_in_observations')
            elif not reference_output:
                result.update(status='unavailable', reason='zero_reference_output')
        if result['status'] == 'computed':
            xs, ys, _ = zip(*observations)
            if xs[0] == xs[-1]:
                raise ValueError('拟合需要至少两个不同的 x 值。')
            slope, intercept = linear_regression(xs, ys)
            residual = max(abs(y-(slope*x+intercept)) for x, y in zip(xs, ys))
            result['values'] = {'slope': slope, 'intercept': intercept, 'max_absolute_residual': residual}
            if metric == 'normalized_max_deviation':
                result['values'].update(reference_output=reference_output,
                    reference_cells=[cell for _, cell in references], deviation_percent=100*residual/reference_output)
        result['id'] = fingerprint(result)
        receipt = self.project.file(f'outputs/report-calculations/{result["id"]}.json')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(receipt, result)
        return ToolResult(output=json.dumps(result, ensure_ascii=False))


def attach_calculation(project, claim):
    """Accept the saved tool result, never a numeric packet copied by the model."""
    claim.pop('calculation', None)
    receipt_id = claim.pop('calculation_id', None)
    if not isinstance(receipt_id, str) or not re.fullmatch(r'[0-9a-f]{64}', receipt_id):
        return
    path = project.file(f'outputs/report-calculations/{receipt_id}.json')
    if path.is_file():
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('source_id') in claim.get('source_ids', []):
            claim['calculation'] = record
