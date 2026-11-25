"""Require explicit assessments of the user's writing rules at review boundaries."""
from __future__ import annotations

from .report_section_policy import IMPLEMENTATION_DETAILS_GUIDANCE, DEFENSIVE_WRITING_GUIDANCE
import copy
from .report_context import fingerprint
from .report_writing import profile_for
from .report_section_policy import RULES,section_roles

VERSION = 6

REFLOW_PRIORITY = {'W04':0,'W05':1,'W03':2,'SECTION':2,'W06':3,'W01':4}


def select_reflow_tasks(document,issues,*,limit=5,locked=()):
    """Prioritize at most five prose blocks without changing historical reviews."""
    if not 1<=limit<=5:raise ValueError('整段重流一次最多5个正文块')
    blocks={b['id']:b for s in document['sections'] for b in s['blocks']}
    order={bid:i for i,bid in enumerate(blocks)};locked=set(locked);grouped={}
    for index,issue in enumerate(issues):
        rules=[r for r in [issue.get('rule_id'),*issue.get('related_rule_ids',[])] if r in REFLOW_PRIORITY]
        if issue.get('severity')!='hard' or not rules:continue
        for bid in issue.get('block_ids',[]):
            if bid in locked or blocks.get(bid,{}).get('type')!='text':continue
            task=grouped.setdefault(bid,{'block_id':bid,'rule_ids':[],'issue_indices':[],'issues':[]})
            task['rule_ids']=list(dict.fromkeys([*task['rule_ids'],*rules]))
            task['issue_indices'].append(index)
            task['issues'].append({**copy.deepcopy(issue),'block_ids':[bid]})
    tasks=sorted(grouped.values(),key=lambda t:(min(REFLOW_PRIORITY[r] for r in t['rule_ids']),order[t['block_id']]))[:limit]
    selected={t['block_id'] for t in tasks};advisories=[]
    for index,issue in enumerate(issues):
        exported={bid for bid in selected if index in grouped[bid]['issue_indices']}
        remaining=[bid for bid in issue.get('block_ids',[]) if bid not in exported]
        if not exported or remaining:
            advisories.append({**copy.deepcopy(issue),'block_ids':remaining or issue.get('block_ids',[]),
                'original_severity':issue.get('severity'),'severity':'soft','effective_status':'advisory',
                'export_reason':'本次只修优先规则的最多5个正文块；其他意见保留，不触发补丁。'})
    return {'block_ids':[t['block_id'] for t in tasks],'tasks':tasks,'advisories':advisories,
        'original_issue_count':len(issues),'max_blocks':limit}

GUIDANCE = '''本轮以用户写作要求为主要检查对象，mandatory_policy_review是必须逐条回答的检查合同。
不进行原始数据溯源、小数精度比对、机制归因取证或额外实验建议；正文直接可见的前后矛盾可指出，不主动扩大事实核查。
逐条提交policy_checks：rule_id、status(pass|advisory|fail|not_applicable)、block_ids、reason。每条用本稿具体内容解释判断，不用“已检查、符合要求”的空话；不适用也说明本次为何不适用。
fail仅表示已明确违反用户原规则；能定位但只是可选改进用advisory并给soft建议，不能为了填满检查表把普通表达升级为hard。检查表不要求各条都找出问题。
逐章提交section_checks：heading、status、block_ids、reason，检查该章是否履行自己的职责、是否侵占别章篇幅。
逐个discourse_targets提交discourse_checks：current_id、previous_id、status(pass|fail)、reason。
重点读段落起手和实际承接：当前在回答什么问题，为何此时引入这个对象，前后是什么关系。小标题、连接词、先报结果后讲定义都不自动代表已有衔接。
已自然承接的段落直接展开，不要求每段加总领句。缺少关系时优先重排、合并、删去重复原理，不统一套用连接句；“为了进一步确认……”只要说明具体目的即可使用。
W01检查“已有结果还不能说明……所以还要……”“只说明……还需确认……”式否定铺垫，改为直接正面说明操作目的，保留原实验任务与必要验证；修改建议自身也遵守W01，不用同类句式修衔接。结论优先直接陈述已有发现与认识，不习惯性加“只能说明、尚不能说明、还需确认”；按已有结果控制宣称范围，不因陈述成果就要求追加限定。修改段落入口时同时看是否新引入W01问题。
关系失败必须在W04或W05标fail并提出定位该段的hard问题。同一个问题可以related_rule_ids列出其他受影响规则，不重复造问题。章节职责失败可以由该章的具体用户规则问题承载，不必另造SECTION问题。明确违反用户规则不能降为可选措辞。
普通用词偏好仍可soft；不要以“分析需增量”为由要求新增欠拟合、过拟合、特征归因或未来收益结论，写作修改只组织现有内容，不扩充实验结论。原先“最多4项”改为最多24项，合并同类问题，但不能以名额已满跳过一条规则。
结果保留issues、summary及已有resolutions，再添加上述三个检查数组。检查记录留后台，不写进实验报告正文。'''

EXTRA_RULES = [
    {'id':'SECTION','problem':'各类章节职责','check':'按每章的实际职能检查允许内容、细节层级和应省略内容，不能只按字数判断。'},
    {'id':'VOICE','problem':'正式学生视角','check':'学生实验实施者的正式、简洁书面语，不聊天、不授课、不站在教师/评分者/Agent开发者视角安排文章。技术解释直接准确，避免“参数往哪走”“损失函数推着参数走”等比喻或拟人化表达；正常数学术语不因含方向、传播等字样被判为比喻。'},
    {'id':'PRESENTATION','problem':'图文与小字','check':'不添加副标题、标题下导语、正文小注、版本或来源自证。只保留必要图表注；正文与图表对应、重要信息有合适载体。'}]

GUIDANCE += "\n" + DEFENSIVE_WRITING_GUIDANCE + "\n" + IMPLEMENTATION_DETAILS_GUIDANCE
GUIDANCE += "所有章节若出现\“本章不讲、不展开、不代表、仅用于、不是为了\”等边界说明，按VOICE或W01定位；编号优先使用1.和（1），避免中点。"


def review_contract(project,document):
    rules=copy.deepcopy(profile_for(project)['rules'])+copy.deepcopy(EXTRA_RULES)
    sections=[{'heading':s['heading'],'roles':section_roles(s['heading']),
        'policy':{r:RULES[r] for r in section_roles(s['heading'])}} for s in document['sections']]
    context=[];prior=None
    # Only current completed writer text is eligible as preceding context.
    if len(document['sections'])==1:
        headings=(project.data.get('template') or {}).get('headings') or [
            s['heading'] for s in project.data.get('report_design',{}).get('sections',[])]
        heading=document['sections'][0]['heading']
        if heading in headings and headings.index(heading)>0:
            previous=headings[headings.index(heading)-1]
            candidates=[b for s in project.data.get('writing_draft',{}).get('sections',[])
                if s['heading']==previous for b in s['blocks'] if b['type']=='text']
            # Keep the object introduction, which may precede the final
            # paragraph. Outline text and unwritten chapters are not prose.
            if candidates:prior=candidates[-1];context=copy.deepcopy(candidates)
    edges=[]
    for section in document['sections']:
        for block in section['blocks']:
            if block['type']!='text':continue
            edges.append({'heading':section['heading'],'current_id':block['id'],
                'previous_id':prior['id'] if prior else '',
                'entry':block.get('text','')[:220]})
            prior=block
    return {'version':VERSION,'document_hash':fingerprint(document),'rules':rules,'sections':sections,
        'discourse_targets':edges,'context_blocks':context,
        'scope':'Writing quality first. No original-data verification. Context absence is explicit; do not invent a prior link.'}


def schema_properties():
    strings={'type':'array','items':{'type':'string'}}
    judgment={'status':{'type':'string','enum':['pass','advisory','fail','not_applicable']},
        'block_ids':strings,'reason':{'type':'string'}}
    return {
        'policy_checks':{'type':'array','items':{'type':'object','properties':{
            'rule_id':{'type':'string'},**judgment},'required':['rule_id',*judgment]}},
        'section_checks':{'type':'array','items':{'type':'object','properties':{
            'heading':{'type':'string'},**judgment},'required':['heading',*judgment]}},
        'discourse_checks':{'type':'array','items':{'type':'object','properties':{
            'current_id':{'type':'string'},'previous_id':{'type':'string'},
            'status':{'type':'string','enum':['pass','fail']},'reason':{'type':'string'}},
            'required':['current_id','previous_id','status','reason']}}}


def current_review(state,document):
    key=fingerprint(document)
    return next((copy.deepcopy(r) for r in reversed(state.get('policy_reviews',[]))
        if r['document_hash']==key and r.get('policy_version')==VERSION),{'document_hash':key,'status':'not_reviewed'})


def validate_coverage(result,contract,document=None):
    ids={b['id'] for s in (document or {}).get('sections',[]) for b in s['blocks']}
    if not ids:
        ids={e['current_id'] for e in contract['discourse_targets']}
    def rows(key,field,expected,label):
        values=result.get(key)
        if not isinstance(values,list) or len(values)!=len(expected) or {r.get(field) for r in values}!=set(expected):
            raise ValueError(label+'必须逐条检查，不能遗漏或重复')
        for row in values:
            if row.get('status') not in ('pass','advisory','fail','not_applicable') or not str(row.get('reason','')).strip():
                raise ValueError(label+'必须给具体判断和理由')
            if key!='discourse_checks' and (not isinstance(row.get('block_ids'),list) or set(row['block_ids'])-ids):
                raise ValueError(label+'只能引用当前文稿块ID')
        return values
    checks=rows('policy_checks','rule_id',[r['id'] for r in contract['rules']],'规则')
    sections=rows('section_checks','heading',[s['heading'] for s in contract['sections']],'章节')
    edges=rows('discourse_checks','current_id',[e['current_id'] for e in contract['discourse_targets']],'段落')
    expected={e['current_id']:e['previous_id'] for e in contract['discourse_targets']}
    issues=result.get('issues',[])
    def hard(rule,block=None):
        return any(i.get('severity')=='hard' and rule in [i.get('rule_id'),*i.get('related_rule_ids',[])]
            and (block is None or block in i.get('block_ids',[])) for i in issues)
    errors=[]
    for row in checks:
        section_failure=(row['rule_id']=='SECTION' and any(s['status']=='fail' and any(
            i.get('severity')=='hard' and set(i.get('block_ids',[])).intersection(s['block_ids']) for i in issues) for s in sections))
        if row['status']=='fail' and not hard(row['rule_id']) and not section_failure:
            errors.append('明确规则失败须有hard；普通建议改为advisory/soft：'+row['rule_id'])
        if row['status']!='fail' and hard(row['rule_id']):
            errors.append('同一规则不能同时通过和存在hard问题：'+row['rule_id'])
    for row in sections:
        if row['status']=='fail' and not any(i.get('severity')=='hard' and set(row['block_ids']).intersection(i.get('block_ids',[])) for i in issues):
            errors.append('章节职责失败必须定位本章具体hard问题：'+row['heading'])
    policy={r['rule_id']:r['status'] for r in checks}
    for edge in edges:
        if edge['previous_id']!=expected[edge['current_id']] or edge['status'] not in ('pass','fail'):
            errors.append('段落检查必须使用实际相邻关系并给pass/fail：'+edge['current_id'])
        if edge['status']=='fail' and not any(policy.get(r)=='fail' and hard(r,edge['current_id']) for r in ('W04','W05')):
            errors.append('段落关系失败必须对应W04/W05 hard，不能仍标通过：'+edge['current_id'])
    if errors:raise ValueError('；'.join(errors))
