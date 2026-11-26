"""Compact existing-reviewer requests; unchanged quality loops and persistent CNY accounting."""
from __future__ import annotations
import copy
import json
import re
from .jobs import atomic_json
from .report_section_policy import IMPLEMENTATION_DETAILS_GUIDANCE, DEFENSIVE_WRITING_GUIDANCE
from .lab_project import now
from .report_context import fingerprint
from .report_policy_review import review_contract, VERSION as POLICY_VERSION

VERSION = 7
OUTPUT_TOKENS = 4096
CHAPTER_RULES = {'W01','W02','W03','W04','W05','W06','W07','W08','SECTION','VOICE','PRESENTATION'}

PROMPT = '''检查当前报告的写作质量，只用finish_stage提交结果。document是当前正文，preceding_context是实际已写前文，rules是本轮规则；不读取原始日志/源码，不做数值溯源或额外实验建议。
每个正文段落都读，不仅看首句。新对象/标签/操作出现时，读者应理解具体所指；段内推理正确不代替对象介绍。承接真实前文，早先已介绍的对象可回指，题目标题已说明问题时直接作答，不强求独立题目互相承接。
操作目的正面说明，避免“只说明……还需确认……”或“已确认……但……因此追加验证”式铺垫；“为了探究/为了进一步确认”有具体目的即可。结论直接陈述已有认识。修衔接的建议也不能引入防御表达、比喻或删除任务说明。
只报告确实存在且值得修改的问题，给rule_id、severity(hard|soft)、block_ids、quote(当前块连续原文)、reason、suggestion、needs_material=false。rules保留用户规则的level；明确违反硬规则或用户明确禁止的句式用hard，不能因只是改句式就降成soft，否则流程不会修。可选润色为soft。不要因为已知原理没有做额外对照实验就判错。block_ids逐字复制document中的实际ID，不能按命名规律推测ID。
previous_issues是同一范围上一轮的问题线索，逐项核对本稿是否仍存在；按当前规则重新判定，不照抄历史裁决；未解决的继续列出，不换一批意见忘掉原问题。检查所有rules及paragraph_ids，checked_rule_ids/checked_block_ids返回实际检查的ID列表即可，不为每个通过项写长理由，不重交章节/规则/段落三套相互重复的回执。结果为{issues:[],summary:"简短结果",checked_rule_ids:[],checked_block_ids:[]}。'''
PROMPT += '''\n已解决的问题不再列为待修问题，“保持现状/无需修改”不能标hard。并列实验可以独立介绍，不要求虚构前后依赖；不要求每段加总起句。实验内容章简述任务范围与记录什么是正常叙述，不因出现“日志”等操作对象就判越界；只在连续实现细节实质挤占任务概览时定位问题。不要为了衔接把独立实验改成互相依赖，也不要把已有背景解释反复判为零帧起手。'''
PROMPT += '''\nW01检查句子在段里的作用。为解释改进建议而简述真实故障、尚未运行的对照或样本条件是有效信息；只有用无关的自证、免责或否定前文来铺垫操作时才指出。明确禁止的防御性承接即使改写前后事实相同，也标为hard。例如“标量样本只检验了单个参数上的梯度，训练循环本身还没有写通。”应用正面目的句或直接介绍下一项实验。普通措辞偏好可标为soft。'''


PROMPT += '''\n步骤节检查“断言”等代码术语是否反复取代实际操作叙述。建议用核对对象、比较方法与必要判定条件说明实际过程。结果分析章逐项检查数据是否导向明确发现；只有陈列图表或复述数值时，引用当前原文，指出相应任务以及能支撑判断的现有比较。总结只归纳分析章已有的结论。'''
PROMPT += '''\n若提供 calculations，它们是已用原件计算的结果，按其范围与数值核对结论，不重算。指导书要求的指标若缺少必要读数，保留一句事实状态，不用 W01 删去，也不要要求填入替代基准或估算值。数值变化与发生原因是两件事，计算回执只支持该现象和它对指标的影响。'''

PROMPT += "\n" + DEFENSIVE_WRITING_GUIDANCE + "\n" + IMPLEMENTATION_DETAILS_GUIDANCE

def enabled(project):
    return project.data.get('report_review_mode') == 'lean'


def schema():
    strings={'type':'array','items':{'type':'string'}}
    issue={'type':'object','properties':{
        'rule_id':{'type':'string'},'severity':{'type':'string','enum':['hard','soft']},
        'block_ids':strings,'quote':{'type':'string'},'reason':{'type':'string'},
        'suggestion':{'type':'string'},'needs_material':{'type':'boolean'}},
        'required':['rule_id','severity','block_ids','quote','reason','suggestion']}
    resolution={'type':'object','properties':{'issue_id':{'type':'string'},
        'status':{'type':'string','enum':['resolved','unresolved','recurred','dismissed']},
        'block_ids':strings,'quote':{'type':'string'},'reason':{'type':'string'}},
        'required':['issue_id','status','block_ids','quote','reason']}
    return {'type':'object','properties':{'issues':{'type':'array','items':issue},
        'resolutions':{'type':'array','items':resolution},
        'summary':{'type':'string'},'checked_rule_ids':strings,'checked_block_ids':strings},
        'required':['issues','summary','checked_rule_ids','checked_block_ids']}


def manuscript_copy(document):
    # Do not shorten prose or lose titles/tables used to interpret it. Only
    # provenance metadata, image paths and repeated evidence IDs are omitted.
    fields={'id','type','text','items','headers','rows','caption'}
    return {'title':document.get('title',''),'sections':[
        {'heading':s['heading'],'blocks':[{k:copy.deepcopy(v) for k,v in b.items() if k in fields}
            for b in s['blocks']]} for s in document['sections']]}


def packet(workflow, payload):
    p=workflow.project;doc=payload['document'];is_prose=all('blocks' in s for s in doc.get('sections',[]))
    if is_prose:
        contract=review_contract(p,doc)
        rules=contract['rules']
        if payload.get('chapter_scope'):rules=[r for r in rules if r['id'] in CHAPTER_RULES]
        scope=('chapter:'+doc['sections'][0]['heading']) if payload.get('chapter_scope') else 'whole_report'
        document=manuscript_copy(doc)
        context=contract['context_blocks'];ids=[e['current_id'] for e in contract['discourse_targets']]
        duties=contract['sections']
    else:
        from .report_writing import profile_for
        from .report_policy_review import EXTRA_RULES
        rules=[r for r in [*profile_for(p)['rules'],*EXTRA_RULES] if r['id'] in ('W02','W03','SECTION')]
        scope='outline';document=copy.deepcopy(doc);context=[];ids=[];duties=[]
    previous=next((r for r in reversed(workflow.state.get('lean_reviews',[])) if r['scope']==scope and not r.get('incomplete')),None)
    prior=[]
    if previous:
        saved=json.loads(p.file(previous['path']).read_text(encoding='utf-8'))
        # Historical severity and proposed rewrites are not current rulings.
        # Keep problem location/evidence without biasing reclassification or
        # resending verbose rewrite suggestions on every recheck.
        prior=[{k:copy.deepcopy(i[k]) for k in ('rule_id','block_ids','quote','reason') if k in i}
            for i in saved['result'].get('issues',[])]
    data={'_lean_review':True,'scope':scope,'document':document,'preceding_context':context,
        'user_request':p.data.get('instructions',''),
        'section_duties':duties,'paragraph_ids':ids,
        'rules':[{'id':r['id'],'level':r.get('level','contextual'),'text':r.get('text') or r.get('check','')} for r in rules],
        'previous_issues':prior,
        'requirements':[{k:r[k] for k in ('id','text','acceptance') if k in r}
                        for r in p.data.get('requirements',[]) if r.get('required')],
        'user_preferences':p.data.get('report_preferences',{}),
        'notice':'Chapter review covers local rules. Revision continues while progress is made within the task budget; unresolved feedback remains recorded for delivery.'}
    if payload.get('chapter_scope') and set(payload['chapter_scope'].get('roles', ())) & {'results', 'analysis'}:
        calculations={c['id']:{k:v for k,v in c.items() if k not in ('pairs','sheet','id')}
                      for group in payload.get('evidence',{}).get('results',{}).values()
                      for c in group.get('calculations',[])}
        if calculations:data['calculations']=list(calculations.values())
    if 'known_issues' in payload:
        data['known_issues']=copy.deepcopy(payload['known_issues'])
        data['notice']+=' For each known issue return resolutions: issue_id, status(resolved|unresolved|recurred|dismissed), block_ids, quote, reason. Resolved requires current text evidence; deleted blocks may use [] and empty quote. Do not omit unresolved issues.'
    if not is_prose:data['notice']+=' This is an outline, not completed report text; check planned coverage and responsibilities only.'
    # Actual prose is never truncated to meet a token target.
    return data


def validate_result(result, data):
    expected={'checked_rule_ids':[r['id'] for r in data['rules']],'checked_block_ids':data['paragraph_ids']}
    for field,ids in expected.items():
        actual=result.get(field)
        if not isinstance(actual,list) or len(actual)!=len(set(actual)) or set(actual)!=set(ids):
            raise ValueError(f'{field}: missing={sorted(set(ids)-set(actual or []))}; unexpected={sorted(set(actual or [])-set(ids))}; use each expected ID once')
    blocks={b['id']:b for s in data['document'].get('sections',[]) for b in s.get('blocks',[])}
    rules=set(expected['checked_rule_ids'])
    if not isinstance(result.get('issues'),list):raise ValueError('issues must be an array')
    for index,issue in enumerate(result['issues']):
        if issue.get('rule_id') not in rules:raise ValueError('rule_id expected one of '+','.join(sorted(rules)))
        bids=issue.get('block_ids',[])
        if blocks and (not bids or set(bids)-set(blocks)):
            quote=issue.get('quote','')
            matches=[bid for bid,b in blocks.items() if quote and quote in json.dumps(b,ensure_ascii=False)]
            raise ValueError(f'issues[{index}].block_ids: actual={bids}; unknown={sorted(set(bids)-set(blocks))}; quote_matches={matches}; expected actual document block IDs, never infer names')
        if blocks and issue.get('severity')=='hard':
            quote=issue.get('quote','')
            def text(b):return b.get('text') or b.get('caption') or json.dumps(b.get('rows') or b.get('items') or [],ensure_ascii=False)
            if not quote or not any(quote in text(blocks[bid]) for bid in bids):raise ValueError('hard quote must be continuous current block text')


def calibrate_result_status_issues(result, data):
    """A verified, concise required-result status is valid under W01."""
    missing = [c for c in data.get('calculations', []) if c.get('status') == 'unavailable'
               and c.get('metric') == 'normalized_max_deviation'
               and c.get('reason') == 'required_reference_not_in_observations']
    if not missing:
        return result
    blocks = {b['id']: b for s in data['document']['sections'] for b in s['blocks']}
    result = copy.deepcopy(result)
    for issue in result['issues']:
        if issue.get('rule_id') != 'W01' or issue.get('severity') != 'hard' or len(issue['block_ids']) != 1:
            continue
        text = blocks[issue['block_ids'][0]].get('text', '').strip()
        sentence = issue['quote'].strip()
        if (len(sentence) > 100 or sentence not in re.split(r'(?<=[。！？])', text)
                or not re.search(r'非线性误差|归一化最大偏差|相对最大偏差', sentence)
                or not re.search(r'未记录|未测得|缺少|缺失|没有.{0,8}读数', sentence)
                or not re.search(r'未计算|未给出|无法计算|无法给出|缺少.{0,8}基准', sentence)
                or re.search(r'所以还要|因此追加|为了|改用|替代', sentence)):
            continue
        if any(re.search(rf'(?<![\d.]){re.escape(format(c["reference_x"], "g"))}(?![\d.])', sentence)
               for c in missing):
            issue['severity'] = 'soft'
            issue['calibration'] = '该句与计算回执中的必交指标缺项一致，保留实际状态，不触发改稿。'
    return result


def run(workflow, payload, original_validator, task_id=None):
    from .lab_pipeline import LabPipeline, Paused
    from .report_protocol import StageUnresolved
    data=packet(workflow,payload);p=workflow.project
    # A saved judgment about identical effective prose/rules is reusable even
    # when that judgment itself has become the previous-issues entry.
    effective={k:v for k,v in data.items() if k!='previous_issues'}
    key=fingerprint({'packet':effective,'version':VERSION,'policy':POLICY_VERSION})
    folder=p.root/'outputs/lean-reviews';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{key}.json'
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if saved.get('status')=='completed':
            original_validator(saved['result'])
            return copy.deepcopy(saved['result'])
    def validate(result):
        validate_result(result,data);original_validator(result)
    atomic_json(path,{'status':'started','packet':data,'source_document_hash':fingerprint(payload['document'])})
    factory=workflow.model_factory
    limit = min(1.0, float(p.data.get('report_review_budget_cny', 1.0))) if workflow.max_cost else None
    accounting = workflow.state.setdefault('review_accounting', {'currency':'CNY','spent_cny':0.,'calls':0})
    accounting['limit_cny'] = limit
    def guarded_factory(config):
        model=factory(config)
        model.output_token_limit=OUTPUT_TOKENS
        if limit is None:
            return model
        original_chat=model.chat
        def chat(messages, tools=None, *args, **kwargs):
            upper_input=len(json.dumps({'messages':messages,'tools':tools},ensure_ascii=False).encode('utf-8'))+1024
            pricing=config.billing_details({'prompt_tokens':upper_input,'completion_tokens':OUTPUT_TOKENS})
            if not pricing or pricing.get('currency')!='CNY':raise Paused('审查预算无法按当前模型确定CNY价格，保留进度，不将未知费用当作0')
            # Use peak configured rates when reserving, irrespective of cache
            # discounts/time-of-day. Charged cost uses actual provider tokens.
            rates=pricing['rates_per_million']
            reserve=(upper_input*max(2.0,rates['input'])+OUTPUT_TOKENS*max(8.0,rates['output']))/1e6
            if accounting['spent_cny']+reserve>limit:
                raise Paused('审查1元预算余量不足以覆盖下一次调用；未解决问题与稿件已保存，不视为审查通过')
            response=original_chat(messages,tools,*args,**kwargs)
            bill=response.get('billing') or config.billing_details(response.get('usage',{}))
            if not bill or bill.get('currency')!='CNY':raise Paused('审查实际用量无法计价，保留未完成状态')
            accounting['spent_cny']+=bill['estimated_amount'];accounting['calls']+=1
            p.save()
            return response
        model.chat=chat
        return model
    workflow.model_factory=guarded_factory
    try:
        result=LabPipeline.role(workflow,'report_requirement_reviewer',PROMPT,data,validate,task_id)
    except (StageUnresolved,Paused) as exc:
        atomic_json(path,{'status':'incomplete','packet':data,'error':str(exc)})
        workflow.state.setdefault('lean_reviews',[]).append({'scope':data['scope'],'path':str(path.relative_to(p.root)),
            'document_hash':fingerprint(payload['document']),'incomplete':True})
        p.save();raise
    finally:workflow.model_factory=factory
    result=calibrate_result_status_issues(result,data)
    record={'status':'completed','at':now(),'packet':data,'result':result,'source_document_hash':fingerprint(payload['document'])}
    atomic_json(path,record)
    workflow.state.setdefault('lean_reviews',[]).append({'scope':data['scope'],'path':str(path.relative_to(p.root)),
        'document_hash':fingerprint(payload['document']),'incomplete':False})
    if data['scope']!='outline':
        policy={'document_hash':fingerprint(payload['document']),'policy_version':POLICY_VERSION,
            'status':'needs_revision' if any(i.get('severity')=='hard' for i in result['issues']) else 'reviewed_no_hard_issues',
            'path':str(path.relative_to(p.root)),'protocol':'lean','checked_block_ids':result['checked_block_ids'],
            'checked_rule_ids':result['checked_rule_ids']}
        workflow.state.setdefault('policy_reviews',[]).append(policy)
    p.save();return result
