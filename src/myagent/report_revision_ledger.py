"""A problem survives revision until a source-grounded recheck resolves it."""
from __future__ import annotations
import copy
import json
import re
from .jobs import atomic_json
from .lab_pipeline import Paused
from .lab_report import validate_document
from .report_context import CONTEXT_VERSION, PATCH, apply_local_patches, fingerprint
from .report_evidence import original_excerpts
from .report_section_policy import RULES, section_roles, preserve_result_tables

REVIEW = '''你是学生实验报告当前章节的写作复查者。document是本轮当前稿，known_issues是必须逐条复查的问题账本。
以用户写作规则为重点，检查逻辑、主次、入口与衔接、过程、图文分工、术语和章节职责。当前正文直接可见的矛盾可指出，不重读原始数据做事实取证。
先逐条判断known_issues是否真正解决、仍存在、或在别处复发，再提出新的具体写作问题。不能因为本轮未再次提出，就默认旧问题消失。
对每个已知问题返回resolutions一项：issue_id、status(resolved|unresolved|recurred|dismissed)、block_ids、quote、reason。resolved也要引当前改文并说明旧问题如何消失；整块删除可block_ids=[]且quote=''。检查整个本章，防止换措辞重复旧因果。
dismissed仅用于检查者原先误判（正确数学性质、错引旧文、越出本章范围或反馈本身承认无需修改），须依据当前原文与来源说明误判原因，保留错误反馈记录；不能把真实未解决错误dismissed。
新问题issues包含rule_id、severity(hard|soft)、block_ids、quote、reason、suggestion。hard必须引用当前实际块内连续原文，明确章节职责/用户规则依据。普通措辞偏好为soft；明确违反用户规则不能降为可选建议。
只检查本章，不要求其他章节的内容或全报告覆盖。数字数量是疑似重复线索，不是硬阈值；关键数字、必要公式和通用数学原理可以出现。目的节“检验、理解、掌握”及概念名称本身不是方法或已取得结果。
修复应直接纠正或删除错误，保留重要过程和有依据的解释，不添加“可能、尚不能证明、未验证”等免责句，不追加实验、核查任务。
表格承担完整比较，正文指出发现并解释关系，不逐个转述表格。图注只交代对象和读图条件，不要版本、自证、重绘小字；已有图像不需重复插入。
用finish_stage提交{issues:[],resolutions:[],summary:简短结论}。无具体硬问题就通过，不为显示检查工作强加问题。'''

EDIT = '''本轮按known_issues中的具体问题修改candidate。每个open问题都要落实到实际补丁，不用修稿说明替代正文修改。
只改editable_block_ids内的当前章节，保留实际结果与必要解释，删掉无依据因果、冗余数字和防御段。不要将被删结论换词后写到别段。
数字数量不直接决定删除；已有图表承载整组值时，正文保留发现、解释与少量决定性数值。代码默认省略。
不靠“可能、未验证、不能说明”等免责句修复错误推断。旧组织计划不提供事实依据。
不改现有结果表单元和必要图片；未变的requirements/evidence字段省略可继承。只用finish_stage提交patches。'''



def continue_revision(w,index,reason,*,additional_repairs=1):
    """Explicit bounded continuation; retain every previous review and patch."""
    if not reason.strip() or not 1<=additional_repairs<=2:raise ValueError('继续修订需具体原因和1—2轮追加额度')
    entry=w.state['revision_ledgers'][str(index)]
    if entry['status']!='needs_attention':raise ValueError('只能继续已经停止的章节')
    entry.setdefault('continuations',[]).append({'reason':reason,'previous_stop':entry.get('stop_reason'),
        'previous_reviews':len(entry['reviews']),'previous_repairs':len(entry['patches']),'additional_repairs':additional_repairs})
    entry.update(status='reviewing',max_repairs=len(entry['patches'])+additional_repairs)
    entry.pop('stop_reason',None);w.project.save()


def issue_tasks(entry):
    return [{**copy.deepcopy(i),**copy.deepcopy(i.get('latest_feedback',{})),'id':i['id'],'status':i['status']}
        for i in entry['issues']]


def export_reflow_tasks(document,issues,*,locked=()):
    """Export a bounded work queue; retain original findings and ledger states."""
    from .report_policy_review import select_reflow_tasks
    return select_reflow_tasks(document,issues,locked=locked)


def content(block):
    if block['type']=='table':return ' '.join(str(v) for row in [block['headers'],*block['rows']] for v in row)
    if block['type']=='list':return ' '.join(block['items'])
    return str(block.get('text') or block.get('caption') or '')


def density_hints(doc):
    return [{'block_id':b['id'],'numeric_tokens':len(re.findall(r'\d+(?:\.\d+)?',b['text']))}
        for s in doc['sections'] for b in s['blocks'] if b['type']=='text' and len(re.findall(r'\d+(?:\.\d+)?',b['text']))>=5]


def validate_review(result,doc,known):
    blocks={b['id']:b for s in doc['sections'] for b in s['blocks']}
    issues=result.get('issues');resolutions=result.get('resolutions')
    if not isinstance(issues,list) or len(issues)>24:raise ValueError('新问题issues最多24项')
    if not isinstance(resolutions,list) or {r.get('issue_id') for r in resolutions}!={i['id'] for i in known} or len(resolutions)!=len(known):
        raise ValueError('必须逐条复查全部known_issues，resolutions不能漏项或重复')
    for i in issues:
        if (i.get('severity') not in ('hard','soft') or not i.get('block_ids') or set(i['block_ids'])-blocks.keys()
            or not all(i.get(k) for k in ('rule_id','reason','suggestion'))):raise ValueError('问题须给当前块ID、严重度、规则和修改依据')
        if i['severity']=='hard' and (not i.get('quote') or not any(i['quote'] in content(blocks[b]) for b in i['block_ids'])):
            raise ValueError('hard引文须逐字存在于当前指定块')
        if i['severity']=='hard' and re.search(r'无需改|无须改|不需要改|保留现文',i['suggestion']):
            raise ValueError('hard问题必须需要具体修改；反馈若确认现文正确、无需修改，应不列新问题或记soft')
    originals={i['id']:i for i in known}
    for r in resolutions:
        if r.get('status') not in ('resolved','unresolved','recurred','dismissed') or not r.get('reason'):
            raise ValueError('复查需明确状态及具体依据；dismissed需说明原先误判')
        ids=r.get('block_ids',[])
        if set(ids)-blocks.keys():raise ValueError('复查只能引用当前实际块ID')
        if ids and (not r.get('quote') or not any(r['quote'] in content(blocks[b]) for b in ids)):
            raise ValueError('复查quote须是当前块的连续原文')
        old=originals[r['issue_id']]
        if r['status']=='resolved' and old.get('status')!='resolved':
            current='\n'.join(content(blocks[b]) for b in old['block_ids'] if b in blocks)
            if current==old['before_text']:raise ValueError('原问题对应文字未改变，不能声明resolved')


def revise_chapter(w,document,*,section_index,section_spec):
    p=w.project;heading=document['sections'][0]['heading'];roles=section_roles(heading)
    key=fingerprint({'document':document,'instructions':p.data['instructions'],'scope':section_spec,'version':CONTEXT_VERSION,'loop':'problem_ledger'})
    entries=w.state.setdefault('revision_ledgers',{});entry=entries.get(str(section_index))
    if not entry or entry['source_hash']!=key:
        entry={'source_hash':key,'heading':heading,'status':'reviewing','draft':copy.deepcopy(document),
            'issues':[],'reviews':[],'patches':[],'pending':False}
        entries[str(section_index)]=entry
    directory=p.root/'outputs/revision-ledgers';directory.mkdir(parents=True,exist_ok=True)
    def save():atomic_json(directory/f'{section_index+1:02}-{key[:12]}.json',entry);p.save()
    def stop(reason):
        entry.update(status='needs_attention',stop_reason=reason);save()
        raise Paused('章节问题账本仍有未解决项：'+heading+'，'+reason)
    if entry['status']=='passed':return copy.deepcopy(entry['draft'])
    if entry['status']=='needs_attention':stop(entry['stop_reason'])
    proxy=copy.copy(p);proxy.data={**p.data,'template':{'headings':[heading]},'requirements':[{**r,'required':False} for r in p.data['requirements']]}
    sources=original_excerpts(p,max_chars=60000,per_source=16000)
    scope={'heading':heading,'roles':roles,'rules':{r:RULES[r] for r in roles},'loop':'problem_ledger'}
    while True:
        draft=entry['draft'];validate_document(draft,proxy)
        if not entry['pending']:
            result=w.role('report_requirement_reviewer',REVIEW,
                {'chapter_scope':scope,'target_heading':heading,'document':draft,'known_issues':issue_tasks(entry),
                 'density_hints':density_hints(draft),'original_source_excerpts':sources,'instructions':p.data['instructions']},
                lambda r:validate_review(r,draft,entry['issues']),task_id=f'ledger-check:{section_index}:{key[:8]}:{len(entry["reviews"])}')
            blocks={b['id']:b for s in draft['sections'] for b in s['blocks']}
            for r in result['resolutions']:
                old=next(i for i in entry['issues'] if i['id']==r['issue_id']);old['status']=r['status'];old.setdefault('checks',[]).append(r)
            for issue in result['issues']:
                if issue['severity']!='hard':continue
                # Reuse the same issue when the reviewer locates it again.
                old=next((i for i in entry['issues'] if i['rule_id']==issue['rule_id'] and set(i['block_ids'])==set(issue['block_ids']) and i.get('quote')==issue.get('quote')),None)
                if old:old.update(status='unresolved',latest_feedback=issue)
                else:entry['issues'].append({'id':f'I{len(entry["issues"])+1}',**issue,'status':'open',
                    'before_text':'\n'.join(content(blocks[b]) for b in issue['block_ids'])})
            entry['reviews'].append({'result':result,'document_hash':fingerprint(draft)})
            entry['pending']=True;save()
            open_issues=[i for i in entry['issues'] if i['status'] not in ('resolved','dismissed')]
            w.logger.log('revision_ledger_review',heading=heading,attempt=len(entry['reviews'])-1,open_ids=[i['id'] for i in open_issues])
            if not open_issues:entry.update(status='passed',pending=False);save();return copy.deepcopy(draft)
            if len(entry['patches'])>=entry.get('max_repairs',2):stop('repair_limit')
        blocks={b['id']:b for s in draft['sections'] for b in s['blocks']};ids=set(blocks)
        def validate_patch(r):
            if not isinstance(r.get('patches'),list) or len(json.dumps(r['patches'],ensure_ascii=False))>22000:raise ValueError('只提交有界patches')
            updated=apply_local_patches(draft,r['patches'],ids);preserve_result_tables(draft,updated);validate_document(updated,proxy)
        result=w.role('report_patcher',PATCH+'\n'+EDIT,
            {'chapter_scope':scope,'target_heading':heading,'candidate':draft,'editable_block_ids':sorted(ids),
             'known_issues':[i for i in issue_tasks(entry) if i['status'] not in ('resolved','dismissed')],'original_source_excerpts':sources,
             'instructions':p.data['instructions'],'new_block_id_prefix':f'ledger-{section_index}-{len(entry["patches"])}-'},
            validate_patch,task_id=f'ledger-edit:{section_index}:{key[:8]}:{len(entry["patches"])}')
        updated=apply_local_patches(draft,result['patches'],ids)
        after={b['id']:b for s in updated['sections'] for b in s['blocks']}
        changes=[{'block_id':bid,'before':content(blocks[bid]) if bid in blocks else '',
            'after':content(after[bid]) if bid in after else ''} for bid in sorted(ids|set(after)) if blocks.get(bid)!=after.get(bid)]
        entry['patches'].append({'patches':result['patches'],'changes':changes,'issue_ids':[i['id'] for i in entry['issues'] if i['status'] not in ('resolved','dismissed')]})
        entry.update(draft=updated,pending=False);save()
        if not changes:stop('no_change')
