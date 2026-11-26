"""Our DSH experiment adapter. DSH is the study subject, not our implementation."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from .jobs import atomic_json
from .lab_environment import fixed_run
from .lab_project import digest, current_receipts, task_generation
from .tools.base import ToolResult, resolve_workspace_path


def installation():
    path = Path.home() / 'AppData/Roaming/npm/node_modules/@deepseek-ai/dsh'
    if not path.is_dir():
        raise ValueError('本机未发现DSH安装；需要先安装实验对象')
    return path


def reference_root():
    root=Path(__file__).resolve().parents[2]/'references/dsh'
    if not (root/'manifest.json').is_file():
        raise ValueError('项目内DSH参考快照缺失；不自动改读全局安装目录')
    return root


def source_file(raw):
    return resolve_workspace_path(reference_root(), raw)


def source_operation(args):
    root = reference_root()
    op = args['operation']
    if op == 'inventory':
        packages = root / 'node_modules/@deepseek-ai'
        return {'version': json.loads((root/'package.json').read_text())['version'],
                'root': str(root), 'packages': [p.name for p in packages.iterdir() if p.is_dir()],
                'source_note': '项目内只读参考快照，不是本Agent的运行依赖；发行包lib不是上游TS源文件，引用路径、行号与SHA'}
    if op == 'read':
        path = source_file(args['path'])
        lines = path.read_text(encoding='utf-8').splitlines()
        start = max(1, int(args.get('start_line', 1)))
        end = min(len(lines), int(args.get('end_line', start+100)))
        return {'path': args['path'], 'sha256': digest(path), 'lines': len(lines),
                'excerpt': '\n'.join(f'{i+1}: {lines[i]}' for i in range(start-1, min(end, start+220)))}
    if op == 'search':
        folder = source_file(args.get('path', 'node_modules/@deepseek-ai'))
        query = str(args['query']).lower()
        hits = []
        for p in ([folder] if folder.is_file() else folder.rglob('*')):
            if p.is_file() and p.suffix in ('.js', '.md', '.yml') and p.stat().st_size < 1_500_000:
                for i, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    if query in line.lower():
                        hits.append({'path': str(p.relative_to(root)), 'line': i, 'text': line[:400]})
                        if len(hits) >= 35:
                            return {'hits': hits, 'limited': True}
        return {'hits': hits}
    raise ValueError('operation必须为inventory/search/read/ask/install_skill；收到非枚举参数，可能混入DSML。下一轮只发一个工具调用，并使用普通JSON独立填写operation/path/query。')


class LabHarness:
    name = 'lab_harness'
    description = ('Our DSH experiment skill. inventory/search/read installed DSH source (with line references); '
                   'ask runs an isolated persisted DSH headless experiment, captures stdout and ORIGINAL sessions. '
                   'ask takes prompt. interview takes prompts (ordered questions, up to 8) in ONE real persistent session; '
                   'study_id is returned and can resume/extend the SAME prompt sequence after restart. Never merge separate logs. '
                   'timeout_s <=240 for ask, <=1800 for interview; optional local_model=true, instruction_line, include_mcp=true. '
                   'instruction_line explicitly replaces the extra AGENTS rule; empty string resets it. Without the field, keep the current study AGENTS.md. '
                   'install_skill installs the existing course grill-me and grilling ONLY into this project work/harness-home/skills. '
                   'ask disables default skill roots and uses ONLY that study skills directory; existing global ~/.dsh/skills or ~/.agents/skills do not establish this study baseline. '
                   'analyze_session(path) indexes a saved original DSH JSONL once: exact system/tools, turn/tool/usage counts, paired calls, error excerpts with source lines. '
                   'compare_sessions(path, other_path) saves exact system/instruction/catalog diffs and observed tool sequences for a before/after experiment. '
                   'No shell or command input. Source operations: path/query/start_line/end_line. '
                   'Do not claim an interview or usage without the saved artifacts.')
    parameters = {'type': 'object', 'properties': {'operation': {'type': 'string', 'enum': ['inventory','search','read','ask','interview','install_skill','analyze_session','compare_sessions']},
                  'prompt': {'type': 'string','description':'ask必填：发送给DSH的自然语言任务；不是本产品对话。'}, 'label': {'type': 'string'}, 'timeout_s': {'type': 'integer'},
                  'prompts': {'type':'array','items':{'type':'string'},'minItems':1,'maxItems':8}, 'study_id': {'type':'string'},
                  'path': {'type': 'string','description':'read/search为DSH安装目录内源码路径；analyze_session为项目内原始JSONL路径；ask不使用path。'}, 'query': {'type': 'string'}, 'start_line': {'type': 'integer'},
                  'end_line': {'type': 'integer'}, 'other_path': {'type':'string'}, 'local_model': {'type': 'boolean'}, 'include_mcp': {'type':'boolean'}, 'instruction_line': {'type':'string'}}, 'required':['operation']}

    def __init__(self, pipeline, task_id, *, reference_only=False):
        self.pipeline, self.project, self.task_id = pipeline, pipeline.project, task_id
        self.reference_only=reference_only
        import copy
        self.parameters=copy.deepcopy(type(self).parameters)
        if reference_only:
            self.parameters['properties']['operation']['enum']=['inventory','search','read','analyze_session','compare_sessions']
            self.description=('Read the project-local DSH REFERENCE snapshot or analyze already saved original sessions. '
                'Available: inventory/search/read/analyze_session/compare_sessions. This is NOT an execution dependency. '
                'No ask/interview/install_skill and no DSH runtime APIs in the dedicated PDF pipeline. '
                'Source paths are relative to references/dsh; query/start_line/end_line; saved sessions use project paths.')
            return
        task=next((t for t in self.project.data['tasks'] if t['id']==task_id),{})
        has_run=any(r.get('adapter')=='dsh' and (task.get('capability')!='mcp' or r['task_id']==task_id)
                    for r in current_receipts(self.project))
        if task.get('capability') in ('harness','mcp') and not has_run:
            self.parameters['properties']['operation']['enum']=['inventory','ask','interview','install_skill']
            self.description+=' This task needs a DSH run: use ask FIRST. MCP integration tasks need their own run (MCP is injected automatically); later session-analysis tasks reuse existing project sessions.'

    def run(self, args, ctx):
        if args['operation'] not in self.parameters['properties']['operation']['enum']:
            if self.reference_only:
                raise ValueError('专用PDF管线只允许项目内DSH参考源码与已有会话分析，不调用DSH运行接口。')
            raise ValueError('当前任务先用ask实际采访/执行DSH，得到回执后再搜索源码或分析会话；不要用源码搜索代替采访。')
        if args['operation'] == 'analyze_session':
            return ToolResult(output=json.dumps(analyze_session(self.project,args['path']),ensure_ascii=False))
        if args['operation'] == 'compare_sessions':
            return ToolResult(output=json.dumps(compare_sessions(self.project,args['path'],args['other_path']),ensure_ascii=False))
        if args['operation'] == 'install_skill':
            home = self.project.root/'work/harness-home'
            sources = []
            mirror=Path('D:/workspace/ai_exp1_harness/grill-src')
            provenance={'method':'existing course skill files','upstream':None,'commit':None}
            if (mirror/'.git').is_dir():
                clone=self.project.root/'work/course-skill-source'
                if not clone.exists():
                    result=fixed_run(['git','clone','--local','--no-checkout',str(mirror),str(clone)],timeout=30)
                    if result.returncode:
                        raise ValueError(result.stderr)
                sparse=fixed_run(['git','-C',str(clone),'sparse-checkout','set','--cone',
                                  'skills/productivity/grill-me','skills/productivity/grilling'],timeout=30)
                if sparse.returncode:
                    raise ValueError(sparse.stderr)
                checkout=fixed_run(['git','-C',str(clone),'checkout','HEAD'],timeout=30)
                if checkout.returncode:
                    raise ValueError(checkout.stderr)
                commit=fixed_run(['git','-C',str(clone),'rev-parse','HEAD']).stdout.strip()
                provenance={'method':'fixed skill adapter git clone --local of existing course mirror',
                            'upstream':fixed_run(['git','-C',str(mirror),'remote','get-url','origin']).stdout.strip(),
                            'commit':commit,'mirror':str(mirror),'clone':str(clone)}
            for name in ('grill-me', 'grilling'):
                source = clone/'skills/productivity'/name if provenance['commit'] else Path.home()/'.dsh/skills'/name
                if not (source/'SKILL.md').is_file():
                    raise ValueError('未发现课程要求的原始'+name+'。请提供它的材料；不伪造原作者版本')
                target = home/'skills'/name
                shutil.copytree(source,target,dirs_exist_ok=True)
                sources.append({'original':str(source),'installed':str(target),
                                'sha256':digest(target/'SKILL.md')})
            file = self.project.root/'outputs/harness-skill-install.json'
            atomic_json(file,{'sources':sources,'provenance':provenance,'notice':'课程要求安装的开源实验对象，原作者版本/哈希已记录；不是原创兼容示例，也未移植为本产品技能'})
            return ToolResult(output=json.dumps({'installed':sources,'provenance':provenance,'artifact':str(file.relative_to(self.project.root))},ensure_ascii=False))
        if args['operation'] not in ('ask','interview'):
            value=source_operation(args)
            if args['operation']=='inventory' and not self.reference_only:
                home=self.project.root/'work/harness-home'
                value['study']={'home':str(home),'session_root':str(home/'sessions'),
                                'skill_roots':[str(home/'skills')],'include_default_skill_roots':False,
                                'invocation_cwd':str(installation()),
                                'notice':'ask的实际隔离配置。全局用户目录已有skill不代表本实验已安装；安装前后以本目录及真实会话catalog为准。'}
            if args['operation']=='read':
                artifact=self.project.root/'outputs/harness-source'/(uuid4().hex[:10]+'.json')
                artifact.parent.mkdir(parents=True,exist_ok=True)
                atomic_json(artifact,value)
                value['artifact']=str(artifact.relative_to(self.project.root))
            return ToolResult(output=json.dumps(value, ensure_ascii=False))
        interview = args['operation'] == 'interview'
        if interview and (not isinstance(args.get('prompts'),list) or not 1<=len(args['prompts'])<=8 or any(not isinstance(q,str) or not q.strip() for q in args['prompts'])):
            raise ValueError('interview需要1—8个按顺序发送的非空prompts；在同一真实会话中连续进行')
        if not interview and not args.get('prompt'):
            raise ValueError('ask必须提供prompt，例如{"operation":"ask","prompt":"请读取package.json并解释版本"}。要分析已有会话，使用analyze_session(path)，不使用ask(path)。')
        root, project = installation(), self.project
        self.pipeline.check_limits()
        label = uuid4().hex[:10]
        directory = project.root/'outputs/harness'/label
        directory.mkdir(parents=True)
        home = project.root/'work/harness-home'
        workspace = project.root/'work/harness-workspace'
        workspace.mkdir(parents=True, exist_ok=True)
        home.mkdir(parents=True, exist_ok=True)
        study = None
        if interview:
            studies=project.data.setdefault('study_sessions',{})
            study=studies.get(args.get('study_id')) if args.get('study_id') else None
            if args.get('study_id') and study is None:
                raise ValueError('study_id必须来自本项目已有interview回执')
            if study and args['prompts'][:len(study['prompts'])] != study['prompts']:
                raise ValueError('续接必须保留原问题顺序，可在末尾追加问题；更换问题请新建interview')
            study_id=args.get('study_id') or uuid4().hex[:12]
            progress_dir=home/'interviews';progress_dir.mkdir(exist_ok=True)
            packet={'session_id':study['session_id'] if study else 'session-'+str(uuid4()),
                    'prompts':args['prompts'],'resume':bool(study),
                    'progress_path':str(progress_dir/(study_id+'.json'))}
            studies[study_id]={'session_id':packet['session_id'],'prompts':args['prompts'],'receipt_id':label}
            project.save()
            atomic_json(directory/'interview-packet.json',packet)
        # A narrow fixed experiment adapter: source reading, no shell tool in DSH.
        policy = ('只读实验对象源码。优先使用文件读取/搜索工具，回答引用文件和函数行号。'
                  '不要执行shell，不改源码。发行包源码位于 '+str(root)+'.\n')
        if args.get('instruction_line'):
            policy += args['instruction_line'] + '\n'
        elif 'instruction_line' not in args and (home/'AGENTS.md').is_file():
            policy=(home/'AGENTS.md').read_text(encoding='utf-8')
        (workspace/'AGENTS.md').write_text(policy, encoding='utf-8')
        (home/'AGENTS.md').write_text(policy, encoding='utf-8')
        (directory/'instructions.md').write_text(policy,encoding='utf-8')
        import yaml
        local = bool(args.get('local_model'))
        service = project.data.get('local_model_service', {})
        config = self.pipeline.config
        patch = [
            {'id':'agent-default-model','config':{'provider':'myagent-study','model': 'local-qwen' if local else config.model}},
            {'id':'llm-pi-ai','config':{'providers':{'myagent-study':{
                'apiKeyEnv':'MYAGENT_STUDY_KEY', 'api':'openai-completions',
                'baseURL':service.get('endpoint','http://127.0.0.1:8871/v1') if local else config.base_url,
                'models':[{'id':'local-qwen' if local else config.model,'name':'Study model',
                           'contextWindow':service.get('context_window',32000) if local else 32000,
                           'maxTokens':512 if local else 2048,'input':['text']}]}}}},
            {'id':'tool-bash','disabled':True}, {'id':'tool-pwsh','disabled':True},
            {'id':'skill-filesystem','config':{'includeDefaultRoots':False,'customSkillDirs':[str(home/'skills')]}},
            {'id':'session-persistence-jsonl','config':{'root':str(home/'sessions'),'compression':'none'}},
        ]
        if local:
            # Preset tools are mounted later, outside the host overlay tree.
            # Disabling their ids in a host patch does not change that catalog.
            # Author a small composition through the subject's public preset seam.
            preset_dir=home/'.agent-presets/myagent-local-study'
            preset_dir.mkdir(parents=True,exist_ok=True)
            preset=[
                {'id':'persona','name':'@deepseek-ai/dsh-persona','config':{
                    'text':'You are a study assistant. Use the filesystem tools for the requested task. Give the measured result concisely.',
                    'complete':True,'includeRuntimeContext':False}},
                {'id':'agent-instructions','name':'@deepseek-ai/dsh-agent-instructions'},
                {'id':'tool-fs','name':'@deepseek-ai/dsh-tool-fs'},
            ]
            (preset_dir/'agent.cordis.yml').write_text(yaml.safe_dump(preset,allow_unicode=True),encoding='utf-8')
            patch.append({'id':'agent-presets','config':{'default':'myagent-local-study'}})
        if interview:
            patch.extend([{'id':'headless-runner','disabled':True},
                {'insert':[{'id':'myagent-study-interview','name':Path(__file__).with_name('lab_dsh_interview.mjs').as_uri()}]}])
        mcp_server = None
        if args.get('include_mcp') or any(t['id']==self.task_id and t.get('capability')=='mcp' for t in project.data['tasks']):
            import threading
            from http.server import ThreadingHTTPServer
            from .lab_mcp import Handler
            mcp_server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
            mcp_server.events = []
            threading.Thread(target=mcp_server.serve_forever,daemon=True).start()
            patch.append({'insert':[{'id':'myagent-labstats-mcp','name':Path(__file__).with_name('lab_dsh_mcp.mjs').as_uri()}]})
        patch_path = directory/'profile.patch.yml'
        patch_path.write_text(yaml.safe_dump(patch, allow_unicode=True), encoding='utf-8')
        prompt = '\n\n'.join(args['prompts']) if interview else args['prompt']
        (directory/'prompt.txt').write_text(prompt, encoding='utf-8')
        env = os.environ | {'DSH_HOME':str(home),'MYAGENT_STUDY_KEY':'local' if local else config.api_key,
                            'DSH_TELEMETRY_DISABLED':'1','PYTHONUTF8':'1'}
        if mcp_server:
            env['MYAGENT_MCP_ENDPOINT'] = f'http://127.0.0.1:{mcp_server.server_port}/mcp'
        if interview:
            env.update(MYAGENT_INTERVIEW_PACKET=str(directory/'interview-packet.json'),MYAGENT_DSH_ENTRY=str(root/'lib/bin.js'))
        node = shutil.which('node')
        command = [node, str(root/'lib/bin.js'), '--profile','headless','--patch',str(patch_path),prompt]
        started = time.monotonic()
        previous = {str(f):f.stat().st_mtime_ns for f in (home/'sessions').rglob('*') if f.is_file()}
        import subprocess
        try:
            from .tools.base import kill_process_tree
            flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=root, env=env, **flags)
            timeout = min(1800 if interview else 240, max(1, int(args.get('timeout_s',900 if interview else 180))))
            stopped = ''
            while True:
                if self.pipeline.cancel.is_set():
                    stopped = '用户暂停DSH实验；保存已生成会话'
                elif ctx and ctx.deadline is not None and time.monotonic()>=ctx.deadline:
                    stopped = '本次运行时间额度已到；保存已生成会话'
                elif time.monotonic()-started >= timeout:
                    stopped = 'DSH实验达到超时；保存已生成会话'
                if stopped:
                    kill_process_tree(proc.pid)
                try:
                    out, err = proc.communicate(timeout=.2)
                    stdout, stderr = out.decode('utf-8',errors='replace'), err.decode('utf-8',errors='replace')
                    code = proc.returncode if not stopped else -1
                    stderr += '\n'+stopped if stopped else ''
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if mcp_server:
                mcp_server.shutdown();mcp_server.server_close()
                atomic_json(directory/'mcp-protocol.json',{'events':mcp_server.events})
        # Keys are process environment only; strip exact value if the subject echoes it.
        for key in (config.api_key,):
            if key:
                stdout, stderr = stdout.replace(key,'[KEY_REDACTED]'), stderr.replace(key,'[KEY_REDACTED]')
        (directory/'stdout.txt').write_text(stdout, encoding='utf-8')
        (directory/'stderr.txt').write_text(stderr, encoding='utf-8')
        copied = []
        usage = {'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'prompt_cache_hit_tokens':0}
        calls = 0
        seen_lines=study.get('session_lines',0) if study and interview else 0
        for path in (home/'sessions').rglob('*'):
            if path.is_file() and previous.get(str(path)) != path.stat().st_mtime_ns:
                target = directory/'original-sessions'/path.relative_to(home/'sessions')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path,target)
                copied.append(str(target.relative_to(project.root)))
                if path.suffix == '.jsonl':
                    # A resumed session contains past usage. Charge only the appended
                    # original events, while preserving the complete new snapshot.
                    for line in path.read_text(encoding='utf-8').splitlines()[seen_lines:]:
                        event = json.loads(line)
                        chunk = event.get('data',{}).get('chunk',{})
                        if event.get('type') == 'assistant/chunk' and chunk.get('type') == 'usage':
                            measured = chunk['usage'];calls += 1
                            hits=measured.get('cacheReadTokens',0)
                            usage['prompt_tokens'] += measured.get('inputTokens',0)+hits+measured.get('cacheWriteTokens',0)
                            usage['prompt_cache_hit_tokens'] += hits
                            usage['completion_tokens'] += measured.get('outputTokens',0)
        usage['total_tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
        cost = 0 if local else config.cost_of(usage)
        if self.pipeline.logger:
            self.pipeline.logger.log('model_usage', purpose='nested_harness', usage=usage, cost=cost,
                                     calls=calls, sources=copied, model='local-qwen' if local else config.model)
            project.data['totals']['nested_model_calls'] = project.data['totals'].get('nested_model_calls', 0) + calls
        receipt = {'id':label,'task_id':self.task_id,'adapter':'dsh','path':str((directory/'prompt.txt').relative_to(project.root)),
                   'plan_generation':task_generation(project,self.task_id),
                   'state':'completed' if code==0 else 'failed','returncode':code,'elapsed_seconds':time.monotonic()-started,
                   'output':stdout[-14000:],'error':stderr[-3000:],'artifacts':copied,
                   'model': 'local-qwen' if local else config.model,
                   'instructions_path':str((directory/'instructions.md').relative_to(project.root)),
                   'instructions_sha256':digest(directory/'instructions.md'),
                   'usage':usage,'nested_calls':calls,'cost_usd':cost,
                   'usage_start_line':seen_lines if interview else 0,
                   'usage_notice':'嵌套主调用用量按原始会话usage去重纳入主项目费用；标题生成另有未知用量，不冒称精确账单'}
        receipt['session_indexes']=[]
        for file in copied:
            if file.endswith('.jsonl'):
                index=analyze_session(project,file)
                receipt['session_indexes'].append({k:index[k] for k in ('artifact','turn_count','tool_call_count','max_input','errors')})
                if not (directory/'session.jsonl').exists():
                    try:os.link(project.file(file),directory/'session.jsonl')
                    except OSError:shutil.copy2(project.file(file),directory/'session.jsonl')
                    receipt['canonical_session']=str((directory/'session.jsonl').relative_to(project.root))
        if interview:
            receipt.update(study_id=study_id,session_id=packet['session_id'],questions=len(args['prompts']))
            if receipt.get('canonical_session'):
                studies[study_id]['session_lines']=len(project.file(receipt['canonical_session']).read_text(encoding='utf-8').splitlines())
            progress_path=Path(packet['progress_path'])
            if progress_path.is_file():
                shutil.copy2(progress_path,directory/'interview-progress.json')
                receipt['interview_progress']=str((directory/'interview-progress.json').relative_to(project.root))
        atomic_json(directory/'receipt.json',receipt)
        project.data['receipts'].append(receipt)
        project.save()
        self.parameters=type(self).parameters
        receipt['files']=[str(p.relative_to(project.root)) for p in directory.rglob('*') if p.is_file()]
        return ToolResult(0 if code==0 else -1,json.dumps(receipt,ensure_ascii=False),stderr[-1000:])


def compare_sessions(project, before, after):
    """A deterministic evidence operation; it does not judge the model's quality."""
    import difflib
    from collections import Counter
    def load(path):
        source=project.file(path)
        rows=[(i,json.loads(line)) for i,line in enumerate(source.read_text(encoding='utf-8').splitlines(),1) if line.strip()]
        def text(data):
            value=data.get('message',data).get('content',[])
            return value if isinstance(value,str) else '\n'.join(b.get('text','') for b in value if b.get('type')=='text')
        messages=[{'line':i,'seq':e.get('seq'),'id':e['data'].get('id'),
                   'kind':e['data'].get('source',{}).get('kind'),'text':text(e['data'])}
                  for i,e in rows if e['type']=='user/message']
        systems=[{'line':i,'text':e['data'].get('header',{}).get('system','')}
                 for i,e in rows if e['type']=='request/header']
        calls=[{'line':i,**e['data']} for i,e in rows if e['type']=='tool/call']
        return {'path':path,'sha256':digest(source),'user_messages':messages,'systems':systems,
                'assistant_messages':[{'line':i,'id':e['data'].get('id'),'text':text(e['data'])}
                                      for i,e in rows if e['type']=='assistant/message'],
                'calls':calls,'tool_counts':dict(Counter(c.get('name') for c in calls)),
                'turn_ends':[{'line':i,**e['data']} for i,e in rows if e['type']=='turn/end']}
    left,right=load(before),load(after)
    def diff(a,b):
        return '\n'.join(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile=before,tofile=after,lineterm=''))
    def messages(side,kind):
        return '\n'.join(m['text'] for m in side['user_messages'] if m['kind']==kind)
    value={'before':left,'after':right,
           'same_user_prompt':messages(left,'user')==messages(right,'user'),
           'system_diff':diff(left['systems'][0]['text'] if left['systems'] else '',right['systems'][0]['text'] if right['systems'] else ''),
           'instruction_diff':diff(messages(left,'agent-instructions'),messages(right,'agent-instructions')),
           'skill_catalog_diff':diff(messages(left,'skill-catalog'),messages(right,'skill-catalog')),
           'notice':'逐字差异及实际调用记录；没有观测到行为差异并不证明规则无效，不将相关性写成因果。'}
    target=project.root/'outputs/harness-comparison'/f'{uuid4().hex[:10]}.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(target,value)
    return {'artifact':str(target.relative_to(project.root)),
            'same_user_prompt':value['same_user_prompt'],
            **{k:value[k] for k in ('system_diff','instruction_diff','skill_catalog_diff')},
            'before_tool_counts':left['tool_counts'],'after_tool_counts':right['tool_counts'],
            'notice':value['notice']}


def analyze_session(project, path):
    """Index original events without expanding packed chunks into invented entries."""
    from collections import Counter
    source=project.file(path)
    rows=[(i,json.loads(line)) for i,line in enumerate(source.read_text(encoding='utf-8').splitlines(),1) if line.strip()]
    folder=project.root/'outputs/harness-analysis'/digest(source)[:12]
    folder.mkdir(parents=True,exist_ok=True)
    headers=[{'line':i,**r['data']['header']} for i,r in rows if r['type']=='request/header']
    calls=[{'line':i,**r['data']} for i,r in rows if r['type']=='tool/call']
    results=[{'line':i,**r['data']} for i,r in rows if r['type']=='tool/result']
    assistants=[{'line':i,**r['data']} for i,r in rows if r['type']=='assistant/message']
    usage=[{'line':i,'turn':r['data'].get('turn'),'step':r['data'].get('step'),
            **r['data']['chunk']['usage'],
            'context_input_tokens':sum(r['data']['chunk']['usage'].get(k,0) for k in ('inputTokens','cacheReadTokens','cacheWriteTokens'))} for i,r in rows
           if r['type']=='assistant/chunk' and r['data'].get('chunk',{}).get('type')=='usage']
    paired=[]
    for call in calls:
        matches=[r for r in results if r.get('message',{}).get('source',{}).get('callId')==call['callId']]
        paired.append({'call':call,'results':matches})
    files={}
    for name,value in [('headers',headers),('tool-pairs',paired),('assistant-messages',assistants),('usage',usage)]:
        dest=folder/(name+'.json');atomic_json(dest,value);files[name]=str(dest.relative_to(project.root))
    errors=[{'line':r['line'],'excerpt':json.dumps(r,ensure_ascii=False)[:1400]} for r in results
            if any(b.get('isError') for b in r.get('message',{}).get('content',[]))]
    summary={'source':path,'source_sha256':digest(source),'physical_lines':len(rows),
             'event_counts':dict(Counter(r['type'] for _,r in rows)),
             'turn_count':sum(r['type']=='turn/start' for _,r in rows),'tool_call_count':len(calls),
             'assistant_count':len(assistants),'usage':usage,
             'max_input':max(usage,key=lambda u:u.get('context_input_tokens',0),default=None),
             'tools':[t.get('name') for t in headers[0].get('tools',[])] if headers else [],
             'header_lines':[h['line'] for h in headers],
             'calls':[{'line':c['line'],'callId':c['callId'],'name':c['name'],'arguments':c.get('arguments')} for c in calls],
             'errors':errors,'files':files,
             'notice':'物理JSONL行号；packed chunks不是独立调用。原始文件不改写。usage取assistant/chunk，避免与assistant/message重复计数。'}
    atomic_json(folder/'index.json',summary)
    summary['artifact']=str((folder/'index.json').relative_to(project.root))
    return summary


def reconcile_usage(project, config, logger):
    """Correct the earlier adapter's omitted cache-read counts, preserving raw logs."""
    for receipt in project.data['receipts']:
        if receipt.get('adapter')!='dsh' or 'prompt_cache_hit_tokens' in receipt.get('usage',{}):
            continue
        previous=receipt.get('usage',{})
        usage={'prompt_tokens':0,'completion_tokens':0,'prompt_cache_hit_tokens':0}
        for raw in receipt.get('artifacts',[]):
            if not raw.endswith('.jsonl'):
                continue
            for line in project.file(raw).read_text(encoding='utf-8').splitlines():
                event=json.loads(line);chunk=event.get('data',{}).get('chunk',{})
                if event['type']=='assistant/chunk' and chunk.get('type')=='usage':
                    u=chunk['usage'];hits=u.get('cacheReadTokens',0)
                    usage['prompt_tokens']+=u.get('inputTokens',0)+hits+u.get('cacheWriteTokens',0)
                    usage['completion_tokens']+=u.get('outputTokens',0)
                    usage['prompt_cache_hit_tokens']+=hits
        usage['total_tokens']=usage['prompt_tokens']+usage['completion_tokens']
        cost=0 if receipt.get('model')=='local-qwen' else config.cost_of(usage)
        cost_delta=cost-receipt.get('cost_usd',0)
        token_delta=usage['total_tokens']-previous.get('total_tokens',0)
        receipt.update(usage=usage,cost_usd=cost)
        project.data['totals']['cost_usd']+=cost_delta
        project.data['totals']['tokens']+=token_delta
        logger.log('usage_reconciliation',receipt_id=receipt['id'],previous=previous,usage=usage,
                   cost_delta_usd=cost_delta,token_delta=token_delta,
                   notice='pi-ai inputTokens为未缓存输入；补计cacheRead/cacheWrite，原始运行流与回执文件保持原样。标题仍有未知用量。')
        project.save()
