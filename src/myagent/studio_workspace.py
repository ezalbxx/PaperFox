"""Paperfox workbench: uploads, native execution-to-writing handoff and library.

Progress comes from persisted stages/tasks/parts, never a timer-driven percent.
No experiment implementation or report prose is supplied by this controller.
"""
from __future__ import annotations

import json
import os
import threading
import time
import sys
import hashlib
from pathlib import Path
from uuid import uuid4

from .jobs import atomic_json
from .lab_project import LabProject, digest, now

PHASES = [('materials', '接收材料'), ('planning', '理解要求'), ('execution', '执行实验'),
          ('structure', '组织图文'), ('writing', '撰写报告'), ('formatting', '排版检查'), ('ready', '阅读与改稿')]
ROLE_NAMES = {'planner':'理解指导书并规划实验', 'executor':'执行实验任务', 'report_librarian':'整理输入材料',
    'report_interviewer':'确认报告要求', 'report_facts':'整理实验事实', 'report_story_cards':'梳理实验主线',
    'report_designer':'组织章节和图表', 'report_figures':'准备报告图表', 'writer':'撰写报告内容',
    'report_patcher':'整理与修订正文', 'report_formatter':'安排最终版式',
    'report_requirement_reviewer':'检查报告内容', 'selection_editor':'讨论选中的文字',
    'selection_memory':'整理写作经验'}


def upload_root(workspace):
    return Path(workspace) / '.paperfox' / 'uploads'


def runtime_catalog(workspace):
    executable=Path(sys.executable)
    if executable.name.lower()=='pythonw.exe' and executable.with_name('python.exe').exists():executable=executable.with_name('python.exe')
    paths=[(executable,'应用环境（默认）')]
    for path in (Path(workspace)/'experiments').glob('*/project.json'):
        data=json.loads(path.read_text(encoding='utf-8'))
        raw=data.get('execution',{}).get('interpreter')
        if raw and Path(raw).is_file():paths.append((Path(raw),'沿用 '+data['title'][:20]+' 的环境'))
    for root in (Path('D:/conda_envs'),Path('D:/Anaconda/envs'),Path.home()/'miniconda3/envs'):
        paths.extend((p,p.parent.name) for p in root.glob('*/python.exe'))
    seen=set();rows=[]
    for path,label in paths:
        key=str(path.resolve()).casefold()
        if key in seen:continue
        seen.add(key);rows.append({'id':'python-'+hashlib.sha256(key.encode()).hexdigest()[:12], 'path':str(path),'label':label})
    return {'interpreters':rows}


def receive_upload(workspace, params, stream, size):
    """Stream a browser file to a batch; originals on the computer stay untouched."""
    batch = params.get('batch', '')
    if not batch or len(batch) > 64 or any(c not in '0123456789abcdef-' for c in batch):
        raise ValueError('无效的上传批次，请重新选择文件')
    name = params.get('name', '').replace('\\', '/').split('/')[-1]
    if not name or name in ('.', '..') or name.lower().startswith('.env'):
        raise ValueError('请选择实验文件，密钥文件不能作为材料')
    if size <= 0 or size > 256 * 1024 * 1024:
        raise ValueError('单文件需介于1字节与256MB之间；大数据请使用本机材料目录')
    suffix = Path(name).suffix.lower()
    folder = upload_root(workspace) / batch
    folder.mkdir(parents=True, exist_ok=True)
    identity = uuid4().hex
    path = folder / (identity + suffix)
    try:
        remaining = size
        with path.open('wb') as target:
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:raise ValueError('上传中断，请重新上传这个文件')
                target.write(block);remaining -= len(block)
        record = {'token': f'{batch}/{identity}{suffix}', 'name': name, 'bytes': size, 'sha256': digest(path), 'at': now()}
        atomic_json(path.with_name(path.name + '.meta.json'), record)
        return record
    except Exception:
        path.unlink(missing_ok=True)
        raise


def resolve_upload(workspace, token):
    root = upload_root(workspace).resolve()
    path = (root / token).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('上传文件已失效，请重新选择')
    record = json.loads(path.with_name(path.name + '.meta.json').read_text(encoding='utf-8'))
    if record['token'] != token:raise ValueError('上传记录不匹配')
    return path, record


def create_project(workspace, data):
    request_id = data.get('request_id','')
    request_path = None
    if request_id:
        if len(request_id)>64 or any(c not in '0123456789abcdef-' for c in request_id):raise ValueError('无效创建请求')
        request_path=Path(workspace)/'.paperfox/requests'/f'{request_id}.json'
        if request_path.exists():
            return LabProject(workspace,json.loads(request_path.read_text(encoding='utf-8'))['project'])
    mode = data.get('mode', 'report')
    if mode not in ('execute', 'report'):
        raise ValueError('无效项目模式')
    items = data.get('files', [])
    sources, uploaded = [], []
    for item in items:
        path, record = resolve_upload(workspace, item['token'])
        # LabProject preserves source basenames in its input inventory.
        named = path.parent / (path.stem + '-named') / record['name']
        named.parent.mkdir(exist_ok=True)
        import shutil
        shutil.copyfile(path, named)
        sources.append({'path': str(named), 'role': item.get('role', 'data')})
        uploaded.append((path, named, record))
    if data.get('guidance_path'):
        sources.insert(0, {'path': data['guidance_path'], 'role': 'guidance'})
    if data.get('library_path'):
        library = Path(data['library_path']).expanduser().resolve()
        if not library.is_dir():
            raise ValueError('请选择可读取的实验材料目录')
        if Path(workspace).resolve().is_relative_to(library):
            raise ValueError('请选择独立的实验材料目录')
        sources.append({'path': str(library), 'role': 'library' if mode == 'report' else 'data'})
    title = data.get('title', '').strip() or '新的实验报告'
    execution=None
    if data.get('interpreter_id'):
        from .lab_environment import probe_interpreter
        record=probe_interpreter(data['interpreter_id'],runtime_catalog(workspace))
        execution={'interpreter_id':record['id'],'interpreter':record['path'],'packages':record['packages']}
    p = LabProject.create(workspace, title=title, materials=sources,
        instructions=data.get('instructions', ''), student_id=data.get('student_id',''), student=data.get('student'),
        include_bonus=bool(data.get('include_bonus')))
    if execution:p.data['execution']=execution
    p.data['use_default_report_template']=True
    p.data['report_first_pass']=True
    p.data['report_total_budget_cny']=3.0
    p.data['studio'] = {'mode': mode, 'archived': False, 'starred': False, 'created_at': now(), 'phase': 'materials'}
    if data.get('validation_origin'):p.data['validation_origin'] = data['validation_origin']
    p.note('材料已接收，已建立独立报告项目', files=len(p.data['materials']))
    if request_path:
        request_path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(request_path,{'project':p.id,'at':now()})
    # A successful import has a canonical input copy; release only these uploaded copies.
    for path, named, record in uploaded:
        path.unlink(missing_ok=True);named.unlink(missing_ok=True)
        named.parent.rmdir()
        record.update(consumed_by=p.id, consumed_at=now())
        atomic_json(path.with_name(path.name + '.meta.json'), record)
    return p


def prepare_executed_report(p):
    """Index actual native artifacts without relabeling them as user imports."""
    if 'report_sources' in p.data:return
    records = []; seen = set()
    for task in p.data['tasks']:
        result = p.data['results'].get(task['id'], {})
        paths = [a['path'] if isinstance(a, dict) else a for a in result.get('artifacts', [])]
        paths += result.get('source_paths', [])
        paths += [r['path'] for r in p.data['receipts'] if r.get('task_id') == task['id'] and r.get('path')]
        for raw in paths:
            path = p.file(raw)
            if not path.is_file() or str(path) in seen:continue
            seen.add(str(path))
            category = 'figures' if path.suffix.lower() in ('.png','.jpg','.jpeg','.svg') else 'code' if path.suffix.lower() in ('.py','.ipynb') else 'results'
            records.append({'id':f'S{len(records)+1:04}', 'category':'experiment_'+task['id'], 'kind':category, 'label':path.name,
                'path':str(path.relative_to(p.root)), 'sha256':digest(path), 'bytes':path.stat().st_size,
                'task_id':task['id'], 'origin':'Native Agent execution; original receipts and run traces retained.'})
    p.data['report_sources'] = records
    p.data['report_profile'] = 'executed_experiment'
    p.data['report_import'] = {'at':now(), 'source':'native_agent_execution', 'no_execution':False}
    p.data['report_material_groups'] = [{'task_id':t['id'],'category':'experiment_'+t['id'],'title':t['title'],
        'count':sum(r['task_id']==t['id'] for r in records)} for t in p.data['tasks']]
    atomic_json(p.root/'source-manifest.json', {'sources':records,'origin':'native_agent_execution'})
    p.save()


class StudioRunner:
    def __init__(self, project, args, model_factory=None):
        self.project, self.args, self.model_factory = project, args, model_factory
        self.cancel = threading.Event();self.current = None

    def request_pause(self):
        self.cancel.set()
        if self.current:self.current.request_pause()

    def advance(self):
        from .lab_pipeline import LabPipeline
        from .report_workflow import ReportWorkflow
        from .report_intake import prepare_report
        p = self.project
        options = {k:self.args[k] for k in ('max_steps','max_cost','max_seconds') if k in self.args}
        options.setdefault('max_steps',400);options.setdefault('max_cost',5.0);options.setdefault('max_seconds',7200)
        if self.model_factory:options['model_factory'] = self.model_factory
        try:
            if p.data.get('studio',{}).get('mode') == 'execute' and not p.data.get('report_sources'):
                p.data['studio']['phase'] = 'execution';p.save()
                self.current = LabPipeline(p, **options)
                self.current.run(action='run', execution_only=True)
                p = self.project = LabProject(p.workspace, p.id)
                if self.cancel.is_set() or p.data['status'] != 'executed':return
                prepare_executed_report(p)
            else:prepare_report(p)
            if self.cancel.is_set():return
            p.data.setdefault('studio',{})['phase'] = 'report';p.save()
            self.current = ReportWorkflow(p, **options)
            if not self.current.automatic:self.current.enable_automatic()
            if self.cancel.is_set():return
            self.current.advance()
        except Exception as exc:
            # Native stages retain their own errors; controller failures also remain resumable.
            p = LabProject(p.workspace,p.id)
            p.data.update(status='failed',last_error=f'{type(exc).__name__}: {exc}')
            if p.data.get('report_workflow'):
                p.data['report_workflow'].update(status='failed',error=p.data['last_error'])
            p.note('流程已保存，处理遇到问题');p.save()


def progress(project, busy=False):
    p = project.data; w = p.get('report_workflow',{}); report = p.get('report')
    raw_stage = w.get('stage') if w else p.get('stage','materials')
    phase_map = {'materials':0,'intake':1,'plan':1,'facts':1,'library':1,'story_cards':3,'outline':3,'sample':3,
        'execution':2,'execution_complete':3,'writing':4,'editing':5,'formatting':5,'review':5,'delivery':6,'done':6}
    index = phase_map.get(raw_stage,0)
    if w and p.get('report_profile')=='executed_experiment' and raw_stage in ('intake','facts','library'):
        index=3  # Post-experiment evidence organization must not jump back to planning.
    state = w.get('status') or p.get('status','ready')
    if busy:state = 'running'
    elif state == 'running':state = 'interrupted'
    tasks = [{'id':t['id'],'title':t['title'],'status':
        'partial' if p.get('results',{}).get(t['id'],{}).get('remaining_work') else 'done' if t['id'] in p.get('results',{}) else 'pending'} for t in p.get('tasks',[])]
    detail = w.get('progress') or {}
    fraction = 0
    if index == 2 and tasks:fraction = sum(t['status']=='done' for t in tasks)/len(tasks)
    elif index in (3,4,5) and detail.get('total'):
        fraction = min(1,detail.get('completed',0)/max(1,detail['total']))
    percent = 100 if index == 6 and report else min(99,round((index+fraction)/6*100))
    pending = w.get('pending')
    questions = pending.get('questions',[]) if pending else []
    if not w and state == 'needs_input':questions = p.get('plan',{}).get('questions',[])
    activity = []
    for a in p.get('activity',[])[-22:]:
        text = ROLE_NAMES.get(a.get('role')) or a['text']
        if a.get('role') and '开始' in a.get('text',''):text += '…'
        activity.append({'at':a['at'],'text':text,'role':a.get('role')})
    activity.extend(tool_activity(project))
    activity=sorted(activity,key=lambda a:a['at'])[-26:]
    draft = p.get('writing_draft') or {}
    review=p.get('reviews',[])[-1] if p.get('reviews') else {}
    issues = list(review.get('issues', [])) if report and review.get('version') == report['version'] else []
    if report:
        issues.extend(report.get('student_voice_check', {}).get('issues', []))
    previews=[];seen_previews=set()
    image_paths=[a['path'] if isinstance(a,dict) else a for result in p.get('results',{}).values() for a in result.get('artifacts',[])]
    for raw in image_paths:
        if Path(raw).suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or raw in seen_previews:continue
        if not project.file(raw).is_file():continue
        seen_previews.add(raw);previews.append({'path':raw,'name':Path(raw).name})
        if len(previews)==4:break
    return {'id':p['id'],'title':p['title'],'busy':busy,'status':state,'phase':PHASES[index][0],
        'phase_index':index,'percent':max(0,min(100,percent)),'phases':[{'id':k,'name':'使用已有结果' if k=='execution' and p.get('studio',{}).get('mode')=='report' else n,
            'state':'done' if i<index else 'current' if i==index else 'pending'} for i,(k,n) in enumerate(PHASES)],
        'stage':raw_stage,'detail':detail,'tasks':tasks,'activity':activity,'questions':questions,
        'pending_id':pending.get('id') if pending else None,'pending_checkpoint':bool(pending and pending.get('checkpoint')),
        'error':'' if busy else (w.get('error','') if w else p.get('last_error','')),'usage':p['totals'],
        'created_at':p['created_at'],'updated_at':p['updated_at'],'studio':p.get('studio',{}),
        'report':{k:report[k] for k in ('version','pdf','sha256') if k in report} if report else None,
        'draft_sections':[{'heading':s['heading'],'blocks':len(s.get('blocks',[]))} for s in draft.get('sections',[])],
        'issues':issues,
        'previews':previews,
        'materials_count':len(p.get('materials',[])),'versions_count':len(p.get('revisions',[])),
        'resume_action':'studio' if p.get('studio') else 'report' if w else 'run'}


def tool_activity(project):
    """Read a bounded tail of the real active trace, without exposing its prompts."""
    p=project.data;w=p.get('report_workflow',{})
    raw=(w.get('debug',{}).get('latest') or {}).get('trace') if w else None
    if not raw and p.get('runs'):raw=p['runs'][-1]['trace']
    if not raw:return []
    try:
        path=project.file(raw)
        with path.open('rb') as stream:
            size=stream.seek(0,2);stream.seek(max(0,size-512000))
            tail=stream.read().decode('utf-8',errors='replace')
    except OSError:return []
    rows=[];calls={}
    for line in tail.splitlines():
        try:event=json.loads(line)
        except ValueError:continue  # An active writer's unfinished tail is not an event.
        data=event.get('payload',{})
        if event.get('type')=='tool_call':
            args=data.get('args',{})
            if isinstance(args,str):
                try:args=json.loads(args)
                except ValueError:args={}
            name=data.get('name','');text=''
            if name=='lab_files':
                text=('保存实验文件' if args.get('operation')=='write' else '查看实验文件')
                file=(args.get('inputs') or {}).get('path')
                if file:text+=' · '+Path(file).name
            elif name=='lab_python':text='运行实验程序'+(' · '+Path(args['path']).name if args.get('path') else '')
            elif name=='report_materials':text='读取相关实验材料'
            elif name=='lab_figure':text='准备实验图表'
            elif name=='finish_stage':text='整理并保存当前阶段结果'
            calls[data.get('call_id')]=name
            if text:rows.append({'at':event['ts'],'text':text,'event_id':event['id']})
        elif event.get('type')=='tool_result':
            name=calls.get(data.get('call_id'))
            if name=='finish_stage' and data.get('returncode')==0:
                rows.append({'at':event['ts'],'text':'当前阶段结果已保存','event_id':event['id']})
            elif name and data.get('returncode'):
                rows.append({'at':event['ts'],'text':'工具返回了待处理问题','event_id':event['id']})
    return rows[-12:]


def library(workspace, hub):
    rows = []
    for path in (Path(workspace)/'experiments').glob('*/project.json'):
        project = LabProject(workspace,path.parent.name)
        row = progress(project,hub.is_busy(workspace,project.id))
        rows.append({k:row[k] for k in ('id','title','status','phase','percent','busy','updated_at','created_at','studio','report','materials_count','versions_count')})
    return sorted(rows,key=lambda r:(not r['studio'].get('starred'),-__import__('datetime').datetime.fromisoformat(r['updated_at']).timestamp()))


def files(project):
    rows = []
    roles = {m['path']:m.get('role') for m in project.data['materials']}
    for group, directory in (('materials','inputs'),('artifacts','outputs'),('reports','reports'),('code','work')):
        base = project.root/directory
        if not base.exists():continue
        for root, dirs, names in os.walk(base,followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('.git','.venv','node_modules','__pycache__','report-debug','report-edits','report-discussions','requirement-checks','harness-home','course-skill-source')
                and not (Path(root)/d).is_symlink() and not getattr(Path(root)/d,'is_junction',lambda:False)()]
            for name in names:
                if name.startswith('.') or name.endswith(('.pyc','.lock','.meta.json')):continue
                path = Path(root)/name
                if path.is_symlink():continue
                rel = str(path.relative_to(project.root))
                rows.append({'name':name,'path':rel,'group':group,'bytes':path.stat().st_size,
                    'modified':path.stat().st_mtime,'role':roles.get(rel),'extension':path.suffix.lower()})
    versions=[]
    for revision in project.data.get('revisions',[]):
        path=project.file(revision['pdf'])
        versions.append({**revision,'modified':path.stat().st_mtime if path.exists() else None})
    return {'files':rows,'versions':versions,'current_version':(project.data.get('report') or {}).get('version')}


def compare_versions(project, before_version, after_version):
    documents=[]
    for version in (int(before_version),int(after_version)):
        row=next((r for r in project.data['revisions'] if r['version']==version),None)
        if not row:raise ValueError('报告版本不存在')
        documents.append(json.loads(project.file(row['pdf']).with_suffix('.json').read_text(encoding='utf-8')))
    def index(document):
        return {b['id']:(s['heading'],b) for s in document['sections'] for b in s['blocks']}
    def display(block):
        if not block:return ''
        if block['type']=='table':return '\n'.join(' | '.join(map(str,row)) for row in [block['headers'],*block.get('rows',[])])
        return block.get('text') or '\n'.join(block.get('items',[])) or block.get('caption') or block.get('path','')
    before,after=map(index,documents);changes=[]
    for bid in dict.fromkeys([*before,*after]):
        a,b=before.get(bid),after.get(bid)
        if a==b:continue
        changes.append({'id':bid,'heading':(b or a)[0],'kind':'added' if not a else 'removed' if not b else 'changed',
            'before':display(a[1]) if a else '', 'after':display(b[1]) if b else ''})
    return {'from':int(before_version),'to':int(after_version),'changes':changes,
            'title_before':documents[0]['title'],'title_after':documents[1]['title']}


def restore_version(project, version):
    from .lab_report import render_report
    row = next((r for r in project.data['revisions'] if r['version']==int(version)),None)
    if not row:raise ValueError('版本不存在')
    source = project.file(row['pdf']).with_suffix('.manifest.json')
    manifest = json.loads(source.read_text(encoding='utf-8'))
    report = render_report(project,manifest['document'],layout=manifest.get('layout') or None,
                           reason=f'user-restored-version:{version}')
    project.data.setdefault('report_workflow',{}).update(stage='delivery',status='needs_attention')
    project.data['writing_draft'] = report['document']
    project.note(f'恢复v{version}为新版本v{report["version"]}，原历史保留')
    return {'version':report['version'],'restored_from':int(version)}
