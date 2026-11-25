"""Local experiment API orchestration. A project has one active writer."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .lab_pipeline import LabPipeline
from .lab_project import LabProject, list_projects


class LabHub:
    def __init__(self):
        self.lock = threading.RLock()
        self.runs = {}

    def key(self, workspace, pid):
        return (str(Path(workspace).resolve()).casefold(), pid)

    def busy(self, workspace=None):
        with self.lock:
            return [pid for (ws, pid), (thread, _) in self.runs.items()
                    if thread.is_alive() and (workspace is None or ws == str(Path(workspace).resolve()).casefold())]

    def is_busy(self, workspace, pid):
        if pid in self.busy(workspace):
            return True
        project = LabProject(workspace, pid)
        try:
            stream = project.acquire()
        except ValueError:
            return True
        stream.close()
        return False

    def snapshot(self, workspace, pid):
        project = LabProject(workspace, pid)
        data = project.data
        data['busy'] = self.is_busy(workspace, pid)
        if data['status'] == 'running' and not data['busy']:
            data['status'] = 'interrupted'
            data['last_error'] = '服务已重启；完成的任务已保存，点击继续。运行中的外部作业会按原记录接续。'
        return data

    def start(self, workspace, pid, args):
        key = self.key(workspace, pid)
        with self.lock:
            if self.is_busy(workspace, pid):
                raise ValueError('这个实验正在执行')
            project = LabProject(workspace, pid)
            if args.get('action')=='studio':
                from .studio_workspace import StudioRunner
                pipeline=StudioRunner(project,args)
                thread=threading.Thread(target=pipeline.advance,daemon=True)
                self.runs[key]=(thread,pipeline);thread.start()
                return {'accepted':True}
            if args.get('action')=='report':
                from .report_workflow import ReportWorkflow
                from .report_intake import prepare_report
                prepare_report(project)
                pipeline_class=ReportWorkflow
            else:pipeline_class=LabPipeline
            from .report_context import REPORT_LIMITS
            defaults=project.data.get('report_workflow',{}).get('limits',REPORT_LIMITS) if args.get('action')=='report' else {'max_steps':100,'max_cost':.5,'max_seconds':1800}
            pipeline = pipeline_class(project, max_steps=int(args.get('max_steps', defaults['max_steps'])),
                                   max_cost=float(args.get('max_cost', defaults['max_cost'])), max_seconds=int(args.get('max_seconds', defaults['max_seconds'])),
                                   review_rounds=int(args.get('review_rounds', 2)))
            if args.get('action')=='report' and args.get('automatic') and not pipeline.automatic:
                pipeline.enable_automatic()
            thread = (threading.Thread(target=pipeline.advance,daemon=True) if args.get('action')=='report' else
                threading.Thread(target=pipeline.run, kwargs={'action': args.get('action', 'run')}, daemon=True))
            self.runs[key] = (thread, pipeline)
            thread.start()
            # A lock conflict with another process is reported synchronously above;
            # unexpected worker failures still remain visible in the project trace.
        return {'accepted': True}

    def pause(self, workspace, pid):
        with self.lock:
            item = self.runs.get(self.key(workspace, pid))
            if item and item[0].is_alive():
                item[1].request_pause()
        return {'pause_requested': True, 'notice': '前台任务会停止；已启动的后台Python作业保留，继续时接续。'}

    def mutate(self, workspace, pid, operation):
        with self.lock:
            if self.is_busy(workspace, pid):
                raise ValueError('请先暂停当前实验再修改')
            project = LabProject(workspace, pid)
            stream = project.acquire()
            try:
                result = operation(project)
                project.save()
                return result
            finally:
                stream.close()

    def close(self):
        with self.lock:
            for thread, pipeline in self.runs.values():
                if thread.is_alive():
                    pipeline.request_pause()

    def selection_action(self, workspace, pid, data):
        from .report_discussion import SelectionRunner, queue, snapshot
        with self.lock:
            if self.is_busy(workspace, pid):raise ValueError('当前报告正在处理，请稍候或先暂停')
            project = LabProject(workspace, pid)
            stream = project.acquire()
            try:
                discussion, start = queue(project, data['thread_id'], data['action'], data)
                runner = SelectionRunner(project)
                project.save()
            finally:stream.close()
            if start:
                worker = threading.Thread(target=runner.run_action, args=(discussion['id'],), daemon=True)
                self.runs[self.key(workspace, pid)] = (worker, runner);worker.start()
            return {'thread_id': discussion['id'], 'accepted': start}


def get_lab(hub, workspace, route, params):
    if route.startswith('/api/lab/studio/'):
        from . import studio_workspace as studio
        if route=='/api/lab/studio/projects':return studio.library(workspace,hub)
        if route=='/api/lab/studio/runtimes':return studio.runtime_catalog(workspace)
        if route=='/api/lab/studio/memories':
            from .writing_memory import memories
            return memories()
        project=LabProject(workspace,params['project'])
        if route=='/api/lab/studio/progress':return studio.progress(project,hub.is_busy(workspace,project.id))
        if route=='/api/lab/studio/files':return studio.files(project)
        if route=='/api/lab/studio/compare':return studio.compare_versions(project,params['from'],params['to'])
        if route=='/api/lab/studio/preview':
            path=project.file(params['path'])
            if path.stat().st_size>2_000_000:raise ValueError('文件较大，请下载后查看')
            return {'name':path.name,'text':path.read_text(encoding='utf-8-sig',errors='replace')[:100000]}
    if route == '/api/lab/report/editor':
        from .report_discussion import snapshot
        return snapshot(LabProject(workspace, params['project']), hub.is_busy(workspace, params['project']))
    if route == '/api/lab/report/state':
        from .report_workflow import ReportWorkflow
        project=LabProject(workspace,params['project'])
        state=ReportWorkflow(project).snapshot()
        state.update(busy=hub.is_busy(workspace,project.id),materials=project.data['materials'],
            material_groups=project.data.get('report_material_groups',[]),title=project.data['title'])
        if state['report_workflow']['status']=='running' and not state['busy']:
            state['report_workflow']={**state['report_workflow'],'status':'interrupted','error':'本机服务曾中断，已完成的内容已保存，可从断点恢复。'}
        return state
    if route == '/api/lab/projects':
        return list_projects(workspace)
    if route == '/api/lab/state':
        return hub.snapshot(workspace, params['project'])
    if route == '/api/lab/estimate':
        return LabPipeline(LabProject(workspace, params['project'])).estimate()
    if route == '/api/lab/resources':
        from .lab_environment import discover
        project=LabProject(workspace,params['project'])
        if project.data.get('resources'):
            return project.data['resources']
        if hub.is_busy(workspace,project.id):
            return discover()
        return hub.mutate(workspace,project.id,lambda p:__import__('myagent.lab_environment',fromlist=['get_inventory']).get_inventory(p))
    if route == '/api/lab/bundle':
        import io
        import os
        import zipfile
        project = LabProject(workspace, params['project'])
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            paths = [project.path, project.root/'materials.json', project.root/'template.json']
            for directory in ('reports', 'outputs', 'traces', 'work','inputs'):
                for root,dirs,files in os.walk(project.root/directory,followlinks=False):
                    dirs[:]=[d for d in dirs if d not in ('harness-home','course-skill-source','node_modules','.git','__pycache__')
                             and not (Path(root)/d).is_symlink() and not getattr(Path(root)/d,'is_junction',lambda:False)()]
                    paths.extend(Path(root)/name for name in files)
            for path in paths:
                relative = path.relative_to(project.root)
                if path.is_file() and not {'harness-home','course-skill-source','__pycache__'}.intersection(relative.parts) and path.suffix not in ('.lock', '.pyc'):
                    archive.write(path, str(relative))
        return raw.getvalue()
    if route == '/api/lab/export':
        project = LabProject(workspace, params['project'])
        traces = []
        for run in [*project.data['runs'], *project.data.get('selection_runs', [])]:
            path = project.file(run['trace'])
            from .events import read_events
            traces.append({'run': run, 'events': read_events(path, tolerate_incomplete_tail=True)})
        from .report_discussion import threads
        from .writing_memory import memories
        return {'project': project.data, 'traces': traces, 'discussions': threads(project),
                'writing_memories': [e for e in memories(include_deleted=True)
                                     if e['source']['workspace'] == str(project.workspace) and e['source']['project'] == project.id],
                'snapshot': hub.is_busy(workspace, project.id)}
    raise ValueError('未知实验接口')


def post_lab(hub, workspace, route, data):
    if route=='/api/lab/studio/create':
        from .studio_workspace import create_project
        with hub.lock:
            project=create_project(workspace,data)
            # Retry of an acknowledged upload must not create or run another experiment.
            if data.get('start',True) and not hub.is_busy(workspace,project.id) and not project.data['runs'] and not project.data.get('report_workflow'):
                hub.start(workspace,project.id,{**data,'action':'studio'})
        return {'project':project.id,'accepted':bool(data.get('start',True))}
    if route=='/api/lab/studio/manage':
        def manage(p):
            action=data['action']
            if action=='rename':
                title=data.get('title','').strip()
                if not title:raise ValueError('报告名称不能为空')
                p.data['title']=title[:180]
            elif action in ('archive','unarchive','star','unstar'):
                meta=p.data.setdefault('studio',{})
                meta['archived' if action in ('archive','unarchive') else 'starred']=action in ('archive','star')
            elif action=='restore':
                from .studio_workspace import restore_version
                return restore_version(p,data['version'])
            else:raise ValueError('未知报告管理操作')
            p.note('已更新报告管理信息',action=action)
            return {'saved':True}
        return hub.mutate(workspace,data['project'],manage)
    if route == '/api/lab/studio/replace-guidance':
        from .studio_workspace import replace_guidance
        pid = data['project']
        with hub.lock:
            hub.mutate(workspace, pid, lambda project: replace_guidance(project, data['path']))
            return hub.start(workspace, pid, {'action': 'studio'})
    if route=='/api/lab/studio/reply':
        p=LabProject(workspace,data['project'])
        if p.data.get('report_workflow'):
            return post_lab(hub,workspace,'/api/lab/report/reply',{**data,'automatic':True})
        text=data.get('text','').strip()
        if not text:raise ValueError('请填写补充信息')
        hub.mutate(workspace,p.id,lambda p:p.update_instructions(p.data['instructions']+'\n用户补充：'+text))
        return hub.start(workspace,p.id,{**data,'action':'studio'})
    if route == '/api/lab/report/create':
        from .report_intake import create_report
        project=create_report(workspace,data)
        hub.start(workspace,project.id,{**data,'action':'report','automatic':True})
        return {'project':project.id,'accepted':True}
    if route == '/api/lab/create':
        project = LabProject.create(workspace, title=data['title'], materials=data['materials'],
                                    instructions=data.get('instructions', ''), student_id=data.get('student_id', ''),
                                    include_bonus=data.get('include_bonus', False), student=data.get('student'))
        project.data['use_default_report_template']=True;project.save()
        from .lab_environment import get_inventory
        get_inventory(project)
        return project.data
    pid = data['project']
    if route == '/api/lab/report/discussion':
        if data['action'] == 'create':
            from .report_discussion import create
            return hub.mutate(workspace, pid, lambda p: create(p, data['anchor'], int(data['version']), client_id=data.get('client_id')))
        return hub.selection_action(workspace, pid, data)
    if route == '/api/lab/report/memory':
        from .writing_memory import update_memory
        return update_memory(data['id'], lesson=data.get('lesson'), delete=data.get('action') == 'delete', restore=data.get('action') == 'restore')
    if route == '/api/lab/report/start':
        return hub.start(workspace,pid,{**data,'action':'report'})
    if route == '/api/lab/report/reply':
        from .report_workflow import ReportWorkflow
        with hub.lock:
            if hub.is_busy(workspace,pid):raise ValueError('报告Agent正在工作，请等待当前步骤结束')
            result=ReportWorkflow(LabProject(workspace,pid)).reply(data['text'],decision=data.get('decision','answer'),
                pending_id=data['pending_id'],origin='web')
            if data.get('advance',True):
                hub.start(workspace,pid,{**data,'action':'report'})
            return result
    if route == '/api/lab/materials':
        return hub.mutate(workspace,pid,lambda p:p.add_materials(data['materials']))
    if route == '/api/lab/environment':
        def update_environment(p):
            from .lab_environment import get_inventory, probe_interpreter, probe_a100
            if data.get('remote_probe'):
                result = probe_a100()
                p.data.setdefault('resources', get_inventory(p))['adapters']['A100'] = result
                return result
            record = probe_interpreter(data['interpreter_id'], get_inventory(p))
            p.data['execution'] = {'interpreter_id':record['id'], 'interpreter':record['path'], 'packages':record['packages']}
            p.note('选择实验Python环境：' + record['id'])
            return record
        return hub.mutate(workspace, pid, update_environment)
    if route == '/api/lab/start':
        return hub.start(workspace, pid, data)
    if route == '/api/lab/pause':
        return hub.pause(workspace, pid)
    if route == '/api/lab/comment':
        return hub.mutate(workspace, pid, lambda p: p.comment(data['block_id'], data['text'], int(data['version']),data.get('action','text'),data.get('task_id')))
    if route == '/api/lab/instructions':
        def update(p):
            return p.update_instructions(data['instructions'])
        return hub.mutate(workspace, pid, update)
    raise ValueError('未知实验操作')


def register_lab_command(sub):
    parser = sub.add_parser('lab', help='specialized PDF guidance to experiment report pipeline')
    parser.add_argument('action', choices=('create', 'list', 'plan', 'run', 'revise', 'write', 'show'))
    parser.add_argument('--workspace', default='.')
    parser.add_argument('--project')
    parser.add_argument('--title', default='新实验')
    parser.add_argument('--guidance', action='append', default=[])
    parser.add_argument('--data', action='append', default=[])
    parser.add_argument('--template', action='append', default=[])
    parser.add_argument('--reference', action='append', default=[])
    parser.add_argument('--instructions', default='')
    parser.add_argument('--student-id', default='')
    parser.add_argument('--name', default='')
    parser.add_argument('--teacher', default='')
    parser.add_argument('--include-bonus', action='store_true')
    parser.add_argument('--max-cost', type=float, default=.5)
    parser.add_argument('--max-steps', type=int, default=100)
    parser.add_argument('--max-seconds', type=int, default=1800)
    parser.add_argument('--review-rounds', type=int, default=2)
    parser.set_defaults(func=cmd_lab)


def cmd_lab(args):
    if args.action == 'create':
        created = LabProject.create(args.workspace, title=args.title,
                    materials=[{'path': p, 'role': role} for role, paths in [('guidance', args.guidance), ('data', args.data), ('template', args.template), ('reference', args.reference)] for p in paths],
                    instructions=args.instructions, student_id=args.student_id, include_bonus=args.include_bonus,
                    student={'name':args.name,'teacher':args.teacher})
        created.data['use_default_report_template']=True;created.save();result=created.data
    elif args.action == 'list':
        result = list_projects(args.workspace)
    else:
        project = LabProject(args.workspace, args.project)
        if args.action == 'show':
            result = project.data
        else:
            pipeline = LabPipeline(project, max_cost=args.max_cost, max_steps=args.max_steps,
                                   max_seconds=args.max_seconds, review_rounds=args.review_rounds)
            print(json.dumps({'estimate': pipeline.estimate()}, ensure_ascii=False), flush=True)
            result = pipeline.run(action=args.action)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if isinstance(result, list) or result['status'] in ('ready', 'planned', 'completed') else 1
