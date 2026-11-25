"""Exclusive image ownership: first committed placement wins; later uses refer."""
from __future__ import annotations
import copy
import re
from collections import defaultdict
from .figure_quality import FIGURE_LABEL
from .lab_project import digest


def image_ownership(project):
    owners={}
    for key,part in project.data.get('writing_parts',{}).items():
        for section in part.get('sections',[]):
            for block in section.get('blocks',[]):
                if block['type']=='image':
                    owners.setdefault(digest(project.file(block['path'])),
                        {'block_id':block['id'],'path':block['path'],'heading':section['heading'],'part_key':key})
    project.data['report_image_owners']=owners
    return copy.deepcopy(owners)


def claim_part_images(project,part,*,part_key):
    result=copy.deepcopy(part);owners=image_ownership(project)
    for section in result['sections']:
        for block in section['blocks']:
            if block['type']!='image':continue
            sha=digest(project.file(block['path']));owner=owners.get(sha)
            if owner and owner['block_id']!=block['id']:
                original=copy.deepcopy(block)
                block.clear();block.update(id=original['id'],type='text',
                    text='见{{figure:'+owner['block_id']+'}}。',
                    **{k:original[k] for k in ('requirements','evidence') if k in original})
                result.setdefault('figure_ownership_changes',[]).append({'original':original,'owner':copy.deepcopy(owner)})
            else:
                owners[sha]={'block_id':block['id'],'path':block['path'],'heading':section['heading'],'part_key':part_key}
    project.data['report_image_owners']=owners
    return result




def _figure_section_allowed(heading):
    text = str(heading)
    return text.startswith(('六、', '七、', '6.', '7.')) or any(word in text for word in ('步骤', '结果', '分析'))


def move_figures_to_core_sections(document):
    result = copy.deepcopy(document)
    target = next((section for section in result['sections'] if str(section.get('heading', '')).startswith('七、')), None)
    if target is None:
        target = next((section for section in result['sections'] if _figure_section_allowed(section.get('heading', '')) and '步骤' not in str(section.get('heading', ''))), None)
    if target is None:
        return result
    moved = []
    for section in result['sections']:
        if section is target or _figure_section_allowed(section.get('heading', '')):
            continue
        kept = []
        for block in section.get('blocks', []):
            if block.get('type') == 'image':
                moved.append(block)
                kept.append({'id': block['id']+'-ref', 'type': 'text', 'text': '相关图表集中列于第七节。正文在图前交代观察对象，图后说明结果。', 'evidence': block.get('evidence', [])})
            else:
                kept.append(block)
        section['blocks'] = kept
    if moved:
        target.setdefault('blocks', []).extend(moved)
    return result

def assemble_figures(project, document):
    result=move_figures_to_core_sections(document)
    seen={};aliases={};removed=[];local=[];global_numbers=defaultdict(set)
    for section in result['sections']:
        numbers=defaultdict(set);local.append(numbers)
        for block in section['blocks']:
            if block['type']!='image':continue
            sha=digest(project.file(block['path']));canonical=seen.setdefault(sha,block)
            aliases[block['id']]=canonical['id']
            old=re.match(r'^\s*'+FIGURE_LABEL,block.get('caption',''))
            if old:
                numbers[old[1]].add(canonical['id']);global_numbers[old[1]].add(canonical['id'])
            if canonical is not block:
                original=copy.deepcopy(block)
                removed.append({'block':original,'canonical_id':canonical['id'],'sha256':sha})
                extra=re.sub(r'^\s*'+FIGURE_LABEL+r'\s*','',block.get('caption','')).strip()
                if extra and extra not in canonical.get('caption',''):
                    canonical['caption']=canonical.get('caption','')+'；'+extra
                for key in ('requirements','evidence'):
                    if key in block:canonical[key]=list(dict.fromkeys([*canonical.get(key,[]),*block[key]]))
                bid=block['id'];refs={k:copy.deepcopy(block[k]) for k in ('requirements','evidence') if k in block}
                block.clear();block.update(id=bid,type='text',text='见{{figure:'+canonical['id']+'}}。',**refs)
    if not seen:return result
    for section,numbers in zip(result['sections'],local):
        for block in section['blocks']:
            for field in ('text','caption'):
                if field not in block:continue
                text=re.sub(r'\{\{figure:([^}]+)\}\}',lambda m:'{{figure:'+aliases.get(m[1],m[1])+'}}',block[field])
                if block['type']=='text' and document.get('figure_reference_version')!=1:
                    def reference(m):
                        choices=numbers.get(m[1]) or global_numbers.get(m[1],set())
                        return '{{figure:'+next(iter(choices))+'}}' if len(choices)==1 else m[0]
                    text=re.sub(FIGURE_LABEL,reference,text)
                block[field]=text
    if not any(re.search(r'图\s*\d+',b.get('text','')) for s in result['sections'] for b in s['blocks'] if b['type']=='text'):
        result['figure_reference_version']=1
    if removed:
        result.setdefault('figure_assembly',{'version':1,'duplicates':[]})['duplicates'].extend(removed)
    return result
