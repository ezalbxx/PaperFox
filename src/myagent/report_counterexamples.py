"""User-approved editorial counterexamples, selected without another model call."""
from __future__ import annotations

import copy

from .report_section_policy import section_roles


EXAMPLES = (
    {
        'id': 'CE01', 'roles': ['procedure'],
        'before': '依次调用三个函数，再逐项设置配置字段。',
        'problem': '正文逐项转述代码，读者难以理解操作顺序和作用。',
        'direction': '围绕关键操作和作用展开，用表格承载必要的配置。',
    },
    {
        'id': 'CE02', 'roles': ['analysis', 'principles'],
        'before': '曲线趋平，说明模型的可学习容量已被用尽。',
        'problem': '把单一现象写成了已经验证的机制解释。',
        'direction': '从结果中的关键变化出发，结合实验条件给出有依据的解释。',
    },
    {
        'id': 'CE03', 'roles': ['conclusion', 'reflection'],
        'before': '总结逐项罗列正文已展示的各组数据及其配置。',
        'problem': '总结重播结果章节，占用了提炼主要认识的篇幅。',
        'direction': '用已有结果归纳主线，保留对总体判断有用的信息。',
    },
)

GUIDANCE = ('以下是用户确认的表达反例，用于理解问题和自主选择组织方式，不是禁用词表、固定改写模板或AIGC检测规则。'
            '例中的实验身份、数字、模型与结论不属于本次事实，不能照搬；同类术语和合理解释仍可使用。'
            '不要求每段采用相同结构，也不要求每段添加总起句、原因、结果或总结；话题入口和承接按实际上下文安排。')


def counterexample_packet(role, payload):
    if role not in ('report_designer', 'writer', 'report_patcher', 'selection_editor'):
        return {}
    target = payload.get('target_heading') or (payload.get('context') or {}).get('heading')
    document = payload.get('document') or payload.get('candidate') or {}
    headings = [target] if target else [s.get('heading', '') for s in document.get('sections', [])]
    roles = {r for h in headings for r in section_roles(h)}
    examples = [e for e in EXAMPLES if roles.intersection(e['roles'])] if headings else list(EXAMPLES)
    return {'version': 1, 'guidance': GUIDANCE,
            'planning': '在全篇范围内分配解释任务，安排各节让读者理解什么，以及哪些内容已经讲清；同一机制选合适位置充分展开，后文推进具体过程和发现，不要求每章独立重讲全套原理。',
            'examples': [{k: copy.deepcopy(v) for k, v in e.items() if k != 'roles'} for e in examples]}
