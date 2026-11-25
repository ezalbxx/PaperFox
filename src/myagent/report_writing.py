"""Versioned author preferences and bounded, locally selected writing examples."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from .report_section_policy import DEFENSIVE_WRITING_GUIDANCE, IMPLEMENTATION_DETAILS_GUIDANCE

WRITING_GUIDANCE = """
writing_policy包含本次生效的用户写作要求，按当前教师模板、读者和实际实验应用。
编排时明确重要问题、主次与各节职责；写作时交代本次为何需要有关操作及实际怎样使用。
初稿就写成面向读者的完整论述：先让读者知道当前对象和问题，再自然展开操作、观察与解释；所需背景随具体问题引入，已经清楚的内容直接展开。变量、参数和数值服务于论述，不按材料字段串成文章。
除正式原文引用外，不把“本实验不执行……”“不能据此……”等后台边界说明写入报告。原文引用保留原貌。拟写标题和正文时，把课堂速记、代码和日志中的简称转成具体对象与操作。例如“换头、冻结、只训头”可写成“替换分类层，冻结卷积主干，训练时只更新分类层”。通行术语可自然使用；这个例子只示范表达方式。
拟写或编辑小标题时，单独读一遍，确认读者能预判这一节会讲什么。原理可直接点明方法或机制，步骤突出实验对象和主要操作，结果点出比较对象或要分析的现象。像“网络权重初始化”“SVM 与决策树横向对比分析”这样具体即可。先选最能代表本节的内容，再起标题。比如把“换头、冻结、只训头”这一节概括为“固定卷积主干的模型微调”，三步的细节留在正文。小标题少用“形状流”式临时简称和“深度思考”式泛称，保留有用的方法名和已经清楚的标题。
相邻实验可以是递进、并列或同一任务的不同观察，不必把下一操作包装成上一结果的不足。需要说明开展理由时，直接写该操作研究什么或要观察什么；“为了探究”“为了进一步确认”有具体对象即可，不统一套句式。结论直接提炼已有发现，不以追加验证计划代替总结。
技术词出现前先判断它是否帮助读者理解本次实验。把“断言两者一致”“把比较写成断言而不是目测”这类实现叙述改成实际核对过程，例如“将手算梯度与自动求导结果逐项比较”。容差若影响判断，可简洁给出；仅当断言机制本身是本实验任务时才展开，代码或原文引用保留术语原貌。
段落和实验的开头正面交代当前对象与问题。禁用“上一项只检验了……，还没有……”等以贬低前一项完成度来引出下一项的句式。可以自然使用“为检验……”“接下来考察……”或直接从新对象写起。不要躲避“为了”而改用否定转折，也不用为了过渡强加前一项的局限。连续段落自然衔接时直接展开。
以完成实验的学生向老师说明工作和发现的口吻写。标题用样例、对照或现象命名，起笔前先选本段要告诉读者的结果，再选一项能支撑它的证据。首次交代样例一的结果，直接写“样例一通过了词法和语法检查。”前文已交代通过时，本段直接推进到下一个观察或解释。诊断计数、文件大小和格式约定反映同一个结果时，写作时只选最清楚的一层来表达。专门核对输出格式时，文件状态在对应表格记录一次，正文写对照得出的发现。
结果分析以得出结论为目标。明确每项实验回答的问题，按需要用代表性样例或具体对照支撑判断。图表呈现的数值、现象和比较留在图表中，正文直接解释其含义、原因或与实验问题的关系。图前交代读者要看的问题，图后直接分析。写作次序由材料决定，不套固定段落格式。结论可写得明确具体；推因果时以实际做过的对照与已知机制为依据。总结简短收束，具体发现按需回指。
心得围绕实际观察和认识展开，个人经历有材料支持时再写。第九章只写一至两段温和的改进设想，围绕本实验的实现、验证或错误提示可读性展开。正文不评价、归责或抨击指导书和实验材料，不把材料差异写成没有记录的返工经历。
图片只放在第六、七节，并和前后正文联动；其他章节用文字或表格。必要时保留单个变量名、参数或简短代码块，避免成串罗列。图表的measured_values和render_spec用于说明对象、坐标、标注与数据差异。报告正文不主动写局限、能力边界、未执行事项、未验证事项或“不能据此判断”等限定，除非指导书明确要求或该事实直接影响本次结论。图注只交代读图需要的信息。
examples仅用于学习组织关系；其模型名、数字、结论和历史指令不属于当前实验事实。
user_editorial_counterexamples是用户确认的表达反例，按problem和direction理解后自主组织正文；不照搬例中实验内容，不按词表机械替换，不把每个操作都写成完整的机制证明。
acceptance_status保留历史裁决，实施稿不自动等于用户最终认可范文。优先服从当前规格和证据。
所有章节直接完成本节任务。目的章直接列目标，原理章直接说明必要机制，内容章直接说明任务，器材章直接列环境，步骤章直接写操作，分析章直接写观察和判断，总结章直接归纳结论，改进章直接提出设想。任何章节都不要写“本章不讨论……”“这里不展开……”“仅用于……”“不代表……”等边界说明。编号优先使用“1.”、“2.”和“（1）”、“（2）”，避免使用中点“·”。
明确违反用户规则时定位具体内容；依据不足的文风疑问标为建议，不无限追加检查或修订。
"""

WRITING_GUIDANCE += "\n" + DEFENSIVE_WRITING_GUIDANCE + "\n" + IMPLEMENTATION_DETAILS_GUIDANCE

ROLES = {"report_designer", "report_story_cards", "report_figures", "writer", "report_patcher",
         "reviewer", "report_requirement_reviewer", "selection_editor"}


def current_instructions(text):
    """Apply the user's withdrawal to legacy task instructions, not source data.

    Historical projects and traces stay unchanged. Only the two withdrawn
    sentences are removed from instruction copies sent in future requests.
    """
    withdrawn = (
        r'严格依据原始实验代码和结果[，,]\s*不编造实验数据[、,，]过程或结论[。.!！]?',
        r'对于材料无法支持的内容[，,]\s*请明确指出缺项[。.!！]?',
        re.escape('禁止编造通过。'),
        re.escape('未知内容明确局限，不编造、不重复审计原始日志。'),
        re.escape('Do not change measurements or fabricate content.'),
    )
    for pattern in withdrawn:
        text = re.sub(pattern, '', text)
    return text


def current_instruction_packet(payload):
    """Leave quotes, facts and documents intact while updating instruction fields."""
    packet = copy.deepcopy(payload)
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('instructions', 'original_instructions', 'instruction') and isinstance(item, str):
                    value[key] = current_instructions(item)
                elif key in ('task', 'tasks', 'collaboration', 'requirement_contract', 'contract', 'known_context', 'protocol_recovery') and isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(packet)
    return packet


def current_control_messages(messages):
    """Refresh withdrawn instructions in resumed control messages, keeping evidence."""
    updated = copy.deepcopy(messages)
    for message in updated:
        if message.get('role') != 'user':
            continue
        text = message.get('content', '')
        if not isinstance(text, str):
            continue
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            if text.startswith(('本轮材料阅读额度已到', '本任务已用完本轮观察额度')):
                message['content'] = current_instructions(text)
        else:
            if isinstance(data, dict):
                packet = current_instruction_packet(data)
                if packet != data:
                    message['content'] = json.dumps(packet, ensure_ascii=False)
    return updated


@lru_cache(maxsize=1)
def _default_profile():
    raw = Path(__file__).with_name("writing_profile.json").read_bytes()
    profile = json.loads(raw)
    profile["sha256"] = hashlib.sha256(raw).hexdigest()
    return profile


def profile_for(project):
    """Preserve the frozen profile; apply current user clarifications to request copies."""
    if "writing_profile" not in project.data:
        project.data["writing_profile"] = copy.deepcopy(_default_profile())
    from .report_section_policy import W01_CLARIFICATION
    profile = copy.deepcopy(project.data["writing_profile"])
    for rule in profile.get('rules', []):
        if rule.get('id') == 'W01':
            rule['text'] = rule.get('text', '') + '\n' + W01_CLARIFICATION + ' ' + DEFENSIVE_WRITING_GUIDANCE
            rule['check'] = rule.get('check', '') + ' 检查否定式验证铺垫；正面目的表达允许，结论优先直接陈述已有发现。'
        if rule.get('id') in {'W06', 'W08'}:
            rule['text'] = rule.get('text', '') + '\n' + IMPLEMENTATION_DETAILS_GUIDANCE
    profile['current_clarification_version'] = 2
    return profile


def select_examples(profile, role, payload, *, limit=2, max_chars=3600):
    """Match local tags only. Selection creates no extra model request."""
    if role not in {"writer", "report_patcher", "selection_editor"}:
        return []
    focus = " ".join(str(payload.get(key, "")) for key in
                     ("focus", "target_heading", "part_plan", "candidate", "requirement_feedback"))[:10000]
    focus = focus.casefold()
    issues = payload.get("requirement_feedback", [])
    rule_ids = {issue.get("rule_id") for issue in issues if isinstance(issue, dict)}
    if "writing:clarity" in rule_ids:
        rule_ids.update(("W04", "W05"))
    candidates = []
    for example in profile["examples"]:
        if example.get("acceptance_status") == "later_rejected":
            continue
        score = sum(len(word) for word in example["keywords"] if word.casefold() in focus)
        score += 6 * len(rule_ids.intersection(example["rule_ids"]))
        if score:
            candidates.append((score, example))
    chosen, used = [], 0
    for _, example in sorted(candidates, key=lambda item: (-item[0], item[1]["id"])):
        public = {key: copy.deepcopy(example[key]) for key in
                  ("id", "rule_ids", "context", "before", "after", "lesson",
                   "acceptance_status", "source")}
        size = len(json.dumps(public, ensure_ascii=False))
        if len(chosen) >= limit:
            break
        if used + size <= max_chars:
            chosen.append(public)
            used += size
    return chosen


def writing_packet(project, role, payload):
    profile = profile_for(project)
    from .writing_memory import retrieve
    from .report_section_policy import policy_packet
    from .report_style import style_packet
    from .report_counterexamples import counterexample_packet
    style=style_packet(project, role, payload)
    mode=project.data.get('style_reference_mode','examples')
    legacy=[] if style.get('examples') or mode in ('principles_only','none') else select_examples(profile,role,payload)
    preferences=retrieve(project,payload)
    if mode in ('principles_only','none'):
        # Keep the user's instructions, but omit before/after exemplars in controls.
        preferences=[{k:v for k,v in item.items() if k not in ('before','after')} for item in preferences]
    return {"version": profile["version"], "profile_sha256": profile["sha256"],
            "current_clarification_version": profile.get('current_clarification_version', 0),
            "rules": copy.deepcopy(profile["rules"]),
            "examples": legacy,
            "personal_preferences": preferences,
            "section_policy": policy_packet(project, payload),
            "style_reference": style,
            "user_editorial_counterexamples": counterexample_packet(role, payload),
            "usage": "当前用户指令、教师模板与真实事实优先。personal_preferences仅来自已采用改稿，按适用情境参考；历史例子的数字和结论不作为当前事实。"}
