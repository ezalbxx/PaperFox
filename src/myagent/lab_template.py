"""Authored report-template reader. Preserve PDF covers; reflow body sections."""
from __future__ import annotations

import re
import statistics
from .word_material import WORD, word_pages, word_section_headings
import json
from pathlib import Path

from .jobs import atomic_json


SECTION = re.compile(r'^\s*(?:第[一二三四五六七八九十\d]+[章节]|[（(][一二三四五六七八九十\d]+[）)]|'
                     r'(?:[一二三四五六七八九十\d]+|[IVXLCDM]+)[、．.)）](?!\d))\s*[^\n]{2,65}')


def docx_text(path):
    return '\n'.join(p['text'] for p in word_pages(path))


def markdown_section_headings(text):
    levels = {}
    fence = ''
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ''
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*$', line)
        if heading:
            title = re.sub(r'\s+#+$', '', heading[2]).strip()
            levels.setdefault(len(heading[1]), []).append(title)
    if not levels:
        return []
    level = min(levels)
    # A lone document title followed by peers is the common Markdown template form.
    if level == 1 and len(levels[1]) == 1 and len(levels.get(2, [])) > 1:
        return levels[2]
    return levels[level]


def read_template(project, documents):
    candidates = [m for m in project.data['materials'] if m['role'] == 'template']
    supplied = [m for m in candidates if not m.get('is_default_template')]
    if supplied:candidates=supplied
    if not candidates and project.data.get('use_default_report_template'):
        from .lab_project import digest
        bundled=Path(__file__).with_name('default_report_template.json')
        target=project.root/'inputs/default-report-template.json'
        target.write_bytes(bundled.read_bytes())
        mid='M'+str(max([int(m['id'][1:]) for m in project.data['materials'] if m['id'][1:].isdigit()]+[0])+1)
        material={'id':mid,'name':'默认实验报告模板.json','role':'template',
            'path':str(target.relative_to(project.root)),'sha256':digest(target),
            'bytes':target.stat().st_size,'is_default_template':True}
        project.data['materials'].append(material);candidates=[material]
    if not candidates:
        return None
    item = candidates[0]
    source = project.file(item['path'])
    spec = {'material_id': item['id'], 'source': item['path'], 'source_sha256': item['sha256'],
            'headings': [], 'cover_page': None, 'body_font_size': 12, 'heading_font_size': 14,
            'margins': {'left': 62, 'right': 62, 'top': 48, 'bottom': 50},
            'fields': {}, 'signature_labels': []}
    spec['origin']='user_default_template' if item.get('is_default_template') else 'user_template'
    # PDF/DOCX headings are parser candidates, not a teacher's verbatim contract.
    spec['headings_origin'] = 'explicit' if source.suffix.lower() == '.json' else 'inferred'
    if source.suffix.lower() == '.json':
        configured = __import__('json').loads(source.read_text(encoding='utf-8-sig'))
        for key in ('headings', 'body_font_size', 'heading_font_size', 'margins', 'fields', 'signature_labels', 'page_size', 'layout'):
            if key in configured:
                spec[key] = configured[key]
        if item.get('is_default_template'):
            for key in ('template_version','source_doc','section_notes','emphasis','planning_guidance','trailing_fields','typography'):
                if key in configured:spec[key]=configured[key]
        text = ''
    elif source.suffix.lower() == '.pdf':
        import fitz
        with fitz.open(source) as pdf:
            texts = [p.get_text() for p in pdf]
            text = '\n'.join(texts)
            spec['headings'] = list(dict.fromkeys(title.strip() for level, title, _ in pdf.get_toc()
                                                  if level == 1 and title.strip()))
            section_pages = [i for i, t in enumerate(texts) if any(SECTION.match(line) for line in t.splitlines())]
            if section_pages and section_pages[0] > 0:
                spec['cover_page'] = 1
            # Infer font size from the template's actual body section labels.
            sizes, lefts = [], []
            for i in section_pages:
                for block in pdf[i].get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        spans = line['spans']
                        if SECTION.match(''.join(s['text'] for s in spans)):
                            sizes += [s['size'] for s in spans if s['text'].strip()]
                            lefts.append(line['bbox'][0])
            if sizes:
                spec['heading_font_size'] = round(statistics.median(sizes), 1)
                spec['body_font_size'] = min(12, spec['heading_font_size'])
            if lefts:
                spec['margins']['left'] = round(min(lefts), 1)
                spec['margins']['right'] = round(min(lefts), 1)
            if pdf:
                spec['page_size'] = [pdf[-1].rect.width, pdf[-1].rect.height]
    elif source.suffix.lower() in WORD:
        text = '\n'.join(p['text'] for p in word_pages(source,project.root/'extracted'))
        spec['headings'] = list(dict.fromkeys(word_section_headings(source)))
    else:
        text = source.read_text(encoding='utf-8-sig')
        if source.suffix.lower() == '.md':
            spec['headings'] = list(dict.fromkeys(markdown_section_headings(text)))
    if not spec['headings']:
        for line in text.splitlines():
            match = SECTION.match(line)
            if match:
                heading = match.group().strip().rstrip('：: ')
                if heading not in spec['headings']:
                    spec['headings'].append(heading)
    if text.strip():
        excerpt = text.strip()
        spec['body_excerpt'] = excerpt[:4000]
        if len(excerpt) > 4000:
            spec['body_excerpt_truncated'] = True
    for label in ('报告评分', '指导教师签字'):
        if label in text:
            spec['signature_labels'].append(label)
    for label, field in (('学生姓名', 'name'), ('学号', 'student_id'), ('指导教师', 'teacher'), ('班级', 'class_name')):
        if label in re.sub(r'\s', '', text):
            spec['fields'][field] = label
    spec['notice'] = ('PDF封面保留原版；正文按模板章节、字号、页边距重新排版并保留评分签字栏。'
                      '不承诺任意Word复杂表单逐像素复制；未知信息留空，不猜姓名或教师。')
    atomic_json(project.root / 'template.json', spec)
    project.data['template'] = spec
    project.save()
    return spec


def template_context(project):
    spec = project.data.get('template')
    if not spec:
        return None
    return {k: v for k, v in spec.items() if k not in ('cover_page', 'margins', 'page_size')}


def normalized_heading(text):
    return re.sub(r'[\s：:、,.．（）()]', '', text)


def heading_contract(project):
    """Explicit structured templates remain binding; parser guesses are advisory."""
    spec = project.data.get('template') or {}
    required = spec.get('headings', []) if spec.get('headings_origin', 'explicit') != 'inferred' else []
    origin = spec.get('origin','user_template')
    explicit = project.data.get('report_heading_constraints', {})
    if origin=='user_default_template' and explicit.get('headings'):
        required=explicit['headings'];origin=explicit.get('origin','explicit_requirement')
    if not required:
        required = explicit.get('headings', [])
        origin = explicit.get('origin', 'explicit_requirement')
    return {'required_headings': required, 'origin': origin if required else 'agent_planned',
        'suggested_headings': spec.get('headings', []) if not required else [],
        'strict': bool(required)}


def default_template_context(project, headings=()):
    spec=project.data.get('template') or {}
    if heading_contract(project)['origin']!='user_default_template':return None
    return {'headings':spec['headings'],'planning_guidance':spec.get('planning_guidance',''),
        'typography':spec.get('typography',{}),
        'body_font_size':spec.get('body_font_size',12),
        'heading_font_size':spec.get('heading_font_size',17),
        'layout':spec.get('layout',{}),
        'emphasis':spec.get('emphasis',{}),
        'section_notes':[r for r in spec.get('section_notes',[]) if not headings or r['heading'] in headings],
        'trailing_fields':spec.get('trailing_fields',[])}


def validate_sections(document, project):
    from .report_protocol import RequirementConflict
    contract = heading_contract(project)
    required = contract['required_headings']
    if required and [normalized_heading(s['heading']) for s in document['sections']] != [normalized_heading(h) for h in required]:
        raise RequirementConflict('报告须按模板顺序使用全部章节：' + __import__('json').dumps({
            'field': 'sections.heading', 'origin': contract['origin'], 'expected': required,
            'actual': [s.get('heading') for s in document['sections']]}, ensure_ascii=False))
