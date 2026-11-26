"""Small authored capability adapters available to the experiment executor."""
from __future__ import annotations

import json
import time
from uuid import uuid4

from .jobs import JobManager, TERMINAL
from .lab_project import digest, task_generation, current_receipts
from .skill_runtime import python_task
from .tools.base import ToolResult
from .tools.files import ReadFileTool, ListDirTool, WriteFileTool
from .tools.edit import EditFileTool
from .tools.registry import ToolRegistry


class FinishStage:
    name = 'finish_stage'
    description = 'Submit the structured stage result. Validation errors are returned for correction. Do not finish with plain prose.'
    parameters = {'type': 'object', 'properties': {'result': {'type': 'object'}}, 'required': ['result'], 'additionalProperties': False}

    def __init__(self, validator, result_schema=None, *, recover_protocol=False, normalizer=None):
        self.validator = validator
        self.result = None
        self.recover_protocol = recover_protocol
        self.normalizer = normalizer
        self.normalizations = []
        self.unresolved = None
        self.last_candidate = None
        self.validation_error = None
        if result_schema:
            self.parameters={'type':'object','properties':{'result':result_schema},'required':['result'], 'additionalProperties': False}
        if recover_protocol:
            self.parameters = {**self.parameters, 'properties': {**self.parameters['properties'],
                'unresolved': {'type': 'object', 'properties': {
                    'kind': {'type': 'string', 'enum': ['protocol','quality','facts','requirements','materials','safety']},
                    'reason': {'type': 'string'}, 'questions': {'type': 'array', 'items': {'type':'object'}}},
                    'required': ['kind','reason']}}, 'anyOf': [{'required':['result']},{'required':['unresolved']}]}
            self.parameters.pop('required', None)
            self.description += ' If success is impossible, submit unresolved={kind,reason,questions}; do not invent missing content to satisfy the success fields.'

    def run(self, args, ctx):
        if self.recover_protocol:
            from .report_protocol import submission
            result, changes, pending = submission(args)
            self.normalizations.extend(changes)
            if pending is not None:
                self.unresolved = pending
                self.result = {'unresolved': pending}
            else:
                self.last_candidate = result
                try:
                    if self.normalizer:
                        normalized=self.normalizer(result)
                        if normalized!=result:self.normalizations.append('program_metadata')
                        result=normalized
                    self.last_candidate = result
                    self.validator(result)
                except Exception as exc:
                    self.validation_error = exc
                    raise
                self.validation_error = None
                self.result = result
            ctx.submitted = True
            ctx.submission = 'Stage result saved' if pending else 'Structured stage result accepted'
            return ToolResult(output=json.dumps({'result': self.result, 'protocol_normalizations': changes}, ensure_ascii=False))
        if 'arguments' in args:
            detail = ''
            if isinstance(args['arguments'], str):
                try:
                    json.loads(args['arguments'])
                except json.JSONDecodeError as exc:
                    excerpt = args['arguments'][max(0, exc.pos - 90):exc.pos + 40]
                    detail = f' 内层JSON也未闭合或语法错误：{exc}；附近原文={excerpt!r}。'
            raise ValueError('不要把工具参数包装成arguments字符串。直接提交{"result":{...}}对象，'
                             'result内是本角色协议字段；不要提交{"arguments":"..."}。'
                             + detail + ' 请重新生成简洁、括号配对完整的对象，不复制此前的错误字符串。')
        misplaced = set(args) - {'result'}
        if misplaced:
            raise ValueError('finish_stage顶层只允许result；请把 ' + ', '.join(sorted(misplaced))
                             + ' 移入result对象，与claim_patches/claims等结果字段放在同一层，不要放在result外面')
        result = args['result']
        self.validator(result)
        self.result = result
        ctx.submitted = True
        ctx.submission = 'Structured stage result accepted'
        return ToolResult(output=json.dumps(result, ensure_ascii=False))


class LabFiles:
    name = 'lab_files'
    description = 'Our code workspace skill. operation read/list/write/edit. Read uses path/start_line/end_line; write path/content; edit path/old_text/new_text. Write only to work/ or outputs/. No shell.'
    parameters = {'type': 'object', 'properties': {'operation': {'type': 'string', 'enum': ['read', 'list', 'write', 'edit']},
                                                 'inputs': {'type': 'object', 'properties': {
                                                     'path': {'type':'string'}, 'content': {'type':'string'},
                                                     'old_text': {'type':'string'}, 'new_text': {'type':'string'},
                                                     'start_line': {'type':'integer'}, 'end_line': {'type':'integer'}},
                                                     'required':['path']}}, 'required': ['operation', 'inputs']}

    def run(self, args, ctx):
        op, inputs = args['operation'], args['inputs']
        if not inputs.get('path'):
            raise ValueError('path必须放在inputs对象内，例如{"operation":"write","inputs":{"path":"work/main.py","content":"代码"}}；代码content用实际换行，不是字面量反斜杠n。')
        from .tools.base import resolve_workspace_path
        path = resolve_workspace_path(ctx.workspace, inputs.get('path', '.'))
        if op in ('write', 'edit') and path.relative_to(ctx.workspace).parts[0] not in ('work', 'outputs'):
            raise ValueError('实验代码和产物分别写入work/、outputs/，不更改材料与项目状态')
        return {'read': ReadFileTool, 'list': ListDirTool, 'write': WriteFileTool, 'edit': EditFileTool}[op]().run(inputs, ctx)


class LabPython:
    name = 'lab_python'
    description = 'Our experiment skill: run a saved Python program using domain libraries. path, timeout_s (1-3600). No command string, argv, subprocess or shell. Saves real execution receipts automatically. Long runs wait locally without model calls. Reuse receipt_id to inspect/continue an existing run instead of rerunning it.'
    parameters = {'type': 'object', 'properties': {'path': {'type': 'string'}, 'timeout_s': {'type': 'integer'},
                                                 'receipt_id': {'type': 'string'}}, 'required': []}

    def __init__(self, pipeline, task_id):
        self.pipeline = pipeline
        self.project = pipeline.project
        self.task_id = task_id

    def run(self, args, ctx):
        project = self.project
        manager = JobManager(project.root)
        if args.get('receipt_id'):
            receipt = next(r for r in project.data['receipts'] if r['id'] == args['receipt_id'] and r['task_id'] == self.task_id)
            if not receipt.get('job_id') and receipt['state'] == 'running':
                raise ValueError('上次执行中断且结果未知，请检查产物后明确决定是否重跑')
        else:
            self.pipeline.check_limits()
            path = project.file(args['path'])
            if path.relative_to(project.root).parts[0] != 'work':
                raise ValueError('请把待运行程序写入work/')
            if any(r['task_id'] == self.task_id and r['state'] == 'running' for r in project.data['receipts']):
                raise ValueError('本任务已有运行记录，请用receipt_id接续')
            timeout = int(args.get('timeout_s', 30))
            if not 1 <= timeout <= 3600:
                raise ValueError('实验超时需要在1到3600秒之间')
            receipt = {'id': uuid4().hex[:12], 'task_id': self.task_id, 'path': args['path'],
                       'plan_generation':task_generation(project,self.task_id),
                       'source_sha256': digest(path), 'state': 'running', 'started_at': time.time()}
            project.data['receipts'].append(receipt)
            project.save()
            # Fixed interpreter; the model cannot choose an executable or raw argv.
            try:
                result = python_task({'path': args['path'], 'timeout_s': timeout, 'background': timeout > 30}, ctx)
                if timeout > 30:
                    receipt['job_id'] = result['id']
                else:
                    receipt.update(result, state='completed' if result['returncode'] == 0 else 'failed')
            except Exception as exc:
                receipt.update(state='failed', returncode=-1, error=str(exc))
            project.save()
        if receipt.get('job_id') and receipt['state'] == 'running':
            while True:
                record = manager.status(receipt['job_id'])
                if record['state'] in TERMINAL or record['state'] == 'unknown':
                    receipt.update(state=record['state'], returncode=record.get('returncode', -1),
                                   output=manager.logs(receipt['job_id']).get('stdout.log', ''),
                                   error=manager.logs(receipt['job_id']).get('stderr.log', ''))
                    break
                self.pipeline.check_limits()
                time.sleep(.25)
            project.save()
        receipt['elapsed_seconds'] = time.time() - receipt['started_at']
        project.save()
        return ToolResult(0 if receipt['state'] == 'completed' else -1,
                          json.dumps(receipt, ensure_ascii=False), receipt.get('error', ''))


class LabEvidence:
    name='lab_evidence'
    description='Read a registered experiment artifact by path/start_line/end_line, including large JSON evidence omitted from the writing packet. Read-only; no experiments or edits.'
    parameters={'type':'object','properties':{'path':{'type':'string'},'start_line':{'type':'integer'},'end_line':{'type':'integer'}},'required':['path']}

    def __init__(self,project):
        self.project=project

    def run(self,args,ctx):
        allowed={str(self.project.file(a['path'])) for r in self.project.data['results'].values() for a in r['artifacts']}
        if str(self.project.file(args['path'])) not in allowed:
            raise ValueError('请读取结果包登记的实验产物')
        return ReadFileTool().run(args,ctx)


def registry(pipeline, role, finish, task_id=None):
    tools = ToolRegistry()
    tools.register(finish)
    if getattr(pipeline,'report_collaboration',False) and role not in ('report_requirement_reviewer','report_formatter'):
        from .report_workflow import ReportMaterials
        if role != 'report_designer' or not pipeline.has_curated_planning_facts():
            tools.register(ReportMaterials(pipeline.project))
        if role == 'report_facts' and task_id == 'report:material_on_demand':
            from pathlib import Path
            from .report_calculations import ReportCalculations
            from .spreadsheet_material import SPREADSHEETS
            if any(Path(s['path']).suffix.lower() in SPREADSHEETS for s in pipeline.project.data['report_sources']):
                tools.register(ReportCalculations(pipeline.project))
        if role=='report_figures':
            from .lab_figures import LabFigures
            from .figure_references import FigureReferences
            tools.register(LabFigures(pipeline.project))
            tools.register(FigureReferences(pipeline.project))
    if role in ('writer','reviewer'):
        tools.register(LabEvidence(pipeline.project))
    if role == 'writer' and not getattr(pipeline,'report_collaboration',False):
        from .lab_figures import LabFigures
        tools.register(LabFigures(pipeline.project))
    if role == 'executor':
        from .lab_harness import LabHarness
        tools.register(LabFiles())
        tools.register(LabPython(pipeline, task_id))
        from .lab_local_model import LabLocalModel
        tools.register(LabHarness(pipeline, task_id, reference_only=True))
        tools.register(LabLocalModel(pipeline, task_id))
        from .lab_mcp import LabMCP, LabPubMed
        tools.register(LabMCP(pipeline, task_id))
        tools.register(LabPubMed(pipeline, task_id))
    return tools
