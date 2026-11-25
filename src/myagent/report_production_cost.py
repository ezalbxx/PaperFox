"""Bounded production batches and lossless request-only context references."""
from __future__ import annotations
import copy
import json

VERSION = 1
REFERENCE_GUIDANCE = '''输入中context_ref是本次请求内部的JSON Pointer引用，指向同一请求中仍完整提供的相同内容，并非缺失资料或外部文件。直接使用该位置的内容，无需工具重读。原文和事实没有被摘要。'''

# Only context containers are shared; editable manuscripts, current prose and
# output schemas keep their original shapes. No lossy text/token truncation.
SHARED_FIELDS = {'experiment_overview','figure_outputs','figure_outputs_full',
    'story_cards','requirements','requirement_contract','human_decisions',
    'facts','claims','results','report_structure','outline','source_context',
    'verified_requirements','original_source_excerpts','reading_map',
    'documents','material_groups','previous_outputs','collaboration','evidence',
    'text','excerpt','observation','interpretation','section_policy','writing_rules','rules'}
PROSE_FIELDS = {'candidate','document','completed_core','continuity','neighbor_blocks',
    'known_issues','previous_issues','requirement_feedback','reflow_context'}


def guard_project_cost(model, project):
    """Reserve a worst-rate estimate before each paid turn, including compaction."""
    from .lab_pipeline import Paused

    chat = model.chat
    limit = float(project.data['report_total_budget_cny'])

    def budgeted_chat(messages, tools=None, *args, **kwargs):
        if project.data.get('usage_incomplete'):
            raise Paused('上次模型用量未确认，无法继续按本报告的人民币预算计费。')
        prompt = len(json.dumps({'messages': messages, 'tools': tools}, ensure_ascii=False).encode('utf8')) + 1024
        pricing = model.config.billing_details({})
        if not pricing or pricing.get('currency') != 'CNY':
            raise Paused('当前模型缺少可用的人民币计价，报告进度已保存。')
        rates = pricing['rates_per_million']
        reserve = (prompt * max(2.0, rates['input']) +
                   model.output_token_limit * max(8.0, rates['output'])) / 1_000_000
        spent = project.data['totals'].get('cost_cny', 0.0)
        if spent + reserve > limit:
            raise Paused(f'本报告已计费约{spent:.2f}元，剩余额度无法覆盖下一次模型调用；现有进度已保存。')
        response = chat(messages, tools, *args, **kwargs)
        if response.get('usage_known') is False:
            project.data['usage_incomplete'] = True
            project.save()
        return response

    model.chat = budgeted_chat


def enabled(project):
    return project.data.get('report_production_mode')=='lean'


def local_story_context(payload):
    """Keep selected detailed cards plus a complete experiment index/overview."""
    packet=copy.deepcopy(payload)
    spec=packet.get('part_plan')
    structure=packet.get('report_structure')
    if not isinstance(spec,dict) or not isinstance(structure,dict):return packet
    wanted=spec.get('card_ids')
    cards=structure.get('story_cards',{}).get('experiments',[])
    # Missing/ambiguous planning must keep the complete fallback context.
    if not wanted or not set(wanted)<={c['id'] for c in cards}:return packet
    selected=[c for c in cards if c['id'] in wanted]
    if len(selected)==len(cards):return packet
    structure['story_cards']['experiments']=selected
    structure['experiment_index']=[{k:copy.deepcopy(c[k]) for k in ('id','title','question','task_ids','source_ids') if k in c}
        for c in cards]
    structure['story_card_scope_notice']='Detailed cards follow part_plan.card_ids; experiment_index covers all experiments. Overall context, plans and current prose remain available. Other originals are readable through report_materials.'
    return packet


def compact_request(payload, *, minimum_chars=600):
    """Replace exact duplicate containers with references, retaining one copy."""
    packet=copy.deepcopy(payload);seen={};refs=[]
    def walk(value,path='',protected=False):
        if isinstance(value,dict):
            for key,item in list(value.items()):
                pointer=path+'/'+str(key).replace('~','~0').replace('/','~1')
                keep=protected or key in PROSE_FIELDS
                if not keep and key in SHARED_FIELDS and isinstance(item,(dict,list,str)):
                    serial=json.dumps(item,ensure_ascii=False,sort_keys=True)
                    if len(serial)>=minimum_chars:
                        if serial in seen:
                            value[key]={'context_ref':'#'+seen[serial]}
                            refs.append({'replaced':pointer,'retained':seen[serial]});continue
                        seen[serial]=pointer
                walk(item,pointer,keep)
        elif isinstance(value,list):
            for index,item in enumerate(value):walk(item,path+'/'+str(index),protected)
    walk(packet)
    before=len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
    after=len(json.dumps(packet,ensure_ascii=False).encode('utf-8'))
    return packet,{'version':VERSION,'before_bytes':before,'after_bytes':after,'references':refs}


def repair_units(document,issues, *, max_chars=6000,max_blocks=12):
    """Combine selected same-chapter units without increasing per-call bounds."""
    from .report_context import document_units,assign_issues,fingerprint
    units=document_units(document,max_chars=max_chars,max_blocks=max_blocks)
    selected=[dict(u,issues=a,subheadings=[u['subheading']],last_unit_index=i)
        for i,(u,a) in enumerate(zip(units,assign_issues(units,issues))) if a]
    merged=[]
    for unit in selected:
        prior=merged[-1] if merged else None
        blocks=(prior['blocks'] if prior else [])+unit['blocks']
        size=sum(len(json.dumps(b,ensure_ascii=False)) for b in blocks)
        if (prior and prior['section']==unit['section'] and prior['last_unit_index']+1==unit['last_unit_index']
                and size<=max_chars and len(blocks)<=max_blocks):
            prior['blocks']=blocks
            prior['last_unit_index']=unit['last_unit_index']
            prior['subheadings']=list(dict.fromkeys(prior['subheadings']+unit['subheadings']))
            prior['subheading']=' / '.join(h for h in prior['subheadings'] if h)
            combined=prior['issues']+unit['issues'];seen=set();prior['issues']=[]
            for issue in combined:
                key=fingerprint(issue)
                if key not in seen:prior['issues'].append(issue);seen.add(key)
        else:merged.append(copy.deepcopy(unit))
    return merged


def small_material_topic(workflow,groups, *, max_chars=100000,max_sources=80):
    """Join imported experiment materials into one evidence packet when the packet remains bounded. Category splitting is the fallback."""
    categories=tuple(dict.fromkeys(g['category'] for g in groups))
    if len(categories)<2:return None
    sources=[s for s in workflow.project.data['report_sources'] if s['category'] in categories]
    if len(sources)>max_sources:return None
    packet=workflow.topic_evidence('material_evidence',sources)
    if (packet.get('omitted_ids') or {s['id'] for s in packet['sources']}!={s['id'] for s in sources}
            or len(json.dumps(packet,ensure_ascii=False))>max_chars):return None
    return ('material_evidence',categories,
        '关联理解同一实验的代码、结果与图表：各任务研究什么、实际怎样操作、产生什么结果。'
        '利用已提供原文和整体概览，把不同存储类别关联到对应实验；不要逐文件复述。'),packet
