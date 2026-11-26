"""Deterministic checks for recorded student-voice wording preferences."""
from __future__ import annotations

import copy
import re

VERSION = 2

VOICE_RULES = (
    ('material_source', re.compile(r'老师|教师(?!签字|模型|网络|信号|端|–学生|-学生|—学生|与学生模型|和学生模型)'),
     '用实验对象或用途命名。确有必要交代来源时，用“实验材料提供的”。'),
    ('report_self_reference', re.compile(r'本文|笔者|作者认为|作者在本实验'),
     '用“本实验”，也可以直接用实验对象、操作或结果作主语。'),
    ('first_person', re.compile(r'我们|本人|(?<![自忘无])我(?!国|校|方|司|党|军|院|省|市|系)'),
     '第一人称用于心得体会段落。其余位置用“本实验”或直接写对象。'),
    ('administrative_voice',
     re.compile(r'课程评价(?:的重点)?|评分标准|考核重点|验收清单|(?:接受|拒绝)结果|错误文件为(?:\s*0\s*字节|空)[^。！？；\n]{0,45}(?:符合|满足)[^。！？；\n]{0,20}(?:约定|要求)'),
     '直接写实验操作、实际观察或结论，省去评分口吻、状态标签和同义自证。'),
    ('internal_shorthand', re.compile(r'只训头|形状流|断言(?:两者|二者)|(?:写成|写为)断言|参数往哪走|损失函数推着参数走'),
     '用实验对象和实际操作来描述。技术词是实验对象时保留准确术语。'),
)

_REFLECTION = re.compile(r'心得(?:体会)?|学习体会|个人体会|实验体会')
_CONCLUSION = re.compile(r'总结|结论|主要发现')
_LEADING_LABEL = re.compile(r'^\s*(?:\d+(?:\.\d+)*[.、]?\s*)?(心得体会|实验心得|学习体会|个人体会|实验体会|实验总结|总结|结论)\s*[：:]')
_REFERENCES = re.compile(r'参考文献|参考资料|引用文献|bibliography|references', re.I)
_REFLECTION_OPENING = re.compile(r'^\s*(?:本次实验中)?(?:我(?:最深的)?(?:的)?体会|(?:最深的)?体会|感受最深|收获最大)')
_NAME_FIELDS = {'姓名', '学生姓名', '实验者姓名'}
_NAME_PLACEHOLDERS = {'本人', '（本人）', '(本人)'}


def resolve_student_name_cells(document, student, locked=()):
    """Resolve only standalone self-name placeholders under an explicit name header."""
    updated = copy.deepcopy(document)
    name = (student or {}).get('name', '').strip()
    for section in updated['sections']:
        for block in section['blocks']:
            if block.get('type') != 'table' or block.get('id') in locked:
                continue
            for index, header in enumerate(block.get('headers', [])):
                if header.strip() in _NAME_FIELDS:
                    for row in block.get('rows', []):
                        if index < len(row) and row[index].strip() in _NAME_PLACEHOLDERS:
                            row[index] = name or '—'
    return updated


def check_student_voice(document):
    issues = []

    def check(value, heading, field, block_id='', *, reflection=False):
        if not isinstance(value, str):
            return
        for rule, pattern, suggestion in VOICE_RULES:
            if rule == 'first_person' and reflection:
                continue
            for match in pattern.finditer(value):
                quote = match.group()
                issues.append({'rule_id': 'student_voice:' + rule, 'block_id': block_id,
                    'section': heading, 'field': field, 'quote': quote, 'start': match.start(), 'end': match.end(),
                    'severity': 'major',
                    'reason': f'{heading}的{field}出现“{quote}”',
                    'suggestion': suggestion})

    check(document.get('title'), '报告', '标题')
    for section in document.get('sections', []):
        heading = section.get('heading', '')
        if _REFERENCES.search(heading):
            continue
        check(heading, heading, '章标题')
        mixed_reflection = bool(_REFLECTION.search(heading) and _CONCLUSION.search(heading))
        reflection = bool(_REFLECTION.search(heading) and not _CONCLUSION.search(heading))
        for block in section.get('blocks', []):
            kind, bid = block.get('type', 'text'), block.get('id', '')
            value = block.get('text', '')
            if kind == 'heading':
                reflection = bool(_REFLECTION.search(value) and not _CONCLUSION.search(value))
                check(value, heading, '小标题', bid)
            elif kind == 'text':
                label = _LEADING_LABEL.match(value)
                in_reflection = (bool(_REFLECTION.search(label[1])) if label else
                                 reflection or (mixed_reflection and bool(_REFLECTION_OPENING.match(value))))
                check(value, heading, '正文', bid, reflection=in_reflection)
            elif kind == 'list':
                for index, item in enumerate(block.get('items', []), 1):
                    check(item, heading, f'列表第{index}项', bid, reflection=reflection)
            elif kind in ('table', 'image'):
                check(block.get('caption'), heading, '表注' if kind == 'table' else '图注', bid)
                if kind == 'table':
                    for column, cell in enumerate(block.get('headers', []), 1):
                        check(cell, heading, f'表头第{column}列', bid)
                    for row, cells in enumerate(block.get('rows', []), 1):
                        for column, cell in enumerate(cells, 1):
                            check(cell, heading, f'表格第{row}行第{column}列', bid)
    return {'version': VERSION, 'status': 'issues_found' if issues else 'clear', 'issues': issues}
