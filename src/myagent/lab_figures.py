"""Authored report figures from saved evidence, with machine-readable lineage.

Pillow supplies drawing primitives; matplotlib supplies scientific plotting.
Neither model-generated pixel evidence nor another agent's skill is used.
"""
from __future__ import annotations

import json
from uuid import uuid4

from .jobs import atomic_json
from .lab_project import digest
from .tools.base import ToolResult


def lookup(value, path):
    for key in path.split('.') if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def registered_assets(project):
    return [a for result in project.data['results'].values() for a in result['artifacts']] + project.data.get('presentation_assets', [])


def figure_grounding(project, asset):
    """Expose recorded plot semantics, without calling them a pixel inspection."""
    unknown = {'basis': 'image_metadata_only', 'pixels_inspected': False}
    provenance = asset.get('provenance')
    if not provenance:
        return unknown
    try:
        if isinstance(provenance, str):
            provenance = json.loads(project.file(provenance).read_text(encoding='utf-8'))
        if not isinstance(provenance, dict) or not provenance.get('source_sha256'):
            return unknown
        if not asset.get('sha256') or digest(project.file(asset['path'])) != asset['sha256']:
            return {**unknown, 'reason': 'image_hash_changed'}
        if digest(project.file(provenance['source'])) != provenance['source_sha256']:
            return {**unknown, 'reason': 'source_hash_changed'}
    except (OSError, ValueError, KeyError):
        return {**unknown, 'reason': 'provenance_unavailable'}
    operation = provenance.get('operation')
    basis = {'plot': 'source_json_values', 'diagram': 'source_linked_diagram',
             'excerpt': 'source_text_excerpt'}.get(operation)
    if not basis:
        return unknown
    keys = ('source', 'source_sha256', 'operation', 'title', 'labels', 'series',
            'measured_values', 'render_spec', 'steps', 'nodes', 'edges', 'start_line', 'end_line',
            'reference_ids', 'reference_use', 'references', 'reference_input_modes', 'design')
    context = {**unknown, 'basis': basis, **{k: provenance[k] for k in keys if k in provenance}}
    if len(json.dumps(context, ensure_ascii=False)) > 6000:
        return {**unknown, 'reason': 'spec_too_large', 'provenance': asset.get('provenance')}
    return context


class LabFigures:
    name = 'lab_figure'
    description = ('Our report illustration skill, reading saved evidence only. Use native report code '
        'blocks for source excerpts and logs. plot: read JSON numeric values using dotted paths '
        '(list indexes allowed), render bar/barh/line/scatter/heatmap. series.path reads a complete numeric array; '
        'x_path supplies a numeric x array, matrix_path supplies a heatmap matrix. No invented arrays. Saves PNG, SVG plus source SHA '
        'and provenance. Use registered original screenshots when needed. '
        'diagram: source-linked steps or nodes/edges; design.layout horizontal/vertical, groups and feedback edges. '
        'Use reference_ids and reference_use to record borrowed design; design sets final width_mm/height_mm/font_size/colors. '
        'number_format supports auto/float/int/percent/scientific (percent values remain source fractions). '
        'For bars supply category_label/value_label/value_unit; axes are mapped from kind. orientation must match bar/barh. '
        'Input source must be a registered artifact or original source_paths entry. '
        'plot series example [{"label":"decode tok/s","paths":["groups.0.mean_decode_tok_s","groups.1.mean_decode_tok_s"]}], '
        'labels describes those conditions. Include the returned image path in the report.')
    parameters = {'type': 'object', 'properties': {
        'operation': {'type': 'string', 'enum': ['plot', 'diagram']},
        'steps': {'type':'array','items':{'type':'string'},'minItems':2,'maxItems':8},
        'source': {'type': 'string'}, 'title': {'type': 'string'},
        'kind': {'type': 'string', 'enum': ['bar', 'barh', 'line', 'scatter', 'heatmap']},
        'x_path': {'type': 'string'}, 'matrix_path': {'type': 'string'},
        'xlabel': {'type': 'string'}, 'colorbar_label': {'type': 'string'},
        'category_label': {'type': 'string'}, 'value_label': {'type': 'string'}, 'value_unit': {'type': 'string'},
        'orientation': {'type': 'string', 'enum': ['horizontal', 'vertical']},
        'label_language': {'type': 'string', 'enum': ['zh', 'en']},
        'row_labels': {'type': 'array', 'items': {'type': 'string'}}, 'annotate': {'type': 'boolean'},
        'number_format': {'type': 'string', 'enum': ['auto', 'float', 'int', 'percent', 'scientific']},
        'reference_ids': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string'}},
        'reference_use': {'type': 'string'},
        'design': {'type': 'object', 'properties': {
            'width_mm': {'type': 'number'}, 'height_mm': {'type': 'number'}, 'font_size': {'type': 'number'},
            'layout': {'type': 'string', 'enum': ['horizontal', 'vertical']},
            'colors': {'type': 'array', 'items': {'type': 'string'}}, 'cmap': {'type': 'string'},
            'show_title': {'type': 'boolean'}}},
        'nodes': {'type': 'array', 'minItems': 2, 'maxItems': 12, 'items': {'type': 'object',
            'properties': {k: {'type': 'string'} for k in ('id', 'label', 'group')}, 'required': ['id', 'label']}},
        'edges': {'type': 'array', 'items': {'type': 'object', 'properties': {
            **{k: {'type': 'string'} for k in ('from', 'to', 'label')},
            'kind': {'type': 'string', 'enum': ['data', 'control', 'feedback']}}, 'required': ['from', 'to']}},
        'labels': {'type': 'array', 'items': {'type': 'string'}},
        'ylabel': {'type': 'string'},
        'series': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'label': {'type': 'string'}, 'paths': {'type': 'array', 'items': {'type': 'string'}}, 'path': {'type': 'string'}},
            'required': ['label'], 'anyOf': [{'required': ['paths']}, {'required': ['path']}]}}}, 'required': ['operation', 'source', 'title']}

    def __init__(self, project):
        self.project = project

    def run(self, args, ctx):
        p = self.project
        if args['operation'] not in ('diagram', 'plot'):
            raise ValueError('制图仅支持diagram和plot。源码、日志和诊断原文请读取后放入报告code块。')
        if p.data.get('figure_spec_version', 1) >= 2 and args['operation'] == 'plot':
            if args.get('kind','bar') in ('bar','barh') and (not args.get('category_label') or not args.get('value_label')):
                raise ValueError('新版条形图需category_label和value_label，由程序按kind映射轴名；补齐后重画')
            args = {**args, 'label_language': 'zh'}
        path = p.file(args['source'])
        allowed = {str(p.file(a['path'])) for a in registered_assets(p)}
        allowed.update(str(p.file(s)) for r in p.data['results'].values() for s in r.get('source_paths', []))
        if str(path) not in allowed:
            raise ValueError('图表来源需要是已登记的实验产物/source_paths')
        from .figure_references import reference_provenance
        reference_design = reference_provenance(p, args)
        directory = p.root / 'outputs/report-figures'
        directory.mkdir(parents=True, exist_ok=True)
        stem = directory / uuid4().hex[:12]
        image = stem.with_suffix('.png')
        provenance = {'source': str(path.relative_to(p.root)), 'source_sha256': digest(path),
                      'title': args['title'], 'operation': args['operation'], **reference_design}
        if args['operation'] == 'diagram':
            from .figure_rendering import render_diagram
            provenance.update(render_diagram(args, image))
        else:
            from .figure_rendering import render_plot
            value = json.loads(path.read_text(encoding='utf-8'))
            provenance.update(render_plot(value, args, image, lookup))
        if image.with_suffix('.svg').is_file():
            provenance['editable_source'] = str(image.with_suffix('.svg').relative_to(p.root))
        atomic_json(stem.with_suffix('.json'), provenance)
        artifact = {'path': str(image.relative_to(p.root)), 'sha256': digest(image),
                    'provenance': str(stem.with_suffix('.json').relative_to(p.root)), **provenance}
        p.data.setdefault('presentation_assets', []).append(artifact)
        p.save()
        return ToolResult(output=json.dumps(artifact, ensure_ascii=False))
