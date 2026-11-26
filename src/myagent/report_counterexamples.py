"""User-approved editorial counterexamples, selected without another model call."""
from __future__ import annotations

import copy

from .report_section_policy import section_roles


EXAMPLES = (
    {
        'id': 'CE01', 'roles': ['procedure'],
        'before': '遍历 model.parameters() 置 requires_grad=False，再遍历 model.fc.parameters() 置 True，优化器只接收 requires_grad 为真的参数。',
        'problem': '连续以变量、API、参数检查组织正文，把实验过程写成口述代码，关键阶段及其作用被细节遮住。',
        'direction': '围绕本次模型改造、训练与评估的实际过程展开，选择影响理解的关键实现说明；不必为每个操作附加原因或意义。保留关键条件与必要过程，不把过程缩成操作清单。',
        'source': '用户指定反例：实验4原报告第6页6.2；2026-11-18讨论。',
    },
    {
        'id': 'CE02', 'roles': ['analysis', 'principles'],
        'before': '待估参数与样本量之比从约一万四千比一降到约三比一，800张图足以约束这一规模的线性分类器。……第7轮后验证准确率不再提升，也说明可学习容量已被用尽。',
        'problem': '将参数数量、样本量、曲线平台串成确定的因果链，每个观察都升级为机制结论；顺滑的解释掩盖了论据与判断之间的跳跃。',
        'direction': '选择本次结果中值得讨论的发现，联系相关原理展开必要解释。观察支持到哪里就陈述到哪里，不强求每个数字都有归因，也不以统一的局限声明收尾；保留有价值的机制解释。原理章交代理解任务需要的背景，具体结果留到分析中展开。',
        'source': '用户指定反例：实验4原报告第10页7.2；2026-11-18讨论。',
    },
    {
        'id': 'CE03', 'roles': ['conclusion', 'reflection'],
        'before': 'Lab 1说明小数据下微调之所以可行……主干提供512维通用表示，800张图只需约束2,565个参数……分类头首轮即达79.5%，15轮后普通验证91.0%、水平翻转TTA 92.5%。',
        'problem': '总结按实验逐项重播机制和数字；心得又复述改进建议。各章成为独立的标准答案，没有推进全文论述。',
        'direction': '提炼读完本次实验后最重要的认识，必要时保留关键结果；已经充分展开的机制和指标无需重讲。具体经历在最合适的位置集中展开，其他位置简洁承接。不要机械套成每个实验一段、每段末尾一条意义。',
        'source': '用户指定反例：实验4原报告第14页第八章；2026-11-18讨论。',
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
