"""Chapter responsibilities independent of the teacher's heading names."""
from __future__ import annotations

import copy
import re

VERSION = 15

PRINCIPLES_MAX_CHARS = 450
EQUIPMENT_MAX_CHARS = 100
EQUIPMENT_LABELS = ('硬件平台', '软件环境')
EQUIPMENT_HEADINGS = {'实验器材', '实验设备', '实验环境', '实验仪器与软件环境', '实验器材与环境'}
EQUIPMENT_RULE = (EQUIPMENT_MAX_CHARS,
    '只提交一至两行纯文本，每行一个 text 块，顺序为“硬件平台：…”、“软件环境：…”。'
    '硬件只列实际使用的设备及必要规格；软件只列实际使用的系统、语言和主要工具或库。'
    f'每类最多一行，全节最多{EQUIPMENT_MAX_CHARS}个可见字符（含标点）。'
    '缺少某类证据时省略该行，不猜版本、型号或配置。'
    '只列名称及必要版本，不写解释、编译参数、命令、输入输出、实验过程、材料清单、表格、列表或小标题。')
OPENING_RULES = {
    '实验项目名称': (100, '只填写本实验的正式名称，提交一个单行 text 块。名称写完即结束。'),
    '实验原理': (PRINCIPLES_MAX_CHARS,
        f'整节连标题控制在半页以内。正文合计最多{PRINCIPLES_MAX_CHARS}个可见字符（含标点），按核心机制自然分段。'
        '从后文步骤和结果分析反推，选出读者必须先懂的核心机制。省去其余解释，再自然地写出取舍后的内容。'
        '完整推导、实现细节和对照结果在正文相应位置按需展开。'),
    '实验目的': (150, '提交一个 list 块。每项一句，直接写具体学习或研究目标；排版自动编号为 1. 2. 3.。'
        '按实际目标决定条数，整节建议约150字以内。'),
    '实验目的及内容': (120, '提交一个编号 list 块，每项用一句话写指导书中的核心目标或本次实验的主要任务。'
        '优先合并围绕同一装置或问题的学习目标。任务可用一句话同时交代主要测量和要评价的指标。'
        '通常两到三项，合计约120字以内；定义和解释留在原理节。'
        '全节以这一组条目一次交代清楚，无需另写导语、重复目标或再列步骤。'
        '装置结构、公式、操作顺序、加载终点及其他具体取值留在正文相应位置；开头只交代任务和要评价的指标。'),
    '实验器材': EQUIPMENT_RULE,
}


def opening_rule(heading):
    name = re.sub(r'^\s*(?:第[一二三四五六七八九十\d]+[章节]|[（(][一二三四五六七八九十\d]+[）)]|'
                  r'(?:[一二三四五六七八九十\d]+|[IVXLCDM]+)\s*[、.．)）](?!\d))\s*',
                  '', heading, flags=re.IGNORECASE).strip(' ：:')
    base = re.sub(r'\s*[（(][^()（）]*[）)]$', '', name).strip()
    if name != base and set(section_roles(name)) - set(section_roles(base)):
        return None
    if base in EQUIPMENT_HEADINGS:return EQUIPMENT_RULE
    if (re.fullmatch(r'(?:实验|研究)?(?:目的|目标)\s*(?:以及|及|与|和|、|[/／])\s*(?:实验)?内容', base)
            or re.fullmatch(r'(?:aim|objective|purpose)s?\s*(?:and|&|[/／])\s*(?:scope|tasks?)', base, re.I)):
        return OPENING_RULES['实验目的及内容']
    if re.fullmatch(r'(?:实验|研究|学习)?(?:目的|目标)|(?:experiment(?:al)?\s+)?(?:aim|objective|purpose)s?', base, re.I):
        return OPENING_RULES['实验目的']
    return OPENING_RULES.get(name)


def template_opening_note(heading, template):
    """Recognize a brief written instruction attached to this top-level heading."""
    if heading not in (template or {}).get('headings', []):
        return None
    lines = [re.sub(r'^\s*#{1,6}\s+', '', line).strip().rstrip('：:')
             for line in (template or {}).get('body_excerpt', '').splitlines() if line.strip()]
    title = heading.strip().rstrip('：:')
    if title not in lines or lines.index(title)+1 >= len(lines):
        return None
    note = lines[lines.index(title)+1].strip('（）() ')
    roles = section_roles(heading)
    if roles not in (['objectives'], ['support']) or len(note) > 240:
        return None
    prose = re.match(r'(?:(?:格式|要求)\s*[：:]\s*)?(?:请)?(?:用|以|写)一(?:个)?(?:自然)?段(?:话)?|'
                     r'(?:write|use|in)\s+(?:a|one|a single)\s+(?:short\s+)?paragraph\b', note, re.I)
    short_scope = (roles == ['support'] and re.match(r'(?:请)?(?:简述|简要说明|概述)', note)
                   and re.search(r'问题|目的|目标', note) and re.search(r'任务|内容|要做|工作', note))
    return (note.rstrip('。.'), bool(prose)) if prose or short_scope else None


def compact_opening_plan(outline, template=None):
    """Reuse evidence associations when replacing verbose opening assignments."""
    for section in outline['sections']:
        parts = section['parts']
        if len(parts) == 1 and parts[0].get('opening_plan_compacted'):
            continue
        rule = opening_rule(section['heading'])
        note = template_opening_note(section['heading'], template)
        combined = set(section_roles(section['heading'])) == {'objectives','principles'}
        if rule is None and not note and not combined:
            continue
        if note:
            instruction, paragraph = note
            budget, focus = 150, ('按本栏模板填写：'+instruction+'。用一至两句话交代本次要解决的问题和主要任务。此处只写目标与任务。'
                '具体原理、公式、数值、操作顺序和结果由相应栏目承担。')
            if paragraph:
                focus += '模板明确指定一个段落，交付一个text块。'
        elif combined:
            budget, focus = PRINCIPLES_MAX_CHARS, ('本栏合写目的和原理，由同一个写作部分一次完成。开头用简短编号目标说明对象和任务，随后简述与后文直接相关的原理。'
                '各职责只承担一次；目标只概括任务和要评价的指标，具体加载范围与操作条件留在方法。原理不重新列目标。整栏约半页。')
            planned = '；'.join(row['focus'] for row in parts if row.get('focus'))
            if planned:
                focus += ' 原计划的主题供选材：'+planned
        else:
            budget, focus = rule
        part = {key: list(dict.fromkeys(item for row in parts for item in row.get(key, [])))
                for key in ('task_ids', 'card_ids')}
        if parts and all('fact_refs' in row for row in parts):
            part['fact_refs']=list(dict.fromkeys(ref for row in parts for ref in row['fact_refs']))
        section['parts'] = [{**part, 'focus': focus, 'character_budget': budget,
                             'detail_carriers': [], 'opening_plan_compacted': True,
                             **({'compact_opening': True} if rule and not note else {}),
                             **({'opening_form': 'paragraph', 'compact_opening': True} if note and note[1] else {})}]
    return outline


def validate_opening_section(section, opening_form=None):
    if opening_form == 'paragraph':
        blocks = section['blocks']
        text = blocks[0].get('text', '').strip() if len(blocks)==1 and blocks[0].get('type')=='text' else ''
        if not text or not re.fullmatch(r'[^\r\n]+', text):
            from .report_protocol import ProtocolError
            raise ProtocolError(section['heading'] + '.blocks', '模板指定一个段落，请提交一个非空text块。', [b.get('type') for b in blocks])
        return
    rule = opening_rule(section['heading'])
    if rule is None:
        return
    budget, instruction = rule
    blocks = section['blocks']
    if rule == OPENING_RULES['实验项目名称']:
        name = blocks[0].get('text', '').strip() if len(blocks) == 1 and blocks[0].get('type') == 'text' else ''
        valid = len(name.splitlines()) == 1 and not re.search(r'[。！？；]', name)
    elif rule == OPENING_RULES['实验原理']:
        visible_count = sum(len(re.sub(r'\s+', '', str(value))) for block in blocks for value in (
            block.get('text', ''), block.get('caption', ''), *block.get('items', []),
            *block.get('headers', []), *(cell for row in block.get('rows', []) for cell in row)))
        valid = 0 < visible_count <= budget
        if not valid:
            instruction += f' 当前正文{visible_count}个可见字符。'
    elif rule == EQUIPMENT_RULE:
        lines = [b.get('text','').strip() for b in blocks if b.get('type')=='text']
        labels = []
        valid = len(lines)==len(blocks) and 1<=len(lines)<=2
        visible_count = sum(len(re.sub(r'\s+','',line)) for line in lines)
        for line in lines:
            label,sep,value=line.partition('：')
            if (label not in EQUIPMENT_LABELS or not sep or not value.strip()
                    or len(line.splitlines())!=1 or re.search(r'(?<![\w-])--?[A-Za-z]',value)
                    or re.search(r'[。！？!?].+|编译选项|编译参数|输入材料|输出文件|实验步骤',value)):
                valid=False
            labels.append(label)
        valid = valid and (len(labels)==1 or tuple(labels)==EQUIPMENT_LABELS)
        valid = valid and visible_count<=budget
        if visible_count>budget: instruction+=f' 当前正文{visible_count}个可见字符。'
    else:
        items = blocks[0].get('items', []) if len(blocks) == 1 and blocks[0].get('type') == 'list' else []
        valid = isinstance(items, list) and bool(items) and all(isinstance(item, str)
            and item.strip() and len(item.strip().splitlines()) == 1
            and not re.match(r'^\s*\d+[.．、)]', item) for item in items)
    if not valid:
        from .report_protocol import ProtocolError
        raise ProtocolError(section['heading'] + '.blocks', instruction, [b.get('type') for b in blocks])

FINDING_PRESENTATION_GUIDANCE = (
    '硬性写作规则：同一个发现全篇只在一个位置呈现一次。同一数据、观察或结论改写措辞仍算重复。'
    '已在表格或图片中展示的信息，由图表独占呈现位置；正文只分析规律的含义、产生原因或与实验问题的关系，'
    '不得换成文字重报数值、类别、趋势、对照结果或图中步骤。图前只交代要看的问题，图后直接进入解释。'
    '已呈现的发现可用图表号或章节号定位，回指不得重述发现。'
    '总结只收束全文对实验问题的回答，采用综合层次的新归纳，禁止逐个复述已出现的发现。'
)

W01_CLARIFICATION = '操作理由直接正面说明要探究的问题或要观察的现象，避免“已有结果还不能说明……所以还要……”“只说明……还需确认……”的否定式铺垫。可用“为了探究……”“为了进一步确认……”说明具体目的，保留原任务与必要验证，不要求每段统一套句式。'
DEFENSIVE_WRITING_GUIDANCE = (
    'W01是硬性要求。逐句判断用途：自我辩护、重复否定、无关免责或用前一项的不足为下一项铺垫，'
    '即使事实无误也必须改写。直接说明操作目的和证据支持的发现。'
    '用自然的关联词说明真实的顺序、因果和转折；“不是……而是……”可以用于纠正有实际意义的事实误解。'
    '真实故障、对照条件和影响结论的证据，用简洁陈述交代。'
    '报告正文不主动写实验局限、能力边界、未执行事项、未验证事项或“不能据此判断”等限定。'
    '只有指导书明确要求报告局限性，或该事实直接影响本次任务结论时，才用事实句简短交代。'
    '所有章节直接写对象、任务、条件、观察或结论，不解释本章“不讲什么”，不声明边界，不补防御性说明。'
    '编号优先使用“1.”、“2.”和“（1）”、“（2）”；正文和标题尽量不用中点“·”作为分隔符。'
    '指导书要求的指标若缺少必要实测输入，在结果处用一句话交代缺失的量及指标状态。'
    '这类事实句可以用“未记录”“未计算”或“无法计算”，不按 W01 判错，也不要求换同义词或补出数值。'
)

# Reserve deterministic matches for explicit defensive constructions.
DEFENSIVE_TRANSITION = re.compile(
    r'(?:只|仅)(?:能|可)?(?:检验|验证|说明|确认|回答|考察)[^。！？；]{0,55}'
    r'(?:还(?:没有|未|没|需|不能)|尚未|仍未)'
    r'|(?:不足以|不能(?:完全)?|尚不能)说明[^。！？；]{0,80}'
    r'(?:所以|因而|因此)[^。！？；]{0,16}(?:还需|还要|必须再|需要再|另做)'
)

IMPLEMENTATION_DETAILS_GUIDANCE = (
    'W06/W08要求正文避免把文件名、测试用例名、变量字段、命令选项、参数明细和代码符号串堆成清单。'
    '先判断它是否帮助读者理解当前操作或结论。必要的单个名称、变量、参数或语法符号可以保留，'
    '多项细节适合放进表格；教师明确要求或某段机制确实需要时，可以用短代码块说明。'
    '正文应把这些细节放在操作、观察和解释中，不因规则而删掉关键证据。'
    '图表与正文联动：规划时给每张图指定实际承担实验步骤、结果或分析的章节、要回答的问题和紧邻的解释位置；'
    'Writer先写图前引入，再放图，随后直接分析图中信息的意义。没有对应论述任务的图不插入。'
)

RULES = {
    'objectives': {'name': '目的与任务', 'question': '要解决什么问题、获得什么能力或达到什么目标？',
        'include': '简述实验对象、核心问题、学习或验证目标和各项任务。默认不写成功门槛；确需保留且有明确来源的关键目标指标，只能随相应任务简要交代，须区分目标与实际成绩。',
        'exclude': '不单列成功门槛、达标标准或验收条件的段落、列表和小节。不宣讲课程评分、教师评价重点、验收清单或报告写作计划。不写具体学习率、批大小、种子、轮数、张量形状、API、程序变量、脚本名、代码、操作流程或已取得的结果；数值容差、逐项检查判据放方法或结果。作为研究对象的概念可以提，例如研究学习率对收敛的影响，但不在此报取值。',
        'detail': '对象和任务层级；目标指标至多附带在对应任务中，不作为目的节的独立论述。'},
    'background': {'name': '背景与问题', 'question': '为什么值得做这个实验？',
        'include': '交代相关场景、当前问题及其与本次实验的关系，顺势引出实验问题。',
        'exclude': '不泛讲学科历史，不提前介绍全部实现和实验结果，不堆无关概念。', 'detail': '问题与动机层级；只保留理解必要的背景。'},
    'principles': {'name': '原理与理论', 'question': '理解本实验需要哪些机制？',
        'include': '围绕实际采用的方法解释必要概念、变量含义和机制，关键公式与推导按实验需要展开。',
        'exclude': '不写教材式百科，不把代码API介绍当原理，不在此报运行配置和结果，不重复步骤节。',
        'detail': '数学符号和公式可以必要且清晰；公式变量不等于程序变量。只保留能帮助理解后文的推导。'},
    'environment': {'name': '环境、材料与数据', 'question': '实验依赖什么条件和输入？',
        'include': '简述影响实验的设备、软件条件和材料来源。数据规模、标签、划分及预处理若决定实验设计，应安排到方法中充分解释。必要版本/配置集中放表。',
        'exclude': '不铺陈安装过程、路径、依赖列表、机器信息、留痕、自证或核查状态，不抢占核心过程和分析篇幅。',
        'detail': '独立的实验器材或实验环境按固定短格式填写；环境与数据或方法合写时按实际职责组织。'},
    'procedure': {'name': '设计、方法与步骤', 'question': '为了回答问题，关键操作怎样安排、为何这样安排？',
        'include': '说明实验设计、数据处理与评价安排、关键操作目的、重要选择、真实调整及中间观察。用操作本身说明校验对象和比较依据，不反复解释“断言”等程序术语；跨实验直接交代新任务的对象、目的或与前一项的实际关系。',
        'exclude': '不逐行解释代码，不把变量/API/命令串成流水账；不列所有超参和实现细枝末节。',
        'detail': '重要控制变量/配置集中放表，流程适合图示。代码默认省略；仅教师明确要求或确为理解关键机制不可替代时保留最短片段。'},
    'results': {'name': '结果与观察', 'question': '实际发生了什么、最重要的发现是什么？',
        'include': '按实验问题呈现关键观察和必要比较；表格呈现数值，图片展示趋势和对照，正文分析变化的原因与意义。',
        'exclude': '不复述图表中已经呈现的任何结果，不重讲方法，不靠结果列表代替发现；未经支持的原因不写成测量事实。',
        'detail': '图表承载选中的数值和对照，正文直接说明它们对实验问题意味着什么。展示顺序体现主次，图表靠近相应分析。'},
    'analysis': {'name': '分析与讨论', 'question': '这些观察意味着什么、为什么会这样？',
        'include': '按实际任务明确数据回答的问题、支撑判断的关键比较及可得的结论。每项实验至少选一个有代表性的样例、对照或表格中的具体观察，说明它如何支撑判断。解释最重要的变化、差异或错误分布及其含义；有依据的发现就在分析章直接写明，不把结论留到总结。',
        'exclude': '不重新抄结果表，不堆术语，不添加假想质疑、免责、可靠性自证或额外核查任务。',
        'detail': '只回引推理所需的关键现象或数字，每段应带来新的解释和判断。'},
    'conclusion': {'name': '总结与结论', 'question': '最终回答了什么、得到哪些值得保留的判断？',
        'include': '简短归纳并直接陈述结果分析已经得出的主要结论和实验认识；可以保留一项决定性结果。',
        'exclude': '不逐章复述，不重列参数/全套结果，不引入新实验或新论据，不逐项宣布通过或加免责段落。不习惯性用“只能说明、尚不能说明、还需确认”削弱已有成果，也不把结论改成新一轮验证计划。',
        'detail': '高度概括，篇幅短于核心过程和分析；一条结论应有前文依据。'},
    'reflection': {'name': '心得、反思与改进', 'question': '这次具体过程改变了什么理解或做法？',
        'include': '基于真实问题、调整、取舍和认识，说明下一次会怎样做；尊重用户对心得代拟的已有授权。',
        'exclude': '不写万能感想，不再总结所有结果，不把新计划冒充已执行。',
        'detail': '选少量有价值的具体经验展开，不记录无关调试流水账。'},
    'questions': {'name': '思考题与指定回答', 'question': '教师提出的这个具体问题，答案和依据是什么？',
        'include': '对题直接作答，给出必要原理和本次证据；已有分析回答过时简要承接。',
        'exclude': '不以答题为由复制整节分析，不补题目未要求的审计、证明或大段代码。',
        'detail': '按问题需要决定深度，覆盖问题本身，避免格式性重复。'},
    'references': {'name': '参考资料', 'question': '确实使用了哪些外部来源？',
        'include': '列实际采用的指导书、文献和官方资料，按模板统一格式。',
        'exclude': '不把内部日志目录、模型自评和来源自证塞进参考资料。',
        'detail': '提供必要且可定位的书目信息，不作新的论证。'},
    'abstract': {'name': '摘要或概述（模板确有要求时）', 'question': '整项工作解决了什么、如何做、得到什么？',
        'include': '用很短的完整叙述概括问题、核心方法和主要发现；允许少量决定性结果。',
        'exclude': '不写实现参数、代码、背景长论，不另造模板没有的摘要节或标题下摘要小字。',
        'detail': '摘要是正常正文层级的规定章节，不是附加副标题或小字导读。'},
    'appendix': {'name': '附录（模板或提交要求需要时）', 'question': '哪些必要材料不适合打断正文？',
        'include': '只收录明确要求或理解工作确实必要的完整材料，正文用简洁定位关联。',
        'exclude': '不把删掉的无关代码、参数和日志全部转存为附录，不自动新增附录凑篇幅。',
        'detail': '后台材料可以留在工程，只有读者确有需要时才进入提交报告。'},
    'support': {'name': '其他或复合栏目', 'question': '这个栏目在教师模板中实际承担什么职责？',
        'include': '按实际内容和用户要求匹配上述职责；复合栏目按问题组织子段，可兼有多种职责。',
        'exclude': '不为套分类新增或改名模板章节；无法从标题判断时不臆定为某一类。',
        'detail': '以本节具体任务为准，执行通用写作要求。'},
}

ALIASES = [
    ('objectives', ('目的', '目标', '任务要求', 'aim', 'objective', 'purpose')),
    ('reflection', ('心得', '体会', '反思', 'reflection', 'lessons learned')),
    ('questions', ('思考题', '思考与练习', '出口题', '课后问题', '思考问题', 'questions', 'exercises')),
    ('references', ('参考', '引用文献', 'reference', 'bibliography')),
    ('appendix', ('附录', 'appendix', 'appendices')),
    ('abstract', ('摘要', 'abstract', '概述', 'overview')),
    ('background', ('背景', '引言', '问题提出', 'background', 'introduction')),
    ('principles', ('原理', '理论', '基础知识', 'principle', 'theory')),
    ('environment', ('环境', '配置', '设备', '材料', '数据集', '器材', 'environment', 'setup', 'material', 'dataset')),
    ('procedure', ('步骤', '方法', '设计', '过程', '实施', 'method', 'methodology', 'procedure', 'protocol', 'implementation')),
    ('results', ('结果', '观察', '现象', 'result', 'observation', 'finding')),
    ('analysis', ('分析', '讨论', 'analysis', 'discussion')),
    ('conclusion', ('总结', '结论', 'conclusion', 'summary')),
]

GUIDANCE = '''section_policy是用户当前明确的章节职责与版面规则，按本次教师模板的内容理解适用，优先于旧profile与历史案例。
章节名可能不同，按职能匹配；复合章按子段职责分工，保留教师原章节名和顺序，不要求新增一套章节。
目的节只讲实验对象、问题、目标和任务，禁止具体实现参数、代码/API和步骤。默认不写成功门槛；确需保留的关键目标指标，只能随相应任务简要交代，不能另起段落、列表或小节汇总门槛，也不得混入已取得的结果。
全篇默认不展示代码细节；仅教师明确要求或不可替代的关键机制保留最短片段。数学原理的必要公式不等于代码细节。
技术解释采用直接、准确的书面语，避免“参数往哪走”“损失函数推着参数走”等比喻或拟人化表达，直接说明参数更新方向、梯度与优化器的作用。自然衔接依靠内容关系，不依靠形象化措辞；正常数学术语不因含方向、传播等字样被判为比喻。
操作目的正面说明所探究的问题或所观察的现象，避免“已有结果还不能说明……所以还要……”“只说明……还需确认……”式铺垫；允许“为了探究……”“为了进一步确认……”等有具体目的的表达，不机械套用。结论直接陈述已有发现和认识，宣称范围与实验结果一致，不习惯性补防御式限定。检查和修订建议也遵守同一要求。
不添加副标题、标题下说明行、导读小字、版本注、来源自证或正文小注。图片放在实际承担步骤、结果或分析的栏目，并遵循模板明确规定的位置。caption仅用于图注或表注；不借注释塞入额外论证。
只写正文、模板规定的信息与必要图表；内部记录留后台。不要把页面界面提示或运行状态写入报告。除指导书明确要求外，不单列局限性、边界、未执行事项或未验证事项。'''
GUIDANCE += '\n' + FINDING_PRESENTATION_GUIDANCE
GUIDANCE += '\n独立的开头栏目各规划一个写作部分。下列短栏写法在模板未明确规定成文形式时适用。' + '\n'.join(
    f'{heading}：{instruction}' for heading, (_, instruction) in OPENING_RULES.items()
)


def section_roles(heading):
    normalized = str(heading).casefold()
    matches = [role for role, words in ALIASES if any(
        re.search(r'\b' + re.escape(w) + r'(?:s|es)?\b', normalized) if w.isascii() else w in normalized
        for w in words)]
    return matches or ['support']


def policy_packet(project, payload=None):
    payload = payload or {}
    document = payload.get('document') or payload.get('candidate') or {}
    headings = [s.get('heading', '') for s in document.get('sections', []) if s.get('heading')]
    if not headings:headings = (project.data.get('template') or {}).get('headings', [])
    target = payload.get('target_heading') or payload.get('context', {}).get('heading')
    if not target and len(headings) == 1:target = headings[0]
    return {'version': VERSION, 'guidance': GUIDANCE, 'types': copy.deepcopy(RULES),
            'sections': [{'heading': h, 'roles': section_roles(h)} for h in headings],
            'current_section': {'heading': target, 'roles': section_roles(target)} if target else None,
            'presentation': {'subtitle': False, 'extra_small_notes': False, 'caption_types': ['image', 'table']}}


def structural_issues(document):
    issues = []
    for section in document.get('sections', []):
        roles = section_roles(section.get('heading', ''))
        # Mixed sections are evaluated semantically within their local paragraphs.
        if roles != ['objectives']:continue
        for block in section.get('blocks', []):
            if block.get('type') == 'text' and re.search(r'课程评价|评分标准|考核重点|本实验的?判据',block.get('text','')):
                issues.append({'rule_id':'chapter:student_perspective','severity':'hard','block_ids':[block['id']],
                    'reason':'目的节宣讲课程评价或验收判据，偏离学生实验报告的作者身份与目标职责。',
                    'suggestion':'删去评分与验收说明；直接交代实验问题、学习目标和必要的目标成绩。',
                    'needs_material':False})
            if block.get('type') == 'code':
                issues.append({'rule_id': 'chapter:objectives', 'severity': 'hard', 'block_ids': [block['id']],
                               'reason': '目的节包含代码块，与本节问题/目标职责冲突。',
                               'suggestion': '目的节保留问题与目标，删去代码；仅在教师明确要求或关键机制不可替代时安排到方法相应位置。',
                               'needs_material': False})
    return issues


def preserve_result_tables(original, updated):
    """Prose editing may change captions, but measured cells require a data fix."""
    protected = {b['id']: b for s in original.get('sections', [])
        if 'results' in section_roles(s.get('heading', '')) for b in s.get('blocks', []) if b['type'] == 'table'}
    current = {b['id']: b for s in updated.get('sections', []) for b in s.get('blocks', [])}
    for bid, before in protected.items():
        after = current.get(bid, {})
        if after.get('type') != 'table' or any(before.get(k) != after.get(k) for k in ('headers', 'rows')):
            raise ValueError('文字编辑须保留结果表的原始表头与数据；数据纠错需明确的要求反馈：' + bid)
