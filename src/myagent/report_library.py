"""Authored mixed-material catalog, document extraction and local content retrieval.

SQLite stores searchable passages, never model embeddings or generated facts.
The librarian role chooses document purposes; rules only propose candidates.
"""
from __future__ import annotations

import json
import io
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .jobs import atomic_json
from .lab_project import digest,now
from .guidance_material import SLIDES, guidance_pages, slide_pages


TEXT={'.txt','.md','.csv','.json','.jsonl','.log','.py','.ipynb','.r','.m','.js','.ts','.yaml','.yml','.toml','.tex','.html','.xml','.sql','.c','.cpp','.h'}
IMAGES={'.png','.jpg','.jpeg','.svg','.webp','.bmp'}
from .word_material import GUIDES, WORD, word_pages

DOCUMENTS = GUIDES | SLIDES


def passages(path, cache=None):
    """Yield extracted chunks with original page or physical-line anchors."""
    if path.suffix.lower()=='.pdf':
        import fitz
        with fitz.open(path) as pdf:
            for number,page in enumerate(pdf,1):
                text=page.get_text()
                for start in range(0,len(text),4000):
                    yield {'page':number,'start_char':start,'text':text[start:start+4000]}
    elif path.suffix.lower() in WORD | SLIDES:
        offset=0
        pages = (word_pages(path,cache) if path.suffix.lower() in WORD else
                 guidance_pages(path,cache) if cache is not None else slide_pages(path))
        for page in pages:
            text=page['text']
            for start in range(0,len(text),4000):
                yield {**page,'start_char':offset+start,'text':text[start:start+4000]}
            offset+=len(text)+1
    elif path.suffix.lower() in TEXT or path.suffix.lower() in ('.zstd','.zst'):
        if path.suffix.lower() in ('.zstd','.zst'):
            import zstandard
            stream=io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(path.open('rb')),encoding='utf-8-sig',errors='replace')
        else:stream=path.open(encoding='utf-8-sig',errors='replace')
        with stream:
            batch=[];start=1;size=0
            for number,line in enumerate(stream,1):
                if batch and size+len(line)>4000:
                    yield {'start_line':start,'end_line':number-1,'text':''.join(batch)}
                    batch=[];size=0;start=number
                # Preserve offsets even for giant single-line JSON records.
                if len(line)>8000:
                    for offset in range(0,len(line),4000):
                        yield {'start_line':number,'end_line':number,'start_char':offset,'text':line[offset:offset+4000]}
                    start=number+1
                else:batch.append(line);size+=len(line)
            if batch:yield {'start_line':start,'end_line':number,'text':''.join(batch)}


def suggest(path,preview):
    name=path.name.lower();text=preview.lower()
    if path.suffix.lower() in ('.zstd','.zst'):return 'sessions','compressed original session; searchable decoded lines'
    if path.suffix.lower() in IMAGES:return 'figures','image file; pixel content not classified'
    if path.suffix.lower() in {'.py','.ipynb','.r','.m','.js','.ts','.c','.cpp','.h','.sql'}:return 'code','source-code format'
    if path.suffix.lower() not in DOCUMENTS and path.suffix.lower() not in {'.md','.txt','.json'}:return 'results' if path.suffix.lower() in TEXT else 'data','file format'
    if re.search(r'模板|空白|template|blank',name):return 'template','template name; librarian verifies content'
    if re.search(r'指导|要求|任务书|手册|guide|instruction|rubric',name):return 'guidance','guidance name; librarian verifies content'
    if re.search(r'报告|report|论文|paper',name) and not re.search(r'模板|template',name):return 'reference','completed-report candidate; not a fresh experimental result'
    signals=sum(word in text for word in ('实验目的','实验内容','实验要求','评分','考核','实验步骤','提交要求','实验任务','objectives','submission','grading'))
    if path.suffix.lower() in DOCUMENTS and signals>=2:return 'guidance',f'document content contains {signals} teaching/assignment signals'
    if path.suffix.lower() in DOCUMENTS:return 'documents','document needs librarian content interpretation'
    return 'results','text or structured experiment material'


def index_library(project):
    p=project;db=p.root/'material-library.sqlite3'
    records=[];seen={};errors=[]
    designated = {m.get('sha256') for m in p.data['materials']
                  if m['role'] in ('guidance', 'template', 'reference')}
    designated.update(m['sha256'] for m in p.data.get('superseded_guidance', []))
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('CREATE TABLE IF NOT EXISTS passages (source_id TEXT, anchor TEXT, text TEXT)')
        conn.execute('DELETE FROM passages')
        for material in list(p.data['materials']):
            if material['role']!='library':continue
            root=p.file(material.get('expanded_path',material['path']))
            for path in sorted(root.rglob('*')) if root.is_dir() else [root]:
                if not path.is_file() or any(x in path.parts for x in ('.git','.venv','node_modules','__pycache__')) or path.name.startswith('.env'):continue
                sha=digest(path)
                if sha in designated:continue
                if sha in seen:
                    seen[sha]['aliases'].append(str(path.relative_to(p.root)));continue
                row={'id':f'S{len(records)+1:04}','path':str(path.relative_to(p.root)),
                    'label':path.name,'sha256':sha,'bytes':path.stat().st_size,'aliases':[],
                    'origin':'User supplied mixed library; this run did not execute the experiment.'}
                preview='';count=0
                try:
                    for piece in passages(path,p.root/"extracted"):
                        conn.execute('INSERT INTO passages VALUES (?,?,?)',(row['id'],json.dumps({k:v for k,v in piece.items() if k!='text'}),piece['text']))
                        preview+=piece['text'][:max(0,6000-len(preview))];count+=1
                except Exception as exc:
                    row['read_error']=f'{type(exc).__name__}: {exc}';errors.append({'id':row['id'],'error':row['read_error']})
                category,reason=suggest(path,preview)
                row.update(category=category,suggested_category=category,classification_reason=reason,
                    preview=preview[:1600],indexed_chunks=count)
                records.append(row);seen[sha]=row
    p.data.update(report_sources=records,report_profile='completed_experiment',
        material_library={'version':1,'status':'indexed','at':now(),'files':len(records),
            'duplicates':sum(len(r['aliases']) for r in records),'errors':errors,
            'index_path':str(db.relative_to(p.root))})
    rebuild_groups(p)
    p.save()


def rebuild_groups(project):
    """Group real files as report evidence; document roles stay outside results."""
    p=project;groups={}
    for row in p.data['report_sources']:
        if row['category'] in ('guidance','template','reference'):continue
        groups.setdefault(row['category'],[]).append(row)
    p.data['tasks']=[];p.data['results']={}
    for i,(category,rows) in enumerate(groups.items(),1):
        tid=f'E{i}'
        p.data['tasks'].append({'id':tid,'title':category,'kind':'analysis','requirements':[],
            'depends_on':[],'instructions':'Interpret supplied completed experiment evidence.'})
        p.data['results'][tid]={'artifacts':[{'path':r['path'],'sha256':r['sha256']} for r in rows],
            'source_paths':[r['path'] for r in rows],'receipt_ids':[],'remaining_work':[],'origin':'imported'}
    p.data['report_material_groups']=[{'category':c,'task_id':f'E{i}','count':len(rows)} for i,(c,rows) in enumerate(groups.items(),1)]
    atomic_json(p.root/'source-manifest.json',{'sources':p.data['report_sources'],'groups':p.data['report_material_groups']})


def choose_documents(project,decisions):
    p=project;by_id={r['id']:r for r in p.data['report_sources']}
    for row in decisions:
        source=by_id[row['id']];source.update(category=row['role'],classification_reason=row['reason'])
    # Promote the librarian's choices to normal M sources, without another copy.
    promoted=[m for m in p.data['materials'] if not m.get('library_source_id')]
    for source in p.data['report_sources']:
        if source['category'] not in ('guidance','template','reference'):continue
        mid=f'M{len(promoted)+1}'
        promoted.append({'id':mid,'role':source['category'],'name':source['label'],
            'path':source['path'],'sha256':source['sha256'],'bytes':source['bytes'],
            'library_source_id':source['id']})
        source['material_id']=mid
    p.data['materials']=promoted
    p.extract();rebuild_groups(p)
    from .lab_template import heading_contract
    p.data['plan']={'report_outline':heading_contract(p)['required_headings'],'questions':[]}
    p.data['material_library'].update(status='organized',organized_at=now(),decisions=decisions)
    p.save()


def search(project,query,category=None,limit=12):
    """Local lexical ranking over original text, with CJK bigrams and anchors."""
    if not query.strip():raise ValueError('请提供要查找的内容')
    terms=set(re.findall(r'[a-zA-Z0-9_]{2,}',query.lower()))
    for run in re.findall(r'[\u4e00-\u9fff]+',query):
        terms.add(run)
        if len(run)>2:terms.update(run[i:i+2] for i in range(len(run)-1))
    if not terms:terms={query.lower()}
    by_id={r['id']:r for r in project.data['report_sources'] if not category or r['category']==category}
    hits=[]
    with closing(sqlite3.connect(project.root/'material-library.sqlite3')) as conn:
        # Coarse SQL candidate selection keeps Python ranking off unrelated passages.
        clauses=' OR '.join('instr(lower(text),?)>0' for _ in terms)
        for sid,anchor,text in conn.execute('SELECT source_id,anchor,text FROM passages WHERE '+clauses,tuple(sorted(terms))):
            if sid not in by_id:continue
            lowered=text.lower();score=sum(min(lowered.count(t),4)*len(t) for t in terms)
            position=min((lowered.find(t) for t in terms if t in lowered),default=0)
            start=max(0,position-160)
            source=by_id[sid]
            hits.append({'id':sid,'path':source['path'],'category':source['category'],
                **json.loads(anchor),'excerpt':text[start:start+1000],'excerpt_start_char':start,'score':score})
    # Name hits allow images and binary artifacts to be found without OCR claims.
    for source in by_id.values():
        label=(source['path']+' '+source.get('label','')).lower()
        score=sum(len(t)*4 for t in terms if t in label)
        if score:hits.append({'id':source['id'],'path':source['path'],'category':source['category'],
            'excerpt':source.get('preview','')[:1000],'score':score,'match':'path/name'})
    hits.sort(key=lambda r:(-r['score'],r['id'],r.get('page',0)))
    return {'query':query,'total_hits':len(hits),'matches':hits[:limit],
        'notice':'Local original-text/name retrieval. Image pixels are not indexed; no claim of semantic image understanding.'}
