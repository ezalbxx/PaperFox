"""Our report document protocol and renderer; ReportLab handles PDF primitives."""
from __future__ import annotations

import base64
import copy
import json
import re
from html import escape
from pathlib import Path

from .jobs import atomic_json
from .lab_project import digest


_FONT_CHOICE = None


def report_font():
    """Embed a real CJK font with math glyphs; retain a portable CID fallback."""
    global _FONT_CHOICE
    if _FONT_CHOICE is not None:return _FONT_CHOICE
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont, TTFError
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    import os
    candidates=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc',
        Path('C:/Windows/Fonts/simsun.ttc'),
        Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
        Path('/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf')]
    for path in candidates:
        if not path.is_file():continue
        try:
            font=TTFont('LabUnicode',str(path),subfontIndex=0)
            if not all(code in font.face.charToGlyph for code in (0x4e2d,0x2212,0xb7)):continue
            pdfmetrics.registerFont(font)
        except (OSError,TTFError):continue
        _FONT_CHOICE=('LabUnicode',{'name':'LabUnicode','embedded':True,'path':str(path),'sha256':digest(path)})
        return _FONT_CHOICE
    if 'STSong-Light' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    _FONT_CHOICE=('STSong-Light',{'name':'STSong-Light','embedded':False,'ascii_math_fallback':True})
    return _FONT_CHOICE

def display_text(value):
    """Present lightweight Markdown as plain report prose; preserve code bytes."""
    lines=[]
    fenced=False
    for line in str(value).split('\n'):
        if re.fullmatch(r'\s*```[\w-]*\s*',line):
            fenced=not fenced
            continue
        if not fenced:
            parts=re.split(r'(`[^`\n]+`)',line)
            line=''.join(part[1:-1] if part.startswith('`') and part.endswith('`')
                         else re.sub(r'\*\*(.+?)\*\*',r'\1',part) for part in parts)
        lines.append(line)
    return '\n'.join(lines)


def typography_fonts():
    """Local Song body / Hei headings, with an explicit portable fallback."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    base,metadata=report_font();result={'body':base,'heading':base,'sources':{}}
    for role,name,path in [('body','PaperFoxSong','C:/Windows/Fonts/simsun.ttc'),
                           ('heading','PaperFoxHei','C:/Windows/Fonts/simhei.ttf')]:
        if not Path(path).is_file():continue
        try:
            if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,path,subfontIndex=0))
            result[role]=name;result['sources'][role]={'path':path,'sha256':digest(path)}
        except (OSError,ValueError):continue
    return result


def validate_document(document, project):
    if not isinstance(document, dict) or not document.get('title') or not document.get('sections'):
        raise ValueError('报告需要title和sections')
    from .lab_template import validate_sections
    validate_sections(document, project)
    seen = set()
    requirements = {r['id'] for r in project.data['requirements']}
    results = set(project.data['results'])
    for section in document['sections']:
        if not section.get('heading') or not section.get('blocks'):
            raise ValueError('每节需要heading与blocks')
        for block in section['blocks']:
            bid = block.get('id', '')
            if not bid or bid in seen:
                raise ValueError('每个报告块需要唯一且稳定的id')
            seen.add(bid)
            if block.get('type', 'text') not in ('text', 'image', 'table', 'code', 'list', 'heading'):
                raise ValueError('不支持的报告块类型')
            invalid_requirements=set(block.get('requirements', []))-requirements
            invalid_evidence=set(block.get('evidence', []))-results
            if invalid_requirements or invalid_evidence:
                raise ValueError('报告块引用了未知要求或实验结果：'+json.dumps({'block_id':bid,
                    'invalid_requirements':sorted(invalid_requirements),'invalid_evidence':sorted(invalid_evidence),
                    'allowed_requirements':sorted(requirements),'allowed_evidence':sorted(results),
                    'instruction':'requirements只用要求ID，evidence只用任务ID；S来源ID放sources元数据。未改变来源的编辑可省略这两字段以继承原关联。'},ensure_ascii=False))
            if block.get('type') == 'image':
                path = project.file(block['path'])
                from .lab_figures import registered_assets
                artifacts = {project.file(a['path']) for a in registered_assets(project)}
                if path not in artifacts or not path.is_file():
                    raise ValueError('图片必须来自已登记的实验产物')
            if block.get('type') == 'table':
                n = len(block.get('headers', []))
                if not n or any(len(r) != n for r in block.get('rows', [])):
                    raise ValueError('表格各行列数必须一致')
    covered = {r for s in document['sections'] for b in s['blocks'] for r in b.get('requirements', [])}
    background={r['id'] for r in project.data.get('report_requirement_contract',{}).get('requirements',[])
                if r.get('presentation_scope')=='background'}
    missing = [r['id'] for r in project.data['requirements'] if r['required'] and r['id'] not in covered and r['id'] not in background]
    if missing:
        raise ValueError('报告未对应必做要求: ' + ', '.join(missing))
    return document


def reference_schema(project,kind):
    """Expose actual metadata ID choices to writers and editors, not prose."""
    ids=([r['id'] for r in project.data['requirements']] if kind=='requirements' else list(project.data['results']))
    return {'type':'array',**({'items':{'type':'string','enum':sorted(ids)}} if ids else
        {'items':{'type':'string'},'maxItems':0})}


def apply_patches(document, patches, allowed_ids):
    updated = copy.deepcopy(document)
    blocks = {b['id']: b for s in updated['sections'] for b in s['blocks']}
    seen = set()
    for patch in patches:
        bid = patch['id']
        if bid not in allowed_ids or bid in seen or bid not in blocks:
            raise ValueError('修改必须对应本轮批注段落，且每段只提交一次')
        seen.add(bid)
        replacement = copy.deepcopy(patch)
        blocks[bid].clear()
        blocks[bid].update(replacement)
    if not patches:
        raise ValueError('需要至少一个段落修改')
    return updated


def table_column_widths(rows, width, font_name, font_size, latin_font=None):
    """Reserve width for complete numeric/Latin tokens before sharing spare space."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    minima=[]
    for index,header in enumerate(rows[0]):
        tokens=[token for row in rows for token in re.findall(r'[A-Za-z0-9_,.()/%+−-]+',display_text(row[index]))]
        measured=[stringWidth(token,latin_font or font_name,font_size) for token in tokens]
        if len(str(header))<=10:measured.append(stringWidth(display_text(header),font_name,font_size))
        for row in rows[1:]:
            value=display_text(row[index])
            if re.fullmatch(r'[0-9.,/%() +−-]+',value):
                measured.append(stringWidth(value,latin_font or font_name,font_size))
        minima.append(max(measured or [font_size*2])+13)
    total=sum(minima)
    if total>width:
        weights=[min(value,width*0.45) for value in minima]
        return [width*value/sum(weights) for value in weights]
    spare=(width-total)/len(minima)
    return [value+spare for value in minima]


def render_report(project, document, *, reason='initial', layout=None, backend='reportlab'):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
    from reportlab.lib.utils import ImageReader

    validate_document(document, project)
    from .figure_quality import asset_quality, placement_check, numbered_document
    from .lab_figures import registered_assets
    assets = {str(project.file(a['path'])): a for a in registered_assets(project)}
    figure_checks = []
    use_ids = document.get('figure_reference_version') == 1 or '{{figure:' in json.dumps(document,ensure_ascii=False)
    figure_reference_repairs = []
    display_document, figure_numbers = numbered_document(document, repairs=figure_reference_repairs) if use_ids else (document, {})
    template = project.data.get('template') or {}
    if layout is None and template.get('typography'):
        from .report_layout import resolve_layout
        layout=resolve_layout(template)
    if layout is not None:
        from .report_layout import validate_layout
        validate_layout(layout,project,document)
    layout=layout or {}
    version = len(project.data['revisions']) + 1
    directory = project.root / 'reports'
    directory.mkdir(exist_ok=True)
    stem = directory / f'report-v{version}'
    atomic_json(stem.with_suffix('.json'), document)
    template = project.data.get('template') or {}
    font_name,font_metadata=report_font()
    typography=template.get('typography',{})
    fonts=typography_fonts() if typography else None
    if fonts:
        font_name=fonts['body'];font_metadata={**font_metadata,'typography_fonts':fonts}
    latin_body = 'Times-Roman' if fonts else None
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font_name
        style.wordWrap = 'CJK'
    template = project.data.get('template') or {}
    margins = template.get('margins', {'left': 56, 'right': 56, 'top': 44, 'bottom': 48})
    page_size = template.get('page_size', A4)
    body_size = template.get('body_font_size', 10.5)
    styles['Normal'].fontSize, styles['Normal'].leading = body_size, body_size * layout.get('body_leading_factor',1.65)
    styles['Normal'].spaceAfter = layout.get('paragraph_space_after',7)
    styles['Normal'].firstLineIndent=body_size*layout.get('first_line_indent_chars',0)
    styles['Normal'].allowWidows = 0
    styles['Normal'].allowOrphans = 0
    if typography:styles['Normal'].alignment=4  # Justified, as in the reference body.
    styles['Title'].fontSize, styles['Title'].leading = 21, 30
    styles['Heading1'].fontSize = template.get('heading_font_size', 14)
    styles['Heading1'].leading = styles['Heading1'].fontSize * 1.65
    styles['Heading1'].spaceBefore = 13
    styles['Heading1'].keepWithNext = True
    styles['Heading2'].fontSize=layout.get('heading2_font_size',12)
    styles['Heading2'].leading=styles['Heading2'].fontSize*1.45
    styles['Heading2'].spaceBefore = 15
    styles['Heading2'].spaceAfter = 6
    styles['Heading2'].keepWithNext = True
    if typography:
        styles['Title'].fontName=fonts['heading'];styles['Title'].fontSize=typography.get('title_font_size',20.5)
        styles['Title'].leading=styles['Title'].fontSize*1.4
        for key in ('Heading1','Heading2'):
            styles[key].fontName=fonts['heading'];styles[key].firstLineIndent=0
            styles[key].textColor=colors.black
    cell = ParagraphStyle('LabCell', parent=styles['Normal'], fontSize=layout.get('table_font_size',9.5), leading=12, firstLineIndent=0)
    caption = ParagraphStyle('LabCaption', parent=styles['Normal'], alignment=1, fontSize=layout.get('caption_font_size',9), leading=13, firstLineIndent=0)
    code_size = layout.get('code_font_size', 10)
    code = ParagraphStyle('LabCode', parent=cell, fontSize=code_size, leading=code_size * 1.35,
                          firstLineIndent=0, backColor=colors.HexColor('#f5f5f5'))
    list_style=ParagraphStyle('LabList',parent=styles['Normal'],firstLineIndent=0)
    width = page_size[0] - margins['left'] - margins['right']
    class RecordedParagraph(Paragraph):
        def split(self, width, height):
            parts=super().split(width,height)
            if parts and hasattr(self,'_lab_block'):
                parts[0]._lab_block=self._lab_block
            return parts
    class RecordedTable(Table):
        def split(self,width,height):
            parts=super().split(width,height)
            if parts and hasattr(self,'_lab_block'):
                parts[0]._lab_block=self._lab_block
            return parts
    def para(text, style=None, literal=False):
        style = style or styles['Normal']
        value=str(text) if literal else display_text(text)
        if font_name=='STSong-Light' and not literal:
            value=value.translate(str.maketrans({'−':'-','·':'*','×':'*'}))
        latin = 'Helvetica-Bold' if fonts and style.name in ('Title','Heading1','Heading2') else latin_body
        if latin and not literal:
            runs = re.split(r'([ -~]+)', value)
            markup = ''.join(f'<font name="{latin}">{escape(run)}</font>' if i % 2 else escape(run)
                             for i, run in enumerate(runs))
        else:
            markup = escape(value)
        return RecordedParagraph(markup.replace('\n', '<br/>'), style)
    pages = {}
    class Document(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            bid = getattr(flowable, '_lab_block', None)
            if bid:
                pages.setdefault(bid, self.page)
            for member in getattr(flowable,'_lab_blocks',[]):pages.setdefault(member,self.page)
    story = [para(document['title'], styles['Title'])]
    # Keep legacy metadata for provenance, but never display a subtitle/note.
    student = project.data.get('student', {'student_id': project.data['student_id']})
    labels = template.get('fields', {})
    student_line = ' ｜ '.join(f'{label}：{student.get(field, "")}' for field, label in labels.items())
    if student_line:
        story.append(para(student_line))
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>' + escape(document['title']) + '</title>',
            '<style>body{max-width:820px;margin:32px auto;padding:0 24px;color:#253025;font:16px/1.85 system-ui}h1{text-align:center;font-size:28px}h2{font-size:21px;margin-top:30px}.block{padding:8px;border-radius:6px;cursor:comment}.block:hover{background:#eef4e9;outline:1px solid #b2c5a4}.caption{text-align:center;font-size:14px;color:#53634c}img{max-width:100%;max-height:620px;display:block;margin:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #ccd5c6;padding:7px;text-align:left}th{background:#fff;border-top:1px solid #222;border-bottom:1px solid #222}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ee;padding:12px}.subtitle{text-align:center;color:#60705b}@media print{.block{padding:0}}</style>',
            '<h1>' + escape(document['title']) + '</h1>']
    if student_line:
        html.append('<p>' + escape(student_line) + '</p>')
    all_blocks={b['id']:b for section in display_document['sections'] for b in section['blocks']}
    grouped={g['block_ids'][0]:g['block_ids'] for g in layout.get('image_groups',[])}
    paired_tail={g['block_ids'][1] for g in layout.get('image_groups',[])}
    for section_index,section in enumerate(display_document['sections']):
        subheading_index=0
        section_heading=section['heading']
        if typography and not re.match(r'^\s*(?:[一二三四五六七八九十]+[、．.]|\d+[、．.])',section_heading):
            numbers=['一','二','三','四','五','六','七','八','九','十']
            section_heading=(numbers[section_index] if section_index<10 else str(section_index+1))+'、'+section_heading
        story.append(para(section_heading, styles['Heading1']))
        html.append('<h2>' + escape(section_heading) + '</h2>')
        for block in section['blocks']:
            if block['id'] in paired_tail:continue
            kind = block.get('type', 'text')
            flows = [];group_members=[]
            if kind == 'table':
                rows = [block['headers'], *block.get('rows', [])]
                table = RecordedTable([[para(c, cell) for c in row] for row in rows],
                              colWidths=table_column_widths(rows,width,font_name,cell.fontSize,latin_body), repeatRows=1,splitInRow=0 if layout else 1)
                table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.white),
                                          ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                                          ('LINEBELOW', (0, 0), (-1, 0), .65, colors.black),
                                          ('BOX', (0, 0), (-1, -1), .65, colors.black),
                                          ('INNERGRID', (0, 0), (-1, -1), .25, colors.HexColor('#8a8a8a')),
                                          ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                          ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
                flows.append(table)
                body = '<table>' + ''.join('<tr>' + ''.join(f'<td>{escape(display_text(c))}</td>' for c in row) + '</tr>' for row in rows) + '</table>'
            elif kind == 'image':
                import mimetypes
                group_members=grouped.get(block['id'],[])
                image_blocks=[all_blocks[bid] for bid in group_members] if group_members else [block]
                gap=layout.get('image_group_gap',14)
                slot=(width-gap)/2 if group_members else width
                panels=[];html_panels=[]
                for image_block in image_blocks:
                    path=project.file(image_block['path']);iw,ih=ImageReader(str(path)).getSize()
                    scale=min(slot/iw,layout.get('image_max_height',450)/ih)
                    quality = asset_quality(project, assets.get(str(path), {}))
                    check = placement_check(quality, iw*scale*25.4/72, layout.get('minimum_figure_font_pt',7))
                    check.update(block_id=image_block['id'], path=image_block['path'])
                    figure_checks.append(check)
                    if check['size_passed'] is False:
                        check['reason'] = f"图片排版后字号{check['effective_font_pt']:.2f}pt过小，建议按最终尺寸重绘"
                    elif check['status'] == 'unverified':
                        check['reason'] = '导入图片缺少经验证的图内排版信息'
                    panel=[Image(str(path),width=iw*scale,height=ih*scale)]
                    if image_block.get('caption'):panel.append(para(image_block['caption'],caption))
                    panels.append(panel)
                    mime=mimetypes.guess_type(path.name)[0] or 'image/png'
                    markup='<img alt="'+escape(image_block.get('caption',''),quote=True)+'" src="data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()+'">'
                    if image_block.get('caption'):markup+='<div class="caption">'+escape(display_text(image_block['caption']))+'</div>'
                    html_panels.append('<div class="block" id="'+escape(image_block['id'],quote=True)+'" data-block-id="'+escape(image_block['id'],quote=True)+'">'+markup+'</div>')
                if group_members:
                    pair=RecordedTable([[panels[0],'',panels[1]]],colWidths=[slot,gap,slot])
                    pair.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
                    pair._lab_blocks=group_members
                    flows=[pair];body='<div class="image-group">'+''.join(html_panels)+'</div>'
                else:
                    flows=panels[0];body=html_panels[0]
            elif kind == 'heading':
                subheading_index+=1
                shown=block.get('text','')
                if layout.get('number_subheadings', True):
                    shown=f'{section_index+1}.{subheading_index} {shown.lstrip()}'
                flows.append(para(shown, styles['Heading2']))
                body = '<h3>' + escape(display_text(shown)) + '</h3>'
            elif kind == 'list':
                flows.extend(para(f'{i}. {text}',list_style) for i, text in enumerate(block.get('items', []), 1))
                body = '<ol>' + ''.join('<li>' + escape(display_text(t)) + '</li>' for t in block.get('items', [])) + '</ol>'
            else:
                if kind=='code' and layout.get('code_preserve_indentation'):
                    value=block.get('text','').expandtabs(4)
                    markup='\n'.join(''.join('<font name="Courier">'+escape(chunk).replace(' ','&#160;')+'</font>' if chunk.isascii() else escape(chunk) for chunk in re.findall(r'[\x00-\x7f]+|[^\x00-\x7f]+',line)) for line in value.split('\n'))
                    flows.append(RecordedParagraph(markup.replace('\n','<br/>'),code))
                else:flows.append(para(block.get('text', ''), code if kind == 'code' else None,literal=kind=='code'))
                body = ('<pre>' + escape(block.get('text', '')) + '</pre>' if kind == 'code' else escape(display_text(block.get('text', ''))).replace('\n', '<br>'))
            if block.get('caption') and kind=='table':
                flows.append(para(block['caption'], caption))
                body+='<div class="caption">'+escape(display_text(block['caption']))+'</div>'
            if flows:
                flows[0]._lab_block = block['id']
            keep_small_table=(kind=='table' and layout and sum(f.wrap(width,10000)[1] for f in flows)<=layout.get('keep_table_max_height',230))
            if kind == 'image' or keep_small_table or (kind == 'text' and flows and
                    flows[0].wrap(width, 10000)[1] <= 3 * styles['Normal'].leading):
                # CJK splitting can leave a single trailing line despite the
                # widow flag. Keep short prose blocks intact across pages.
                flows = [KeepTogether(flows)]
            if flows:
                flows[0]._lab_block = block['id']
                if group_members:flows[0]._lab_blocks=group_members
            story.extend(flows)
            if kind != 'heading':
                story.append(Spacer(1, 6))
            if kind=='image':html.append(body)
            else:html.append('<div class="block '+('prose' if kind=='text' else '')+'" id="' + escape(block['id'], quote=True) + '" data-block-id="' + escape(block['id'], quote=True) + '">' + body + '</div>')
    signature_labels=template.get('signature_labels', [])
    if signature_labels:
        signature_text='    '.join(label+'：________________' for label in signature_labels)
        story.append(KeepTogether([para(signature_text)]))
        html.append('<p style="text-align:right">'+escape(signature_text)+'</p>')
    if layout:html.insert(2,'<style>.image-group{display:grid;grid-template-columns:1fr 1fr;gap:14px;break-inside:avoid}.block{padding:4px}body{line-height:1.5}.prose{text-indent:2em}pre{text-indent:0}.caption{text-indent:0}</style>')
    if typography:
        html.insert(3,'<style>body{font-family:"Times New Roman",SimSun,"Songti SC",serif;font-size:'+str(body_size)+'pt;color:#000;line-height:'+str(layout.get('body_leading_factor',1.5))+'}h1,h2,h3{font-family:Arial,SimHei,"Microsoft YaHei",sans-serif;color:#000;text-indent:0;font-weight:bold}h1{font-size:'+str(styles['Title'].fontSize)+'pt}h2{font-size:'+str(styles['Heading1'].fontSize)+'pt}h3{font-size:'+str(styles['Heading2'].fontSize)+'pt}.prose{text-indent:2em;text-align:justify}.caption{text-indent:0}table{font-family:inherit}</style>')
    html.insert(2, '<style>pre{background:#f5f5f5;color:#222}</style>')
    html.append('</html>')
    stem.with_suffix('.html').write_text('\n'.join(html), encoding='utf-8')
    def footer(canvas, doc):
        canvas.setFont(font_name, 9)
        canvas.drawString(margins['left'], 28, str(project.data['student_id']))
        canvas.drawRightString(page_size[0] - margins['right'], 28, f'第 {doc.page} 页')
    Document(str(stem.with_suffix('.pdf')), pagesize=page_size, leftMargin=margins['left'], rightMargin=margins['right'],
             topMargin=margins['top'], bottomMargin=margins['bottom'], title=document['title']).build(story, onFirstPage=footer, onLaterPages=footer)
    pdf_backend={'backend':'reportlab'}
    if backend=='latex':
        try:
            from .report_latex import render_latex
            pages,pdf_backend=render_latex(project,display_document,template,layout,stem.with_suffix('.pdf'))
        except (RuntimeError,OSError) as exc:
            pdf_backend={'backend':'reportlab','fallback_reason':f'{type(exc).__name__}: {exc}'}
    if template.get('cover_page'):
        import fitz
        with fitz.open(project.file(template['source'])) as original, fitz.open(stem.with_suffix('.pdf')) as body_pdf:
            merged = fitz.open()
            index = template['cover_page'] - 1
            merged.insert_pdf(original, from_page=index, to_page=index)
            merged.insert_pdf(body_pdf)
            raw = merged.tobytes(garbage=3, deflate=True)
            preview = original[index].get_pixmap(matrix=fitz.Matrix(1, 1)).tobytes('png')
            merged.close()
        stem.with_suffix('.pdf').write_bytes(raw)
        html.insert(2, '<img class="template-cover" alt="原报告模板封面" src="data:image/png;base64,' + base64.b64encode(preview).decode() + '">')
        stem.with_suffix('.html').write_text('\n'.join(html), encoding='utf-8')
        pages = {bid: page + 1 for bid, page in pages.items()}
    from .report_student_voice import check_student_voice
    student_voice = check_student_voice(document)
    for check in figure_checks:
        check['page'] = pages.get(check['block_id'])
    for issue in student_voice['issues']:
        issue['page'] = pages.get(issue['block_id'])
    manifest = {'version': version, 'document': document, 'reason': reason,
                'student_voice_check': student_voice,
                'pdf_backend': pdf_backend,
                'figure_numbers': figure_numbers,
                'figure_reference_repairs': figure_reference_repairs,
                'figure_qa': {'status': 'checked' if all(c['status']=='checked' and c['size_passed'] is True and c.get('language')=='zh' for c in figure_checks) else 'needs_attention',
                              'figures':figure_checks, 'minimum_font_basis':'项目暂定7pt，可由模板minimum_figure_font_pt覆盖',
                              'scope':'记录选用资产的已执行几何检查及最终放置字号；不等于完整视觉或语义审核'},
                'pdf': str(stem.with_suffix('.pdf').relative_to(project.root)),
                'html': str(stem.with_suffix('.html').relative_to(project.root)),
                'sha256': digest(stem.with_suffix('.pdf')), 'block_pages': pages, 'template': template,'font':font_metadata,'layout':layout,
                'provenance': {bid: {'requirements': b.get('requirements', []), 'evidence': b.get('evidence', [])}
                               for s in document['sections'] for b in s['blocks'] for bid in [b['id']]}}
    atomic_json(stem.with_suffix('.manifest.json'), manifest)
    project.data['report'] = manifest
    project.data['revisions'].append({'version': version, 'pdf': manifest['pdf'], 'reason': reason})
    project.save()
    return manifest
