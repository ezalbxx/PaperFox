"""Progress-driven chapter revision with deliverable checkpoints."""
from __future__ import annotations
import copy
import json
import re

from .jobs import atomic_json
from .lab_pipeline import OutputTruncated, Paused
from .report_protocol import StageUnresolved
from .lab_report import validate_document
from .report_context import CONTEXT_VERSION, PATCH, apply_local_patches, fingerprint
from .report_evidence import original_excerpts
from .report_section_policy import IMPLEMENTATION_DETAILS_GUIDANCE, DEFENSIVE_TRANSITION, DEFENSIVE_WRITING_GUIDANCE, RULES, section_roles, structural_issues, preserve_result_tables

CHAPTER_REVIEW = '''你是当前章节的写作检查者。只检查document这一个已写章节，不检查其他章尚未完成的内容，不要求补齐整份报告。
目的节允许“检验、验证、考察、理解、掌握、完成某任务”等目标式表达和必要的研究对象名称（如自动微分、非线性隐藏层、混淆矩阵）；这些措辞本身不是操作流水账或已取得的结果。已知数学原理不需要本次另做模型对照来成立。只在出现具体实现取值、详细操作序列或实际成绩时判越界。
teacher_requirement_excerpts是指导书原文；明确目标门槛按原文保留。当前document才是待检查稿，不把原始材料或上一轮反馈中的旧措辞说成本轮正文。每项hard必须给quote，为当前列出的某个block内连续原文，不能改写或拼接；没有准确引文的疑问只记soft。
chapter_scope给出本章职责。优先检查：内容是否属于本章；原值/方法是否与提供的原材料一致；是否把假说或没有记录的动机写成事实；正文是否重复本章图表中的整组数据；是否有防御性表达、无关代码或术语堆砌。
原理可支持解释，未做的因果/模型能力对照不得成为已证结论。纠正错误或删除多余内容，不能通过添加“可能、未验证、不能说明”等免责段修复。
结果分析优先检查每项实验是否从已有比较或观察得出了正文中明确的结论。只陈列图表、复述数值或把结论留到总结时，指出具体实验并说明哪项已有证据可用于推理。检查段首是否通过否定上一任务来引入新任务，以及“断言”等实现术语是否盖过操作目的。修订时保留关键实验过程或发现。既有必要公式和有依据的原理解释不自动算代码细节或防御性文字。
判定W01时看句子的用途。能解释改进建议的真实故障、尚未完成的对照或样本条件应保留；只有措辞偏好时记soft。
caption只说明读图条件；普通数据制图的来源留元数据，不要求图注加“重绘、已核验、非截图”等小字。没有看过图片像素，不猜图像外观；不得要求额外实验、审计、统计或学生补充现有原件。
不要按字符数机械判错，不把普通措辞偏好升为hard。硬问题必须给具体块ID、原文和违反本章职责/事实的理由；同类问题合并。
最多4项：明确事实错误、用户禁止内容、本章缺失的关键任务为hard；可选措辞为soft。只用finish_stage提交{issues:[{rule_id,severity,block_ids,quote,reason,suggestion,needs_material:false}],summary}。无硬问题可以通过，不为显示检查工作强加问题。'''

CHAPTER_EDIT = '''本轮只修chapter_scope指定的已完成章节。requirement_feedback是本轮具体问题，其余内容保留。
只在editable_block_ids内提交最小补丁，保留已有数值、图表、关键过程和引用；不修改其他章节，不新增审计、自证或免责文字。
正文只概括关键发现，完整比较留已有表格；不把删除的数字再搬到代码块。分析应解释现象之间的关系。
purpose只交代问题与目标，不展开操作参数；其他章按chapter_scope职责处理。没有记录的个人动机不要补写。
块替换保留ID，未变动的requirements/evidence可以省略以继承。字段只接受项目提供的合法要求/任务ID，来源S编号不是evidence任务ID。'''

CHAPTER_REVIEW += "\n" + DEFENSIVE_WRITING_GUIDANCE + "\n" + IMPLEMENTATION_DETAILS_GUIDANCE


def calibrate_issues(issues,roles):
    """A vague interpretation of a valid objective cannot become a hard gate.

    The user's objective policy forbids concrete implementation details and
    achieved results, while allowing concepts and sourced target thresholds.
    Ambiguous wording remains visible as soft feedback, never silently erased.
    """
    result=copy.deepcopy(issues)
    for issue in result:
        if (issue.get('severity')=='hard' and re.fullmatch(r'(?:保持现状|无需修改|保留原文)[。.!！\s]*',issue.get('suggestion',''))
                and re.search(r'(?:问题已解决|已解决|已修复)',issue.get('reason',''))):
            issue['severity']='soft'
            issue['calibration']='审查理由明确确认已解决且建议不修改，不能同时作为待修硬问题；原意见保留。'
    if roles!=['objectives']:return result
    detail=re.compile(r'(?:学习率|批大小|随机种子|迭代次数|隐藏单元|轮数|epoch|batch|lr|seed)\s*(?:为|是|取|设为|=|：|:)\s*\d|'
        r'\b(?:backward|zero_grad|optimizer\.step|torch\.[A-Za-z_]+)\s*\(|\b\w+\.py\b|'
        r'(?:首先|第一步).{0,120}(?:然后|第二步)|(?:已|实际|最终)(?:达到|取得|得到|实现|完成)|课程评价|评分标准|考核重点')
    for issue in result:
        if issue['severity']!='hard' or issue.get('rule_id')=='VOICE':continue
        quote=issue.get('quote','')
        achieved=bool(re.search(r'(?:准确率|损失|梯度).{0,12}(?:为|达到|降至|升至)\s*[-−]?\d',quote)) and not re.search(r'目标|期望|力争|要求',quote)
        if not detail.search(quote) and not achieved:
            issue['severity']='soft';issue['calibration']='目的节概念、目标动词或目标门槛的语气疑问，无具体实现取值/操作顺序/已取得结果的引文，不作硬性阻断；原意见保留供查看。'
    return result


def local_policy_issues(document, *, lean=False):
    """Locate explicit user constraints; these remain visible across reviews."""
    issues=structural_issues(document)
    for section in document['sections']:
        roles=section_roles(section['heading'])
        has_table=any(b['type']=='table' for b in section['blocks'])
        for block in section['blocks']:
            if block['type']=='text':
                text=block.get('text','')
                if DEFENSIVE_TRANSITION.search(text):
                    issues.append({'rule_id':'W01','severity':'hard','block_ids':[block['id']],
                        'reason':'当前正文仍含用户禁止的防御表达：'+text,
                        'suggestion':'直接交代当前实验的对象和目的，或陈述实际操作、发现与解释；可用自然的目的句。','needs_material':False})
                if lean:continue
                values=re.findall(r'(?<![A-Za-z])[-−]?\d+(?:\.\d+)?(?:%|e[-+]?\d+)?',text)
                if has_table and len(values)>=5 and set(roles).intersection(('procedure','results','analysis')):
                    issues.append({'rule_id':'W06','severity':'hard','block_ids':[block['id']],
                        'reason':'本章已有表格，当前段仍包含'+str(len(values))+'个数字片段，应处理正文细节密度：'+text,
                        'suggestion':'以已有图表承载完整比较，正文保留操作目的、关键发现及解释；删除重复数字串，不把删掉内容转存代码，不删关键过程。','needs_material':False})
            if not lean and block['type']=='table' and roles==['procedure']:
                cells=' '.join(str(v) for row in block.get('rows',[]) for v in row)
                if '关键数值' in block.get('headers',[]) and re.search(r'(?:损失|准确率).{0,30}→',cells):
                    issues.append({'rule_id':'chapter:procedure_results','severity':'hard','block_ids':[block['id']],
                        'reason':'步骤章配置表的“关键数值”列提前展示了损失/准确率变化结果。',
                        'suggestion':'本章表格只保留必要的实验条件与设置，移除结果列；原始结果仍保存在工程，由结果章按原值展示。','needs_material':False})
    return issues


def review_chapter(workflow, document, *, section_index, section_spec):
    w=workflow;p=w.project
    if len(document.get('sections',[]))!=1:raise ValueError('章节检查只接受一个完整章节')
    heading=document['sections'][0]['heading']
    roles=section_roles(heading)
    task_ids=list(dict.fromkeys(t for part in section_spec.get('parts',[]) for t in part.get('task_ids',[])))
    key=fingerprint({'document':document,'heading':heading,'scope':section_spec,'context':CONTEXT_VERSION,
        'policy':{r:RULES[r] for r in roles},'instructions':p.data['instructions']})
    entries=w.state.setdefault('chapter_reviews',{})
    entry=entries.get(str(section_index))
    if not entry or entry['source_hash']!=key:
        entry={'heading':heading,'source_hash':key,'status':'reviewing','draft':copy.deepcopy(document),
            'history':[],'repairs':0,'pending_issues':None}
        entries[str(section_index)]=entry
    folder=p.root/'outputs/chapter-reviews';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{section_index+1:02}-{key[:12]}.json'
    def checkpoint():
        w.state['progress']={'label':'检查章节' if entry['status']=='reviewing' else '章节检查已保存',
            'topic':heading,'completed':len(entry['history']),'total':None,
            'repairs':entry['repairs'],'chapter_status':entry['status']}
        atomic_json(path,entry);p.save()
    def defer(reason):
        entry.update(status='unresolved',stop_reason=reason);checkpoint()
        w.logger.log('chapter_review_deferred',heading=heading,reason=reason,
                     pending_issues=entry.get('pending_issues'),checkpoint=str(path.relative_to(p.root)))
        return copy.deepcopy(entry['draft'])
    if entry['status']=='passed':return copy.deepcopy(entry['draft'])
    if entry['status']=='unresolved':return copy.deepcopy(entry['draft'])
    if entry['status']=='needs_attention':
        # Old repair-limit checkpoints resume at their saved pending feedback.
        entry['legacy_stop_reason']=entry.pop('stop_reason',None)
        entry['status']='reviewing';checkpoint()
    scope={'heading':heading,'roles':roles,'rules':{r:copy.deepcopy(RULES[r]) for r in roles},
        'task_ids':task_ids,'scope_notice':'Only this completed chapter; global coverage/repetition is checked after assembly.'}
    sources=original_excerpts(p)
    known={s['id']:s for s in p.data.get('report_sources',[])}
    if task_ids:
        sources=[s for s in sources if not known.get(s['source_id'],{}).get('task_ids') or
                 set(known[s['source_id']]['task_ids']).intersection(task_ids)]
    evidence=w.result_package(task_ids or None,compact=True)
    # The current manuscript is what is checked; old model interpretations
    # must not be reintroduced as answers to reproduce during local repair.
    for result in evidence.get('results',{}).values():result.pop('analysis',None)
    teacher=[]
    materials=p.root/'materials.json'
    if materials.exists():
        for doc in json.loads(materials.read_text(encoding='utf-8')).get('documents',[]):
            if doc.get('role') not in ('guidance','template'):continue
            for page in doc.get('pages',[]):
                text=page.get('text','')
                if page.get('page')==1 or any(t in text for t in ('70%','目标','实验目的','准确率')):
                    teacher.append({'material_id':doc['material_id'],'page':page['page'],'text':text[:2400]})
        teacher=teacher[:8]
    partial=copy.copy(p)
    partial.data={**p.data,'template':{'headings':[heading]},
        'requirements':[{**r,'required':False} for r in p.data['requirements']]}
    def validate(doc):validate_document(doc,partial)
    checkpoint()
    while True:
        draft=entry['draft'];validate(draft)
        if not entry['pending_issues']:
            ids={b['id'] for b in draft['sections'][0]['blocks']}
            def validate_review(result):
                issues=result.get('issues')
                if not isinstance(issues,list) or len(issues)>24:raise ValueError('本章最多24项具体问题')
                for issue in issues:
                    if (not issue.get('block_ids') or set(issue['block_ids'])-ids or
                        issue.get('severity') not in ('hard','soft') or not all(issue.get(k) for k in ('rule_id','reason','suggestion'))):
                        raise ValueError('问题需定位本章实际块ID，给出有效严重度、规则和具体修改依据')
                    if issue['severity']=='hard':
                        quote=issue.get('quote')
                        def block_content(b):
                            if b['type']=='table':return ' '.join(str(v) for row in [b['headers'],*b['rows']] for v in row)
                            if b['type']=='list':return ' '.join(b['items'])
                            return str(b.get('text') or b.get('caption') or '')
                        if not isinstance(quote,str) or not quote.strip() or not any(
                            quote in block_content(b) for b in draft['sections'][0]['blocks'] if b['id'] in issue['block_ids']):
                            raise ValueError('hard问题的quote必须逐字出现在当前本章指定block中；不得引用已删除旧文或材料内容，表格引用单元格原文')
            try:
                result=w.role('report_requirement_reviewer',CHAPTER_REVIEW,
                    {'chapter_scope':scope,'target_heading':heading,'document':draft,'instructions':p.data['instructions'],
                     'original_source_excerpts':sources,'teacher_requirement_excerpts':teacher,'evidence':evidence},validate_review,
                    task_id=f'chapter-review:{section_index}:{key[:8]}:{len(entry["history"])}')
            except OutputTruncated as exc:
                entry['review_error']=str(exc)
                return defer('review_output_incomplete')
            except Paused as exc:
                if not str(exc).startswith('审查'):raise
                entry['review_error']=str(exc)
                return defer('review_budget_or_protocol')
            except StageUnresolved as exc:
                if exc.kind not in ('protocol','quality'):raise
                entry['review_error']=exc.reason
                return defer('review_protocol')
            from .report_lean_review import enabled as lean_enabled
            issues=local_policy_issues(draft, lean=lean_enabled(p))+calibrate_issues(result['issues'],roles)
            hard=[i for i in issues if i['severity']=='hard']
            signature=fingerprint(sorted((i['rule_id'],tuple(sorted(i['block_ids']))) for i in hard))
            prior=entry['history'][-1] if entry['history'] else None
            entry['history'].append({'attempt':len(entry['history']),'issues':issues,'summary':result.get('summary',''),
                'draft_hash':fingerprint(draft),'hard_signature':signature})
            entry['pending_issues']=hard;checkpoint()
            w.logger.log('chapter_review',heading=heading,section_index=section_index,attempt=len(entry['history'])-1,
                hard_issues=len(hard),repairs=entry['repairs'],checkpoint=str(path.relative_to(p.root)))
            if not hard:
                entry.update(status='passed',pending_issues=None);checkpoint();return copy.deepcopy(draft)
            if prior and prior['hard_signature']==signature and prior['draft_hash']==fingerprint(draft):return defer('no_progress')
            if any(h['draft_hash']==fingerprint(draft) and h['hard_signature']==signature for h in entry['history'][:-1]):
                return defer('revision_cycle')
        ids={b['id'] for b in draft['sections'][0]['blocks']}
        locked={b['id'] for s in w.state['outputs'].get('sample',{}).get('sections',[]) for b in s.get('blocks',[])}
        def validate_patch(result):
            patches=result.get('patches')
            if not isinstance(patches,list) or len(json.dumps(patches,ensure_ascii=False))>18000:
                raise ValueError('只提交本章有界patches，最多18000字符')
            updated=apply_local_patches(draft,patches,ids,locked)
            preserve_result_tables(draft,updated);validate(updated)
        try:
            result=w.role('report_patcher',PATCH+'\n'+CHAPTER_EDIT,
                {'chapter_scope':scope,'target_heading':heading,'candidate':draft,
                 'editable_block_ids':sorted(ids),'locked_blocks':sorted(locked),
                 'new_block_id_prefix':f'chapter-{section_index}-{entry["repairs"]}-',
                 'requirement_feedback':entry['pending_issues'],'original_source_excerpts':sources,'teacher_requirement_excerpts':teacher,
                 'evidence':evidence,'instructions':p.data['instructions']},validate_patch,
                task_id=f'chapter-repair:{section_index}:{key[:8]}:{entry["repairs"]}')
        except OutputTruncated as exc:
            entry['repair_error']=str(exc)
            return defer('repair_output_incomplete')
        except StageUnresolved as exc:
            if exc.kind not in ('protocol','quality'):raise
            entry['repair_error']=exc.reason
            return defer('repair_protocol')
        entry['draft']=apply_local_patches(draft,result['patches'],ids,locked)
        entry.setdefault('patches',[]).append(result['patches'])
        entry['repairs']+=1;entry['pending_issues']=None;checkpoint()
