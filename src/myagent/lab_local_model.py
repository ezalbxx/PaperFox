"""Our typed model deployment skill: discover/start/query/benchmark/stop."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from .jobs import atomic_json
from .lab_project import task_generation
from .lab_environment import get_inventory, probe_interpreter
from .tools.base import ToolResult

BASE='http://127.0.0.1:8871'


def request(route, data=None, timeout=60, *, port=8871):
    raw=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+route,data=raw,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.load(r)


class LabLocalModel:
    name='lab_local_model'
    description=('Our local deployment skill. discover/status/start/chat/benchmark/stop. start selects model_index from '
                 'discovered local models and interpreter_id from discovered conda environments (needs torch/transformers). '
                 'CPU service on localhost:8871 or CUDA on 8872 (device=cuda), OpenAI-compatible endpoint, no download or shell. '
                 'benchmark measures real prefill/decode for prompt and longer context; saves JSON. '
                 'Not a replacement for cloud coding models. Inputs: prompt, max_tokens, interpreter_id, model_index.')
    parameters={'type':'object','properties':{'operation':{'type':'string','enum':['discover','status','start','chat','benchmark','stop']},
                'interpreter_id':{'type':'string'},'model_index':{'type':'integer'},'prompt':{'type':'string'},'max_tokens':{'type':'integer'},
                'device':{'type':'string','enum':['cpu','cuda']}},'required':['operation']}

    def __init__(self,pipeline,task_id):
        self.pipeline,self.project,self.task_id=pipeline,pipeline.project,task_id

    def run(self,args,ctx):
        op=args['operation'];p=self.project
        receipt_id=None
        device=args.get('device',p.data.get('local_model_service',{}).get('device','cpu'))
        port=8872 if device=='cuda' else 8871
        def query(route,data=None,timeout=60):
            return request(route,data,timeout,port=port)
        directory=p.root/'outputs/local-model';directory.mkdir(parents=True,exist_ok=True)
        if op=='discover':
            value=get_inventory(p,refresh=True)
        elif op=='start':
            inventory=get_inventory(p)
            chosen=Path(inventory['local_models'][int(args.get('model_index',0))]).parent
            interpreter=probe_interpreter(args['interpreter_id'],inventory)
            if not all(interpreter['packages'].get(n) for n in ('torch','transformers')):
                raise ValueError('所选环境需要已有torch和transformers')
            try:
                health=query('/health',timeout=2)
                if Path(health['model_path'])!=chosen:
                    raise ValueError('端口已有其他模型，请先停止或使用现有模型')
                value=health
            except (OSError,TimeoutError):
                worker=Path(__file__).with_name('lab_model_worker.py')
                flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
                with (directory/'server.stdout.log').open('wb') as stdout, (directory/'server.stderr.log').open('wb') as stderr:
                    proc=subprocess.Popen([interpreter['path'],'-X','utf8',str(worker),'--model',str(chosen),
                                           '--device',device,'--port',str(port),
                                           '--evidence-dir',str(directory/'http')],
                                          stdout=stdout,stderr=stderr,cwd=p.root,**flags)
                atomic_json(directory/'server.json',{'pid':proc.pid,'model':str(chosen),'python':interpreter['path'],
                                                    'device':device,'endpoint':f'http://127.0.0.1:{port}/v1'})
                deadline=time.monotonic()+90
                while True:
                    self.pipeline.check_limits()
                    try:
                        value=query('/health',timeout=1);break
                    except OSError:
                        if proc.poll() is not None or time.monotonic()>deadline:
                            raise ValueError('模型服务启动失败：'+(directory/'server.stderr.log').read_text(encoding='utf-8',errors='replace')[-4000:])
                        time.sleep(.4)
            p.data['local_model_service']={'device':device,'endpoint':f'http://127.0.0.1:{port}/v1',
                                         'context_window':value.get('context_window',32000),'model':'local-qwen'}
            p.save()
        elif op=='status':
            value=query('/health',timeout=3)
        elif op=='stop':
            value=query('/shutdown',{})
        elif op in ('chat','benchmark'):
            prompt=args.get('prompt','The capital of France is')
            texts=[prompt] if op=='chat' else [prompt,('Archived neutral words: alpha beta gamma delta. '*64)+prompt,
                                                        ('Archived neutral words: alpha beta gamma delta. '*256)+prompt]
            values=[]
            groups=[]
            for text in texts:
                for threads in ([1,6] if op=='benchmark' and device=='cpu' else [None]):
                    body={'model':'local-qwen','messages':[{'role':'user','content':text}],
                          'max_tokens':int(args.get('max_tokens',128 if op=='benchmark' else 256))}
                    if threads is not None:
                        body['threads']=threads
                    if op=='benchmark':
                        # Discard one warmup for each condition, retain it separately.
                        warmup=query('/v1/chat/completions',body)
                    measured=[]
                    for _ in range(3 if op=='benchmark' else 1):
                        self.pipeline.check_limits()
                        response=query('/v1/chat/completions',body)
                        values.append(response);measured.append(response)
                    if op=='benchmark':
                        import statistics
                        groups.append({'prompt':text,'threads':threads,'warmup':warmup,
                                       'trials':measured,'n':3,
                                       'mean_prefill_tok_s':statistics.mean(r['timings']['prefill_tok_s'] for r in measured),
                                       'mean_decode_tok_s':statistics.mean(r['timings']['decode_tok_s'] for r in measured),
                                       'prefill_range':[min(r['timings']['prefill_tok_s'] for r in measured),max(r['timings']['prefill_tok_s'] for r in measured)],
                                       'decode_range':[min(r['timings']['decode_tok_s'] for r in measured),max(r['timings']['decode_tok_s'] for r in measured)],
                                       'actual_prompt_tokens':measured[0]['usage']['prompt_tokens'],
                                       'finish_reasons':[r['choices'][0]['finish_reason'] for r in measured]})
            value={'responses':values,'groups':groups,
                   'comparison':f'same checkpoint and device={device}; three actual input lengths'+('; CPU threads 1 vs 6' if device=='cpu' else '; GPU threads not used as an experimental variable')+'; one warmup + three measured trials per condition; no cross-request prompt cache' if op=='benchmark' else ''}
            receipt={'id':uuid4().hex[:12],'task_id':self.task_id,'adapter':'local-model','state':'completed',
                     'plan_generation':task_generation(p,self.task_id),
                     'path':'outputs/local-model','returncode':0,'output':value,'device':device}
            p.data['receipts'].append(receipt);p.save()
            receipt_id=receipt['id']
        else:
            raise ValueError('未知模型操作')
        path=directory/(op+'-'+uuid4().hex[:8]+'.json');atomic_json(path,value)
        return ToolResult(output=json.dumps({'result':value,'artifact':str(path.relative_to(p.root)),
                                            **({'receipt_id':receipt_id} if receipt_id else {})},ensure_ascii=False))
