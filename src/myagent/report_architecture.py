"""Experiment-centred report planning and core-first production. No model calls here."""
from __future__ import annotations

from .report_section_policy import DEFENSIVE_TRANSITION, IMPLEMENTATION_DETAILS_GUIDANCE, FINDING_PRESENTATION_GUIDANCE
import copy
import re
from .report_evidence import anchor_schema, comparison_schema, validate_finding, story_evidence

VERSION = 2
CARD_SELECTION_VERSION = 6
CARD_SELECTION_VERSIONS = (1, 2, 3, 4, 5, CARD_SELECTION_VERSION)
CURATED_FACTS_VERSION = 3

FACTS_CURATION_GUIDANCE = """claims是交给正文的最终事实清单。逐项问：删掉这条，回答指导书明确提出的问题会缺少关键过程、结果或解释吗？只记录有重大、直接影响的事实，覆盖每项有材料支撑的必做任务及其关键输出；同一事实只写一次，保留来源，简洁概括。排除稳健性审查、补充材料中的弱相关内容、自检、回归、检验实验、审查和只说明结论稳健的记录。指导书指定的样例及其输出属于任务结果。把核心结果和附带检查拆开，只留核心；某材料组没有这类事实就提交空claims。不要把验收要求转写成结果。"""

FACT_CHAIN_GUIDANCE = """各材料批次共用existing_claims这一份已整理的事实清单。依据已确定的必做任务，先对照已有条目，本次只提交新增或补全。同一实际操作、同一次运行的同一输出、同一个观察，视为同一条事实，即使措辞或文件来源不同。只有语义不同且属于必做内容才新增。缺少的关键做法、结果或原因补回已有条目：在claims元素填existing_claim_id（沿用清单中的准确id），保留旧条目正确内容并写出补完后的字段，引用现有事实最直接的原始证据。有原始输出支撑时，报告日志或测试汇总重述同一现象，直接略过；只补出处不同无价值时也略过。本批没有应该新增或补全的内容时，返回claims=[]。优先读本批材料，后批会继续补，只有此时无法厘清的关键事实才跨组读取。"""

FACT_READING_GUIDANCE = """由你根据verified_requirements和experiment_overview决定要读什么。source_context.supplied_files是文件目录；需要时用report_materials的list/search定位，read/read_many读取原件。先确定必做步骤、指定输入与应有输出，优先找直接记录这些内容的主实现与指定样例的原始产物。每次读取应解决一个还缺证据的具体问题；必做内容有直接证据就停止。汇总、日志、更多源码和其他材料按需补读。跨文件把同一项操作和同一次运行的直接结果关联起来，一次提交事实清单；同一输出在源码、日志和原始结果中出现时只记一次。材料类型和文件名仅供你定位，任何已登记的文件均可按需读取。"""

BACKGROUND_PLANNING_GUIDANCE = """请自主组织这份报告，让读者理解具体实验对象、完整系统的功能与所用模型，以及课程实验研究的问题。experiment_overview提供背景知识；在哪里介绍、展开多少、怎样衔接，由你根据材料和读者的理解需要决定。"""

PLANNER_PROTOCOL_GUIDANCE = """story_cards是已整理材料的索引，原文仍可按source_context和reading_map读取。
先理解指导书规定的实际任务和交付结果。选事实只看是否直接说明某项必做任务怎样实现、产出什么、得出了什么结果。用实验过程与发现组织段落，把相关要求自然写入对应论述；按实验自身的关系安排标题和顺序。
拟定每部分要说明的内容时，直接用fact_refs选择能支撑这段叙述的原有事实；从已选事实确定对应材料分组，目录中的其他事实不需要安排篇幅。看到描述的是验证脚本做了什么、覆盖了哪些用例或测试是否通过时，留在后台；看到直接解释必做功能的实现或指定样例的真实输出时，按叙述需要选入。缺省材料、背景和短章节可用空数组。常规自检、回归、压力测试、内部排查和检查汇总都留在后台，不规划正文段落、图表或结论。指导书点名要求运行的样例及其输出属于必做任务的结果。验收指标可随结果简洁交代实测与目标；指标的原因有实质分析价值或被明确要求时再展开。detail_carriers列出选用的载体，无需时可用空数组。
content_ownership只记录选入正文的卡的过程、结果和分析主要放在哪里，引用本次计划的真实章节标题；这些位置可以相同。用focus写清本节要回答的具体问题，用avoid_repeating指出相邻章节中的同一主题在哪里详讲、本节还需要补充什么。优先处理原理、步骤、结果分析和思考题之间容易重复的解释，也照顾目的与内容的分工。
例如，原理说明某项运算为何成立，步骤说明这次如何实现和核对，结果分析说明实际记录回答了什么；思考题可简短回指已有解释，再回答题目尚未覆盖的部分。根据具体实验选择详讲位置，保留教师要求和关键操作，不硬套章节分工。拟定标题时将课堂简称还原成明确的实验对象或操作。
主线说明各实验围绕什么问题、研究什么对象以及相互关系，不只串联技术动作；各部分的开展理由直接说明目的，不把后续实验一律设计成对先前结果不足的补救。计划是内容组织依据，不是让Writer逐字段转述的正文。结果分析部分不能只列图表标题和总体判断。按问题需要选择代表性样例、具体对照或关键观察，必要时再写入计划，Writer据此写出观察、解释和结论。图表计划必须同时记录所属第六或第七节、正文引入和图后解释的任务，图表不作为孤立装饰。
用内容顺序体现逻辑：让关键操作、观察和解释围绕同一个问题推进，按实际需要组织。前文已交代对象和关系时，本节直接推进；只标出跳转时确实需要补的一点背景或联系，避免把承接本身列成写作任务。
先安排报告的主体，按九节模板时把大部分篇幅留给第6节实验步骤和第7节数据及结果分析。前置章节按模板实际内容取舍，模板或用户原稿已写好的部分优先沿用，按明确要求补空缺。短章节直接完成自己的内容任务，不写章节边界说明。原理为空时，用很短的段落交代读懂步骤和结果所必需的机制。原理章不放图片，不展开完整文法、教学示例或实现流程；需要图示时集中放到第六或第七节。指导书中的完整文法、教学示例与实现提示供理解任务使用，只有明确要求呈现或后文确实需要时才展开。规划时主动给原理、总结和改进建议分配较小的篇幅，先保证步骤与分析有足够空间。总结只归纳分析已得出的结论，可带一项真实体会；改进建议只安排一至两段温和的发散性设想，围绕本实验的实现、验证或结果可读性。不得评价、归责或抨击指导书和实验材料；需要说明采用的规则时放到原理或步骤。教师明确要求详细展开时按要求安排。
这些关联用于后续交接，章节组织、内容取舍、解释方式和篇幅由你规划。图片只安排在第六节实验步骤或第七节实验数据及结果分析，其他章节用文字或表格说明，不放图片。图片必须和所属段落联动，图前提出问题，图后直接分析图中信息的意义。"""
CURATED_PLANNING_GUIDANCE = ('\n'.join(
    line for line in PLANNER_PROTOCOL_GUIDANCE.splitlines()
    if not line.startswith(('先理解指导书规定', '拟定每部分', 'content_ownership'))
) + '\nprevious_outputs.story_cards 是事实整理阶段已选定的正文材料。直接据此安排实验过程和发现的顺序，按材料和内容需要自然体现指导书要求。只规划章节、每部分的论述任务、使用的实验任务及图表。实验步骤、用例、实测结果和数据图表必须来自已整理事实；指导书和实验概览用于理解要求与背景。附加验证无需规划，即使已整理事实中偶然夹带了补充验证，也无需为它安排小节或图表。已明确要求但未整理出的证据作为缺项记录。每部分用owned_fact_refs放置负责呈现或分析的条目，引用已整理材料中的fact_ref，同一编号全篇只分配一次。'
    '表格或图片展示的发现和与之对应的分析安排在同一部分。短栏目或只做过渡的部分用空数组；'
    '已有表图或其他部分覆盖的同义条目无需另安排。' + '\n' + FINDING_PRESENTATION_GUIDANCE + '\n' + IMPLEMENTATION_DETAILS_GUIDANCE)

PLANNER_PROTOCOL_GUIDANCE += "\n" + IMPLEMENTATION_DETAILS_GUIDANCE

STORY_CARDS = """你是实验叙事整理角色。依据已保存的真实facts和原始材料，按实际实验身份组织事实卡。
材料按results/figures/code分类只是存储类别，不是实验身份；同一个实验的代码、结果、图关联到同一张卡。
每张卡说明实验问题、初态、关键操作及理由、中间观察、主要发现及解释、对应图表/代码来源。
reason正面说明该操作服务的具体问题或观察目的，不先用“只说明、还不能说明、还需确认”否定先前结果再引出下一步；原任务无需包装为追加验证。保留真实操作和必要验证，不为改变句式删掉任务。
候选事实只保留直接说明指导书规定的任务怎样实现、产出什么、得出什么结果的关键操作与观察。同一观察归入一个最合适的主题，引用已有相关来源，避免在多张卡重复。自检、回归检查、压力测试和内部排查留在原始记录里。指导书明确要求的测试样例、调优对照或故障诊断按实验任务保留。只摘取关键步骤，避免逐行抄代码、列全部参数。
已有成功结果直接复用。后台不做额外审计、消融或猜想证明；这些内部工作状态不写入报告正文。
事实卡是后台组织材料，路径/ID和完整数值不直接进入报告正文。已提供原件足够时直接提交，不反复读取。
结果用finish_stage提交experiments数组，每项含id/title/question/initial_state/task_ids/source_ids/procedure/findings/assets。
procedure每项含action/reason/observation/source_ids；findings每项含observation/interpretation/source_ids；
assets每项含source_id/carrier(image|table|code)/purpose。只选择重要材料。
提交evidence_version=1。每条findings另含evidence_kind(measured|code|source_text)、interpretation_kind(principle|hypothesis|none)、anchors和comparisons。
实测发现用anchors=[{source_id,pointer,value}]引用JSON中的具体标量原值，value保留完整原值不四舍五入。涉及大小/相等关系时用comparisons=[{left:当前anchors下标,operator:lt|le|eq|ge|gt,right:下标}]表达，程序将读取原件核对。
无数值比较时comparisons=[]；代码/文本观察可anchors=[]。interpretation只放已知原理或候选解释，不把推测写进observation；没有必要解释时interpretation为空且kind=none。
数值记录、机制原理和因果推测必须分开；不从一次训练推出未做的结构/特征归因。"""

ARCHITECTURE_GUIDANCE = """
当前采用实验叙事与信息归属结构（版本2）。story_cards按实验组织真实过程与发现。
编排时每部分提供card_ids和detail_carriers；每项细节载体含source_id/carrier(image|table|code)/purpose。
content_ownership为选入正文的卡指定procedure_section/result_section/analysis_section（模板中的准确标题，可同章）。
按问题安排关键过程、观察与解释；同一事实的详细展开只安排一个主要位置，跨章仅作必要回指。
独立的实验器材或实验环境栏目按section_policy的固定短格式列实际设备和软件。目的、原理、总结从简，核心步骤、结果和分析占主要篇幅。
不要以字数目标扩写。日志目录、SHA、审计和自检状态留在后台。
合同中presentation_scope=background的提交材料继续保存，正文无需自检表、未核验列、目录差异或免责说明。旧acceptance里的正文安排不覆盖用户本轮要求；检查反馈遵守同一分工。
正文用自然语言说明关键操作、已有依据的理由、发现和解释；重要密集参数/结果放表、趋势比较放图。代码默认省略，只有教师明确要求或关键机制不可替代时才保留最短片段。
不逐行讲代码。图表呈现的内容由图表承载，正文解释其意义。不为自证安排额外实验。删除免责话术、假想反例及其证明；直接作有事实支持的判断。
为证明产物可信而做的PNG像素扫描、行数统计等保存在后台，正文围绕实验图像和真实结果解释。
必做问答与检查点可由已有分析承担，覆盖内容即可，不强制重复新增同义小节或再复制图表。
三项实验各自v0/v1形成三组调优对照，不因“三轮”自行增加第三版本，也不写“第三轮未完成”的免责段落。
四角交替标签的XOR线性不可分。
控制器先生成步骤、结果、分析，再写简短前后章节；最终PDF始终按模板展示。
后写的目的/原理/环境/总结利用已写核心内容，避免再次展开核心数值与操作。
"""

def section_role(heading):
    from .report_section_policy import section_roles
    roles=section_roles(heading)
    return next((role for role in ('analysis','procedure','results','environment') if role in roles),roles[0])

def production_order(design):
    sections=design['sections']
    return sorted(range(len(sections)),key=lambda i:(0 if section_role(sections[i]['heading']) in ('procedure','results','analysis') else 1,i))


def writing_design(outline):
    """Carry the joint prose/visual plan across both sample and full writing."""
    return {key:copy.deepcopy(outline[key]) for key in
            ('writing_plan_version','card_selection_version','main_thread','sections','content_ownership','figure_plan') if key in outline}


def active_design(project):
    outputs=project.data.get('report_workflow',{}).get('outputs',{})
    outline=outputs.get('outline') or {}
    saved=project.data.get('report_design') or {}
    # Older checkpoints dropped shared metadata. Recover only when their section
    # plans are identical; a revised outline must not overwrite an accepted plan.
    if not saved:return outline
    if saved.get('sections')==outline.get('sections'):return {**outline,**saved}
    return saved


WRITER_SECTION_GUIDANCE = """先按当前部分计划的focus确定本节要让读者明白什么，结合avoid_repeating与content_ownership决定哪些细节应在别处展开。即使核心章先写，开头也按读者的阅读顺序交代首次需要知道的对象和任务。
模板同时有实验目的、实验内容和实验步骤时，目的交代对象及要回答的问题，内容概括任务和真实关系，步骤讲实际怎么做及关键条件。彼此独立的练习可以并列介绍，同一项任务只在需要它的地方展开实现。
写当前部分时，若同一机制已有详讲位置，按需回指。图表已展示结果时，正文直接分析其含义或原因。实测观察、已有原理与可能解释各自说清，保留关键实验条件。
上下文能接上时直接写当前的操作、观察或解释。对象换了或读者容易跟丢时，用短句点明必要的联系即可。避免为了体现逻辑而复述上一节、预告下一节或专写过渡段；篇幅留给实验本身。
模板已有成段的原理、目的或内容时，沿用适用于本次任务的正文，只补空缺；区分模板正文、占位文字和填写提示。需自行写原理时，简要交代对象和理解后文所需的机制。原理写清之后直接收束，剩余预算无需写满。保留教师明确要求及理解后文所必需的内容。总结只收束已有发现与一项实际体会，改进建议聚焦最值得做的事项。
初稿就把总结和建议写到各自职责上：总结直接回答实验问题，提炼前文最重要的认识；建议指出下一次具体改什么，可简短引用促成该建议的真实观察。数值比较或按日志推算时，先把条件与对应记录对上，再写结论。
参数、变量名和数值紧跟它们支撑的操作或判断。若一组细节已经由图表、公式或代码说明，正文推进到该怎么理解。句首根据具体对象和上文关系安排，避免连续套用同一种目的句或总结句。心得从实际操作、观察或遇到的问题出发，个人想法以已有材料为准。"""


WRITING_HANDOFF_GUIDANCE = """writing_handoff是本次唯一的章节编排入口，由保存的计划与图表产物组成。计划决定内容位置，不决定事实真假；原始证据与story_evidence中的原值优先于main_claim和explanation_depth。
planned_visuals说明本节图表要回答什么以及实际制作状态。只选对当前论述有用且已提供的图表，不把计划当已生成，不因总目录里有图而全部插入。
图内说明使用中文，英文旧图应由图表角色用源数据另绘中文版。quality=unverified不是质量通过。图表正文引用使用{{figure:图片块ID}}，排版按实际出现顺序统一编号，图注不自行编号码。
图表承载观察与比较，正文分析其意义；content_ownership用于决定何处详细展开、何处简要承接。
used_carriers列出已经放置的图表及其真实块ID、标题和章节；同一载体一般只完整展示一次，其他章节引用已有编号并解释新问题。
current_chapter_carriers和image_ownership列出已占用图片，其他部分只能使用{{figure:已有图片块ID}}引用，不得再次插入；图片首次插入后由程序登记唯一所属位置。
交接单与当前证据不一致时查原始产物并直接纠正或省略错误计划。无需写纠错经过、免责或额外核查段落。"""


WRITER_SECTION_GUIDANCE += "\n" + FINDING_PRESENTATION_GUIDANCE


def writing_handoff(project,payload):
    """Join section intent and producer outputs without another model call.

    Inspired by PaperOrchestra's shared outline (§4); implemented locally for
    teacher templates and resumable report parts. No prompts/code are imported.
    """
    design=active_design(project)
    heading=payload.get('target_heading')
    section=next((s for s in design.get('sections',[]) if s['heading']==heading),None)
    if not section:return {}
    part=payload.get('part_plan')
    if not isinstance(part,dict) and isinstance(payload.get('focus'),dict):part=payload['focus']
    parts=[part] if isinstance(part,dict) else [p for p in section.get('parts',[])
                                             if p.get('focus')==payload.get('focus')]
    if not parts:parts=section.get('parts',[])
    card_ids={cid for part in parts for cid in part.get('card_ids',[])}
    fact_refs={ref for part in parts for ref in part['fact_refs']} if parts and all('fact_refs' in part for part in parts) else None
    outputs=project.data.get('report_workflow',{}).get('outputs',{})
    cards=scope_story_cards(outputs.get('story_cards',{}),card_ids,fact_refs,label_entries=fact_refs is not None)
    produced={}
    for key in ('figures','figures_full'):
        for figure in (outputs.get(key) or {}).get('figures',[]):
            if figure.get('id'):produced[figure['id']]={**copy.deepcopy(figure),'output_key':key}
    visuals=[]
    for figure in design.get('figure_plan',[]):
        if figure.get('section')!=heading:continue
        planned={k:copy.deepcopy(figure[k]) for k in
                 ('id','kind','purpose','source_ids','caption_draft','reference_ids','reference_use','design') if k in figure}
        planned['production']=copy.deepcopy(produced.get(figure.get('id'),{'status':'not_produced'}))
        visuals.append(planned)
    return {'version':1,'heading':heading,'section_role':section_role(heading),
            'main_thread':design.get('main_thread',''),
            'section_map':[{'heading':s['heading'],'role':section_role(s['heading'])} for s in design.get('sections',[])],
            'parts':copy.deepcopy(parts),
            'content_ownership':[copy.deepcopy(o) for o in design.get('content_ownership',[])
                                 if o.get('card_id') in card_ids],
            'planned_visuals':visuals,
            'story_evidence':story_evidence(project,cards),
            **({'selected_procedures':[row for card in cards.get('experiments',[]) for row in card.get('procedure',[])]}
                if fact_refs is not None else {}),
            'used_carriers':[{'heading':s['heading'],'id':b['id'],'type':b['type'],
                **{k:copy.deepcopy(b[k]) for k in ('path','caption','headers') if k in b}}
                for s in project.data.get('writing_draft',{}).get('sections',[])
                for b in s.get('blocks',[]) if b['type'] in ('image','table')],
            'current_chapter_carriers':copy.deepcopy(payload.get('current_chapter_carriers',[])),
            'image_ownership':copy.deepcopy(project.data.get('report_image_owners',{})),
            'completed_headings':[s['heading'] for s in project.data.get('writing_draft',{}).get('sections',[])],
            'notice':'Producer status is reported output, not independent verification. Facts remain in source evidence.'}


def writer_packet(payload,handoff):
    """Replace duplicate planning surfaces; never mutate the saved caller state."""
    packet=copy.deepcopy(payload)
    for key in ('part_plan','report_map','report_structure','completed_headings'):
        packet.pop(key,None)
    if isinstance(packet.get('focus'),dict):
        packet['focus']=packet['focus'].get('focus','')
    if isinstance(packet.get('continuity'),dict):
        packet['continuity'].pop('main_thread',None)
    packet['writing_handoff']=handoff
    return packet

def card_schema(project=None,*,anchored=True):
    string={'type':'string'};strings={'type':'array','items':string}
    def obj(fields):return {'type':'object','properties':fields,'required':list(fields)}
    procedure=obj({**{k:string for k in ('action','reason','observation')},'source_ids':strings})
    finding=obj({**{k:string for k in ('observation','interpretation')},'source_ids':strings})
    if anchored:finding['properties'].update(evidence_kind={'type':'string','enum':['measured','code','source_text']},
        interpretation_kind={'type':'string','enum':['principle','hypothesis','none']},
        anchors={'type':'array','maxItems':12,'items':anchor_schema()},
        comparisons={'type':'array','maxItems':12,'items':comparison_schema()})
    if anchored:finding['required']+=['evidence_kind','interpretation_kind','anchors','comparisons']
    asset=obj({'source_id':string,'carrier':{'type':'string','enum':['image','table','code']},'purpose':string})
    card=obj({**{k:string for k in ('id','title','question','initial_state')},'task_ids':strings,'source_ids':strings,
              'procedure':{'type':'array','items':procedure},'findings':{'type':'array','items':finding},'assets':{'type':'array','items':asset}})
    if project is not None:
        card['properties']['task_ids']={'type':'array','minItems':1,'items':{'type':'string','enum':[t['id'] for t in project.data['tasks']]}}
    return obj({**({'evidence_version':{'type':'integer','enum':[1]}} if anchored else {}),
                'experiments':{'type':'array','minItems':1,'maxItems':12,'items':card}})

def validate_cards(result,project):
    cards=result.get('experiments');seen=set()
    if not isinstance(cards,list) or not 1<=len(cards)<=12:raise ValueError('需要1—12张实际实验事实卡')
    sources={s['id'] for s in project.data['report_sources']}|{m['id'] for m in project.data['materials']}
    tasks={t['id'] for t in project.data['tasks']}
    def refs(values):
        if not isinstance(values,list) or not values or any(not isinstance(v,str) for v in values) or set(values)-sources:
            raise ValueError('事实卡需引用已登记的source_ids')
    for card in cards:
        for key in ('id','title','question','initial_state'):
            if not isinstance(card.get(key),str) or not card[key].strip():raise ValueError('事实卡缺少'+key)
        if card['id'] in seen:raise ValueError('事实卡ID重复')
        seen.add(card['id']);refs(card.get('source_ids'))
        if not card.get('task_ids') or set(card['task_ids'])-tasks:
            raise ValueError(card['id']+' 的task_ids='+str(card.get('task_ids'))+'无效；报告材料任务可用值='+str(sorted(tasks))+'。执行日志的T编号仅保留在原始来源，事实卡task_ids使用报告材料所属E编号；实验身份由卡id/title表达。')
        for key,fields in (('procedure',('action','reason','observation')),('findings',('observation','interpretation'))):
            rows=card.get(key)
            if not isinstance(rows,list) or not rows:raise ValueError('每张卡需要真实'+key)
            for row in rows:
                needed=fields if result.get('evidence_version')!=1 else fields[:1]
                if any(not isinstance(row.get(f),str) or not row[f].strip() for f in needed):raise ValueError('事实卡条目缺少'+str(needed))
                refs(row.get('source_ids'))
                if key=='findings' and result.get('evidence_version')==1:validate_finding(project,row)
        if not isinstance(card.get('assets'),list):raise ValueError('assets需要数组')
        for asset in card['assets']:
            refs([asset.get('source_id')])
            if asset.get('carrier') not in ('image','table','code') or not asset.get('purpose'):raise ValueError('材料需指定展示载体和用途')

def validate_ownership(outline,cards,source_ids):
    ids={c['id'] for c in cards.get('experiments',[])}
    headings={s['heading'] for s in outline['sections']}
    owners=outline.get('content_ownership',[])
    for owner in owners:
        for field in ('procedure_section','result_section','analysis_section'):
            if owner.get(field) not in headings:
                from .report_protocol import ProtocolError
                raise ProtocolError('content_ownership.'+str(owner.get('card_id'))+'.'+field,
                    {'模板或自主计划的真实章节标题':sorted(headings)},owner.get(field))
    assigned=set()
    entries=card_entry_index(cards)
    for section in outline['sections']:
        for part in section['parts']:
            if not isinstance(part.get('card_ids'),list) or set(part['card_ids'])-ids:raise ValueError('每部分需有真实card_ids数组，可为空')
            assigned.update(part['card_ids'])
            refs=part.get('fact_refs')
            if refs is not None and (not isinstance(refs,list) or
                    any(not isinstance(ref,str) or ref not in entries or entries[ref] not in part['card_ids'] for ref in refs)):
                raise ValueError('fact_refs须引用本部分card_ids对应的真实事实条目')
            if not isinstance(part.get('detail_carriers'),list):raise ValueError('每部分需给detail_carriers数组，无密集细节时为空')
            for detail in part['detail_carriers']:
                if detail.get('source_id') not in source_ids or detail.get('carrier') not in ('image','table','code') or not detail.get('purpose'):
                    raise ValueError('细节载体须引用真实来源，说明展示用途')
    expected=assigned if outline.get('card_selection_version') in CARD_SELECTION_VERSIONS else ids
    if {o.get('card_id') for o in owners}!=expected or len(owners)!=len(expected):raise ValueError(
        'content_ownership须为每张选用卡指定一次主要位置；expected='+str(sorted(expected))+
        '，actual='+str([o.get('card_id') for o in owners]))
    if assigned!=expected:raise ValueError('旧版编排要求全部实验卡均安排到具体部分')

def selected_card_ids(design):
    return {cid for section in design.get('sections', []) for part in section.get('parts', [])
            for cid in part.get('card_ids', [])}


def planning_fact_index(facts, tasks):
    """Group the upstream-curated claims for task-based delivery to the Writer."""
    titles={t['id']:t.get('title',t['id']) for t in tasks}
    groups={}
    seen=set()
    for claim in facts.get('claims',[]):
        signature=(claim.get('observation',''),claim.get('interpretation',''),
                   tuple(sorted(claim.get('source_ids',[]))),tuple(claim.get('source_lines',[])))
        task_ids=tuple(sorted(tid for tid in claim.get('task_ids',[]) if tid in titles))
        if (task_ids,signature) in seen:continue
        seen.add((task_ids,signature))
        if task_ids not in groups:
            label='、'.join(titles[tid] for tid in task_ids) or '通用实验事实'
            groups[task_ids]={'id':f'facts-{len(groups)+1}','title':label,'task_ids':list(task_ids),
                              'source_ids':[],'findings':[]}
        card=groups[task_ids]
        card['findings'].append(copy.deepcopy(claim))
    for card in groups.values():
        card['source_ids']=sorted({sid for row in card['findings'] for sid in row.get('source_ids',[])})
    return {'mode':'curated_facts','experiments':list(groups.values())}


def card_entry_index(cards):
    return {f"{c['id']}:{kind}:{i}":c['id'] for c in cards.get('experiments',[])
            for kind in ('procedure','findings') for i,_ in enumerate(c.get(kind,[]))}


def scope_story_cards(cards, card_ids=None, fact_refs=None, *, label_entries=False):
    scoped=copy.deepcopy(cards)
    for card in scoped.get('experiments',[]):
        if card_ids is not None and card['id'] not in card_ids:continue
        for kind in ('procedure','findings'):
            rows=[]
            for i,row in enumerate(card.get(kind,[])):
                ref=f"{card['id']}:{kind}:{i}"
                if fact_refs is not None and ref not in fact_refs:continue
                if label_entries:row['fact_ref']=ref
                rows.append(row)
            if kind in card:card[kind]=rows
        if fact_refs is not None:
            wanted={sid for kind in ('procedure','findings') for row in card.get(kind,[])
                    for sid in row.get('source_ids',[])}
            card['source_ids']=sorted(wanted)
            card['assets']=[a for a in card.get('assets',[]) if a['source_id'] in wanted]
            card.pop('initial_state',None)
    if card_ids is not None:
        scoped['experiments']=[c for c in scoped.get('experiments',[]) if c['id'] in card_ids]
    return scoped


def structure_packet(project, card_ids=None, fact_refs=None):
    state=project.data['report_workflow'];design=active_design(project)
    experimental=project.data.get('report_revision_mode','stable')=='experimental'
    cards=scope_story_cards(state['outputs'].get('story_cards',{}),card_ids,fact_refs,
                            label_entries=fact_refs is not None)
    return {'version':VERSION,**({'story_evidence':story_evidence(project,cards)} if experimental else
            {'story_cards':copy.deepcopy(cards)}),
            'content_ownership':design.get('content_ownership',[]),
            'section_roles':[{'heading':s['heading'],'role':section_role(s['heading'])} for s in design.get('sections',[])],
            'production_order':[design['sections'][i]['heading'] for i in production_order(design)] if design.get('sections') else [],
            'guidance':ARCHITECTURE_GUIDANCE}

def structure_observations(design):
    rows=[{'heading':s['heading'],'role':section_role(s['heading']),
           'planned_chars':sum(p['character_budget'] for p in s['parts'])} for s in design['sections']]
    total=sum(r['planned_chars'] for r in rows)
    return {'sections':rows,'core_budget_share':sum(r['planned_chars'] for r in rows if r['role'] in ('procedure','results','analysis'))/max(1,total),
            'notice':'结构观察供编排和整合调整，不作为教师评分或硬性长度门槛。'}


def editorial_candidates(document):
    """Locate user-priority edits; the Agent decides wording and preserves real facts."""
    issues=[]
    for section in document['sections']:
        for block in section['blocks']:
            if block['type']!='text':continue
            text=block['text'];reasons=[]
            if DEFENSIVE_TRANSITION.search(text):
                reasons.append(('W01','移除防御性对照、假想反例、边界免责和PNG核查推演；直接写实际操作与发现。保留教师必做的调优和故障事实，用简洁直接表达。不补免责替代句。'))
            numbers=re.findall(r'(?<![A-Za-z])[-−]?\d+(?:\.\d+)?(?:%|e[-+]?\d+)?',text)
            identifiers=re.findall(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?',text)
            if len(numbers)>=5 or len(identifiers)>=10:
                reasons.append(('W06','正文数字/变量/步骤密集。图表已呈现的信息留在图表，正文解释其含义。把过程写成操作目的、选择与关键观察，删除无关细节。'))
            for rule,suggestion in reasons:
                issues.append({'rule_id':rule,'severity':'hard','block_ids':[block['id']],
                    'reason':'用户明确约束的编辑候选：'+text[:200], 'suggestion':suggestion,'needs_material':False})
    return issues
