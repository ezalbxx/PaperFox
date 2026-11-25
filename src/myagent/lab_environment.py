"""Fixed environment operations, never a model-provided command launcher."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROBE = '''import json,sys,importlib.util,importlib.metadata
names=['numpy','scipy','scikit-learn','matplotlib','torch','transformers','PyMuPDF','reportlab']
packages={}
for n in names:
 try: packages[n]=importlib.metadata.version(n)
 except importlib.metadata.PackageNotFoundError: packages[n]=None
print(json.dumps({'python':sys.version.split()[0],'interpreter':sys.executable,'packages':packages}))
'''


def fixed_run(argv, *, timeout=12, cwd=None, env=None, input=None):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    return subprocess.run(argv, input=input, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, cwd=cwd, env=env, **flags)


def discover():
    result = {'interpreters': [{'id': 'application', 'path': sys.executable}], 'gpus': [], 'adapters': {}}
    roots = [Path('D:/conda_envs'), Path('D:/Anaconda/envs'), Path.home() / 'miniconda3/envs',
             Path.home() / 'anaconda3/envs']
    for root in roots:
        for p in sorted(root.glob('*/python.exe' if os.name == 'nt' else '*/bin/python')):
            result['interpreters'].append({'id': 'conda:' + p.parent.name, 'path': str(p)})
    gpu = shutil.which('nvidia-smi')
    if gpu:
        try:
            r = fixed_run([gpu, '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'])
            for line in r.stdout.splitlines():
                name, total, free = [p.strip() for p in line.split(',')]
                result['gpus'].append({'name': name, 'total_mib': int(total), 'free_mib': int(free)})
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            result['gpu_error'] = str(exc)
    dsh = Path.home() / 'AppData/Roaming/npm/node_modules/@deepseek-ai/dsh'
    result['adapters']['dsh'] = {'available': dsh.is_dir(), 'root': str(dsh)}
    result['adapters']['A100'] = {'configured': (Path.home() / '.ssh/config').is_file(),
                                'status': 'not_probed', 'notice': '按需使用ssh A100探测，不在每次开页建立远程连接'}
    result['local_models'] = discover_local_models()
    return result


def discover_local_models(roots=None):
    """Inspect known model locations, not the whole disk or embedding checkpoints."""
    roots=roots or [Path('D:/LLM'),Path('D:/huggingface_models/hub'),
                    Path('D:/hf_cache'),Path('D:/huggingface_cache')]
    found=[]
    for root in roots:
        for pattern in ('*/config.json','models--*/snapshots/*/config.json'):
            for path in sorted(root.glob(pattern)):
                config=json.loads(path.read_text(encoding='utf-8'))
                if any('ForCausalLM' in a for a in config.get('architectures',[])):
                    if str(path) not in found:found.append(str(path))
    return found


def probe_interpreter(identifier, inventory):
    record = next((r for r in inventory['interpreters'] if r['id'] == identifier), None)
    if not record:
        raise ValueError('请从已发现的解释器中选择')
    r = fixed_run([record['path'], '-X', 'utf8', '-c', PROBE], timeout=25)
    if r.returncode:
        raise ValueError(r.stderr[-2000:])
    return {**record, **json.loads(r.stdout)}


def probe_a100():
    # Existing SSH alias retains its network-specific configuration.
    command = '/root/miniconda3/envs/countgd_lora/bin/python -c ' + __import__('shlex').quote(
        "import json,sys,subprocess; print(json.dumps({'python':sys.version,'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.free','--format=csv,noheader'],text=True)}))")
    try:
        r = fixed_run(['ssh', 'A100', command], timeout=25)
        return {'available': r.returncode == 0, 'stdout': r.stdout, 'error': r.stderr}
    except subprocess.TimeoutExpired:
        return {'available': False, 'error': 'ssh A100连接超时；保留既有SSH配置，恢复网络后可重试'}


def get_inventory(project, refresh=False):
    if refresh or 'resources' not in project.data:
        project.data['resources'] = discover()
        project.save()
    return project.data['resources']
