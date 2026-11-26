"""Read original Excel cells without recalculating or rewriting the workbook."""
from __future__ import annotations

from contextlib import closing


SPREADSHEETS = {'.xlsx', '.xlsm'}


def spreadsheet_passages(path, *, sheet=None, first_row=1, last_row=None):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    with closing(load_workbook(path, read_only=True, data_only=True, keep_links=False)) as workbook:
        if sheet is not None and sheet not in workbook.sheetnames:
            raise ValueError('无此工作表，可选工作表：' + ', '.join(workbook.sheetnames))
        worksheets = [workbook[sheet]] if sheet else workbook.worksheets
        for worksheet in worksheets:
            end = last_row
            if worksheet.max_row is not None:
                end = worksheet.max_row if end is None else min(end, worksheet.max_row)
            if end is not None and end < first_row:
                continue
            rows = worksheet.iter_rows(min_row=first_row, max_row=end, values_only=True)
            for row_number, values in enumerate(rows, first_row):
                cells = [f'{get_column_letter(column)}{row_number}={value}'
                         for column, value in enumerate(values, 1) if value is not None]
                if cells:
                    yield {'sheet': worksheet.title, 'start_line': row_number, 'end_line': row_number,
                           'text': '\t'.join(cells)}
