"""Persistent experiment projects. Documents are inputs; execution receipts are evidence."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from .word_material import GUIDES, WORD, word_pages
from .jobs import atomic_json
from .task_state import now
from .tools.base import resolve_workspace_path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pdf_pages(path):
    import fitz

    with fitz.open(path) as pdf:
        return [{'page': i, 'text': page.get_text()} for i, page in enumerate(pdf, 1)]


def scanned_guidance_error(name):
    return f'{name}是扫描件，本初版需要可提取文字的PDF'


def task_generation(project, task_id):
    return next((t.get('plan_generation',0) for t in project.data['tasks'] if t['id']==task_id),0)


def current_receipts(project, task_id=None):
    return [r for r in project.data['receipts'] if (task_id is None or r['task_id']==task_id)
            and r.get('plan_generation',0)==task_generation(project,r['task_id'])]


def environment():
    packages = {}
    for name in ('numpy', 'scipy', 'scikit-learn', 'matplotlib', 'torch', 'pandas', 'PyMuPDF', 'reportlab'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {'platform': platform.platform(), 'python': sys.version.split()[0],
            'interpreter': sys.executable, 'cpus': os.cpu_count(), 'packages': packages,
            'capabilities': ['python', 'pdf', 'files'],
            'remote': '远程GPU和外部实验软件尚未接入本初版；不能据此声称不可用。'}


class LabProject:
    def __init__(self, workspace, project_id):
        self.workspace = Path(workspace).resolve()
        if not re.fullmatch(r'[a-f0-9]{12}', project_id):
            raise ValueError('invalid experiment id')
        self.id = project_id
        self.root = self.workspace / 'experiments' / project_id
        self.path = self.root / 'project.json'
        self.data = json.loads(self.path.read_text(encoding='utf-8'))

    @classmethod
    def create(cls, workspace, *, title, materials, instructions='', student_id='', include_bonus=False, student=None):
        ws = Path(workspace).resolve()
        if not ws.is_dir() or not str(title).strip():
            raise ValueError('需要现有工作文件夹和实验名称')
        # Validate before allocating a project. Original materials are never changed.
        sources = []
        for item in materials:
            path = Path(item['path']).expanduser().resolve()
            role = item.get('role', 'data')
            if role not in ('guidance', 'data', 'template', 'reference', 'library') or not (path.is_file() or (role in ('data','library') and path.is_dir())):
                raise ValueError(f'无效材料: {path}')
            if path.name.lower().startswith('.env'):
                raise ValueError('密钥文件不作为实验材料')
            if role == 'guidance' and path.suffix.lower() not in GUIDES:
                raise ValueError('指导书支持 PDF、DOC 和 DOCX')
            if role == 'template' and path.suffix.lower() not in ('.pdf', '.txt', '.md', '.json', '.doc', '.docx'):
                raise ValueError('模板支持 PDF、DOC、DOCX、TXT、Markdown 或 JSON')
            sources.append((path, role))
        if not any(role in ('guidance','library') for _, role in sources):
            raise ValueError('至少提供一份 PDF 或 Word 指导书')
        pid = uuid4().hex[:12]
        root = ws / 'experiments' / pid
        (root / 'inputs').mkdir(parents=True)
        inventory = []
        for i, (source, role) in enumerate(sources, 1):
            target = root / 'inputs' / f'{i:02}_{source.name}'
            if source.is_dir():
                def ignored(folder,names):
                    skipped = []
                    for name in names:
                        entry = Path(folder) / name
                        if (name.lower() in {'.git', '.venv', 'node_modules', '__pycache__'}
                                or name.lower().startswith('.env')
                                or entry.suffix.lower() in {'.key', '.pem', '.pfx', '.p12'}
                                or entry.is_symlink()
                                or getattr(entry, 'is_junction', lambda: False)()
                                or entry.resolve() == root):
                            skipped.append(name)
                    return skipped
                shutil.copytree(source, target,ignore=ignored)
            else:
                shutil.copy2(source, target)
            inventory.append({'id': f'M{i}', 'role': role, 'name': source.name,
                              'original': str(source), 'path': str(target.relative_to(root)),
                              'sha256': digest(target) if target.is_file() else None,
                              'bytes': target.stat().st_size if target.is_file() else sum(f.stat().st_size for f in target.rglob('*') if f.is_file())})
            expand_data(root, target, inventory[-1])
        data = {'id': pid, 'title': title.strip(), 'created_at': now(), 'updated_at': now(),
                'instructions': instructions, 'student_id': student_id, 'include_bonus': bool(include_bonus),
                'student': {**(student or {}), 'student_id': student_id},
                'status': 'ready', 'stage': 'materials', 'materials': inventory, 'requirements': [],
                'tasks': [], 'results': {}, 'receipts': [], 'comments': [], 'reviews': [],
                'report': None, 'revisions': [], 'activity': [], 'runs': [], 'environment': environment(),
                'totals': {'steps': 0, 'cost_usd': 0.0, 'tokens': 0}, 'last_error': ''}
        atomic_json(root / 'project.json', data)
        return cls(ws, pid)

    def add_materials(self, materials):
        # Import into this project; keep existing successful task results intact.
        if not materials:
            raise ValueError('请提供需要补充的材料')
        if any(m.get('role','data') != 'data' for m in materials):
            raise ValueError('执行中补充只接受数据/初始代码；更换指导书或模板请新建实验')
        imported=[]
        for item in materials:
            source=Path(item['path']).expanduser().resolve()
            if not source.exists() or source.name.lower().startswith('.env'):
                raise ValueError('无效的数据材料')
            index=len(self.data['materials'])+1
            target=self.root/'inputs'/f'{index:02}_{source.name}'
            if source.is_dir():
                shutil.copytree(source,target,ignore=lambda folder,names:[name for name in names
                    if name in ('.git','.venv','node_modules','__pycache__') or name.lower().startswith('.env')])
            else:
                shutil.copy2(source,target)
            record={'id':f'M{index}','role':'data','name':source.name,'original':str(source),
                    'path':str(target.relative_to(self.root)),
                    'sha256':digest(target) if target.is_file() else None,
                    'bytes':target.stat().st_size if target.is_file() else sum(f.stat().st_size for f in target.rglob('*') if f.is_file())}
            expand_data(self.root,target,record)
            self.data['materials'].append(record);imported.append(record)
        self.note('补充数据/初始代码材料，已完成实验保留')
        return imported

    def save(self):
        self.data['updated_at'] = now()
        atomic_json(self.path, self.data)

    def update_instructions(self, instructions):
        """A new user decision supersedes an old scope without deleting evidence."""
        if not isinstance(instructions,str) or not instructions.strip():
            raise ValueError('请提供本次目标和范围说明')
        if instructions == self.data['instructions']:
            return self.data
        self.data.setdefault('instruction_history',[]).append({'at':now(),'instructions':self.data['instructions']})
        self.data['instructions']=instructions.strip()
        self.data['plan_pending']=True
        self.data.update(status='ready',stage='plan')
        self.note('用户更新实验目标；保留原实验与报告，下次开始按新目标重新规划')
        return self.data

    def note(self, text, **extra):
        self.data['activity'].append({'at': now(), 'text': text, **extra})
        self.save()

    def file(self, raw):
        return resolve_workspace_path(self.root, raw)

    def extract(self):
        texts = []
        for item in self.data['materials']:
            # Previous reports are comparison references, never new experimental observations.
            if item['role'] in ('reference','library'):
                continue
            path = self.file(item['path'])
            if path.is_dir():
                continue
            if path.suffix.lower() == '.pdf':
                pages = pdf_pages(path)
                item['pages'] = len(pages)
                item['empty_pages'] = [p['page'] for p in pages if not p['text'].strip()]
                if not any(p['text'].strip() for p in pages) and item['role'] == 'guidance':
                    raise ValueError(scanned_guidance_error(item['name']))
                texts.append({'material_id': item['id'], 'role': item['role'], 'path': item['path'], 'pages': pages})
            elif item['role'] in ('guidance','template') and path.suffix.lower() in WORD:
                pages = word_pages(path, self.root/'extracted')
                item['pages'] = len(pages)
                texts.append({'material_id':item['id'],'role':item['role'],'path':item['path'],'pages':pages})
            elif item['role'] == 'template' and path.suffix.lower() in ('.md', '.txt', '.json'):
                text = path.read_text(encoding='utf-8-sig')
                texts.append({'material_id': item['id'], 'role': 'template', 'text': text})
        atomic_json(self.root / 'materials.json', {'documents': texts})
        from .lab_template import read_template
        read_template(self, texts)
        self.save()
        return texts

    def comment(self, block_id, text, version, action='text', task_id=None):
        report = self.data['report']
        if not report or version != report['version']:
            raise ValueError('报告版本已改变，请刷新后再批注')
        blocks = {b['id'] for s in report['document']['sections'] for b in s['blocks']}
        if block_id not in blocks or not text.strip():
            raise ValueError('需要有效段落和批注内容')
        if action not in ('text','experiment') or (action=='experiment' and task_id not in {t['id'] for t in self.data['tasks']}):
            raise ValueError('补实验请指定现有任务')
        row = {'id': uuid4().hex[:12], 'block_id': block_id, 'text': text.strip(),
               'version': version, 'status': 'open', 'at': now(), 'action':action,'task_id':task_id}
        self.data['comments'].append(row)
        self.note('收到报告批注', comment=row['id'])
        return row

    def acquire(self):
        """OS lock also protects against a separate CLI or web process."""
        stream = (self.root / '.writer.lock').open('a+b')
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise ValueError('这个实验正在执行，请先暂停') from None
        # Reload only after the lock: stale readers must not overwrite live state.
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        return stream


def list_projects(workspace):
    rows = []
    for path in (Path(workspace) / 'experiments').glob('*/project.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        rows.append({k: data[k] for k in ('id', 'title', 'status', 'stage', 'updated_at', 'totals')})
    return sorted(rows, key=lambda x: x['updated_at'], reverse=True)


def expand_data(root, target, record):
    if record['role'] not in ('data','library') or target.suffix.lower() != '.zip' or not target.is_file():
        return
    import zipfile
    destination=target.with_name(target.stem+'-unpacked')
    with zipfile.ZipFile(target) as archive:
        for member in archive.infolist():
            # Zip paths use forward slashes, even on Windows.
            resolve_workspace_path(destination,member.filename)
        archive.extractall(destination)
    record['expanded_path']=str(destination.relative_to(root))
