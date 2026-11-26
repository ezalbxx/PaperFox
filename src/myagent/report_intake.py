"""Import completed experiments into the single report workflow."""
from collections import defaultdict
from pathlib import Path

from .jobs import atomic_json
from .guidance_material import guidance_pages
from .lab_project import LabProject, digest, now
from .spreadsheet_material import SPREADSHEETS


def prepare_report(project):
    """Index supplied files, never pretend an imported result was executed here."""
    p=project
    if 'report_sources' not in p.data and not p.data.get('report'):
        p.data.setdefault('use_default_report_template',True)
    p.data.setdefault('report_review_mode','lean')
    if p.data.get('studio', {}).get('mode') != 'report':
        p.data.setdefault('report_review_budget_cny',1.0)
    p.data.setdefault('report_review_scope','chapters')
    p.data.setdefault('report_production_mode','lean')
    if p.data.get('report_review_mode')=='lean' and not p.data.get('report_first_pass'):
        p.data.setdefault('chapter_review_mode','enabled')
    if 'report_sources' in p.data:return
    if any(m['role']=='library' for m in p.data['materials']):
        for material in p.data['materials']:
            if material['role'] == 'guidance':
                guidance_pages(p.file(material['path']), p.root/'extracted', name=material['name'])
        from .report_library import index_library
        index_library(p)
        p.data['report_import']={'at':now(),'source':'mixed material library','no_execution':True}
        p.save()
        return
    p.extract()
    groups=defaultdict(list)
    for material in p.data['materials']:
        if material['role']!='data':continue
        root=p.file(material.get('expanded_path',material['path']))
        for path in sorted(root.rglob('*')) if root.is_dir() else [root]:
            if not path.is_file() or any(x in path.parts for x in ('.git','node_modules','__pycache__','.venv')) or path.name.startswith('.env'):continue
            suffix=path.suffix.lower()
            category=('figures' if suffix in ('.png','.jpg','.jpeg','.svg') else
                      'code' if suffix in ('.py','.ipynb','.r','.m','.js') else
                      'results' if suffix in {'.csv','.json','.jsonl','.txt','.log','.md'} | SPREADSHEETS else 'data')
            groups[category].append(path)
    records=[]
    for index,(category,paths) in enumerate(groups.items(),1):
        tid=f'E{index}';rows=[]
        for path in paths:
            row={'id':f'S{len(records)+1:04}','category':category,'label':path.name,
                 'path':str(path.relative_to(p.root)),'sha256':digest(path),'bytes':path.stat().st_size,
                 'origin':'User supplied completed experiment material; not executed by this report run.'}
            records.append(row);rows.append(row)
        p.data['tasks'].append({'id':tid,'title':category,'kind':'analysis','requirements':[],
            'depends_on':[],'instructions':'Interpret supplied completed experiment evidence.'})
        p.data['results'][tid]={'artifacts':[{'path':r['path'],'sha256':r['sha256']} for r in rows],
            'source_paths':[r['path'] for r in rows],'receipt_ids':[],'remaining_work':[],'origin':'imported'}
    p.data['report_sources']=records
    p.data['report_material_groups']=[{'category':c,'task_id':f'E{i}','count':len(rows)} for i,(c,rows) in enumerate(groups.items(),1)]
    p.data['report_profile']='completed_experiment'
    from .lab_template import heading_contract
    p.data['plan']={'report_outline':heading_contract(p)['required_headings'], 'questions':[]}
    p.data['report_import']={'at':now(),'source':'user materials','no_execution':True}
    atomic_json(p.root/'source-manifest.json',{'sources':records,'groups':p.data['report_material_groups']})
    p.save()


def prior_import_facts(project, *, curated_facts_version=None):
    """Reuse reported facts for identical, completed imports in this workspace."""
    import json

    p = project
    if (p.data.get('report_profile') != 'completed_experiment'
            or p.data.get('validation_origin') or not p.data.get('report_sources')):
        return None

    def identity(data):
        return (
            tuple(sorted((item['path'], item['category'], item['sha256'])
                         for item in data.get('report_sources', []))),
            tuple((item['role'], item['path'], item['sha256'])
                  for item in data['materials'] if item['role'] in ('guidance', 'template')),
        )

    expected = identity(p.data)
    for path in sorted(p.root.parent.glob('*/project.json'), reverse=True):
        if path == p.path:
            continue
        try:
            candidate = json.loads(path.read_text(encoding='utf8'))
            workflow = candidate.get('report_workflow', {})
            facts = workflow.get('outputs', {}).get('facts')
            if (candidate.get('report_profile') == 'completed_experiment'
                    and not candidate.get('validation_origin')
                    and not candidate.get('instruction_history')
                    and workflow.get('status') == 'completed'
                    and not workflow.get('interactions')
                    and facts and not facts.get('questions')
                    and (curated_facts_version is None or
                         facts.get('curated_facts_version')==curated_facts_version and
                         candidate.get('instructions')==p.data.get('instructions'))
                    and identity(candidate) == expected):
                return path.parent.name, facts
        except (OSError, ValueError, KeyError):
            continue
    return None


def prior_planning_outputs(project, *, outline_selection_version=None, story_selection_version=None):
    """Return reusable facts/story cards/outline for identical imported sources."""
    import json
    p = project
    expected = tuple(sorted((r.get('path'), r.get('category'), r.get('sha256'))
                            for r in p.data.get('report_sources', [])))
    if not expected:
        return None
    for path in sorted(p.root.parent.glob('*/project.json'), reverse=True):
        if path == p.path:
            continue
        try:
            candidate = json.loads(path.read_text(encoding='utf8'))
            workflow = candidate.get('report_workflow', {})
            outputs = workflow.get('outputs', {})
            sources = tuple(sorted((r.get('path'), r.get('category'), r.get('sha256'))
                                   for r in candidate.get('report_sources', [])))
            if (candidate.get('report_profile') == 'completed_experiment'
                    and workflow.get('status') == 'completed'
                    and expected == sources
                    and outputs.get('facts') and outputs.get('story_cards')
                    and outputs.get('outline')
                    and (story_selection_version is None or
                         outputs['story_cards'].get('card_selection_version')==story_selection_version)
                    and (outline_selection_version is None or
                         outputs['outline'].get('card_selection_version')==outline_selection_version
                         and outputs['story_cards']==p.data.get('report_workflow',{}).get('outputs',{}).get('story_cards'))
                    and (outline_selection_version is None or candidate.get('instructions')==p.data.get('instructions')
                         and candidate.get('template')==p.data.get('template'))):
                return path.parent.name, outputs
        except (OSError, ValueError, KeyError):
            continue
    return None


def create_report(workspace,data):
    materials=([{'path':data['library_path'],'role':'library'}] if data.get('library_path') else data.get('materials',[]))
    title=data.get('title','').strip() or (Path(data['library_path']).stem if data.get('library_path') else '实验报告')
    p=LabProject.create(workspace,title=title,materials=materials,
        instructions=data.get('instructions',''),student_id=data.get('student_id',''),
        include_bonus=data.get('include_bonus',False),student=data.get('student'))
    prepare_report(p)
    return p
