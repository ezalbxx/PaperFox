"""Final template layout contract, separate from scientific content and prose edits."""
from __future__ import annotations
import copy,json,re

LAYOUT_VERSION=7
FORMAT_PROMPT="""你是最终模板排版角色。正文和数据已冻结，本轮只提交版面安排，不改正文、图注、数据或章节顺序，不执行实验。
依据模板、图表尺寸及block_inventory，把相邻且适合比较的两张图安排side_by_side。
只组合adjacent_image_candidates列出的成对图片；用途是训练前后/条件对照，不为省页数组合无关主题。
模板规定的字号、纸张、页边距由程序固定，不允许你修改。其他行距/缩进/表格分页由确定性排版器执行。
最多3组；没有合适组合时image_groups=[]。用finish_stage提交{"image_groups":[{"block_ids":["a","b"],"reason":"为何适合并排比较"}],"summary":"仅说明版面选择"}。
"""

def format_schema():
    return {'type':'object','properties':{'image_groups':{'type':'array','maxItems':3,'items':{'type':'object','properties':{
        'block_ids':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'string'}},'reason':{'type':'string'}},'required':['block_ids','reason']}},'summary':{'type':'string'}},'required':['image_groups','summary']}

def inventory(project,document):
    from PIL import Image
    from .lab_figures import registered_assets
    from .figure_quality import asset_quality
    assets = {str(project.file(a['path'])): a for a in registered_assets(project)}
    items=[];pairs=[]
    for section in document['sections']:
        blocks=section['blocks']
        for i,b in enumerate(blocks):
            row={'id':b['id'],'type':b['type'],'section':section['heading']}
            if b['type']=='image':
                with Image.open(project.file(b['path'])) as im:row.update(width_px=im.width,height_px=im.height)
                row['caption']=b.get('caption','')
                row['figure_quality'] = asset_quality(project, assets.get(str(project.file(b['path'])), {}))
                if i+1<len(blocks) and blocks[i+1]['type']=='image':pairs.append([b['id'],blocks[i+1]['id']])
            elif b['type']=='table':row.update(columns=len(b['headers']),rows=len(b.get('rows',[])),headers=b['headers'])
            elif b['type']=='code':row['lines']=len(b.get('text','').splitlines())
            elif b['type']=='heading':row['text']=b['text']
            items.append(row)
    return {'block_inventory':items,'adjacent_image_candidates':pairs}

def validate_plan(plan,project,document):
    allowed={tuple(p) for p in inventory(project,document)['adjacent_image_candidates']};used=set()
    groups=plan.get('image_groups')
    if not isinstance(groups,list) or len(groups)>3:raise ValueError('image_groups需要0—3组成对相邻图片')
    for group in groups:
        ids=group.get('block_ids',[])
        if tuple(ids) not in allowed or used.intersection(ids) or not group.get('reason'):raise ValueError('只能将本章相邻且未重复的图片并排，保留原ID和图注')
        used.update(ids)
    return plan

def resolve_layout(template,plan=None):
    template=template or {};explicit=copy.deepcopy(template.get('layout',{}))
    defaults={'body_leading_factor':1.8,'first_line_indent_chars':2,'paragraph_space_after':6,
              'heading2_font_size':12,'caption_font_size':9,'table_font_size':12,'code_font_size':10,
              'image_max_height':300,'image_group_gap':14,'keep_table_max_height':520,
              'number_subheadings':True,'code_preserve_indentation':True,
              'minimum_figure_font_pt':7}
    return {'version':LAYOUT_VERSION,**defaults,**explicit,'table_caption_position':'below','image_groups':copy.deepcopy((plan or {}).get('image_groups',[])),
            'locked_template_fields':{k:copy.deepcopy(template[k]) for k in ('headings','page_size','margins','body_font_size','heading_font_size','cover_page','fields','signature_labels') if k in template},
            'notice':'Template fields have priority. This contract changes display only; content JSON and original assets remain unchanged.'}


def recover_plan(plan,project,document):
    """Optional image pairing may fail without invalidating the manuscript."""
    try:
        validate_plan(plan,project,document)
        return plan
    except (ValueError,TypeError,KeyError) as exc:
        fallback={'image_groups':[],'summary':'Single-column fallback','fallback':str(exc)}
        if isinstance(plan,dict):plan.clear();plan.update(fallback);return plan
        return fallback

def content_hash(document):
    import hashlib
    return hashlib.sha256(json.dumps(document,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()

def validate_layout(layout,project,document):
    plan=recover_plan({'image_groups':layout.get('image_groups',[])},project,document)
    layout['image_groups']=plan['image_groups']
    from .figure_quality import placement_check
    items = {row['id']: row for row in inventory(project, document)['block_inventory']}
    template = project.data.get('template') or {}
    margins = template.get('margins', {'left':56, 'right':56})
    # Match the renderer's A4 default, or an explicit custom page tuple.
    page_size = template.get('page_size', (595.2756, 841.8898))
    page_width = page_size[0] if isinstance(page_size, (list, tuple)) else 595.2756
    slot = (page_width - margins.get('left',56) - margins.get('right',56) - layout.get('image_group_gap',14)) / 2
    kept=[]; rejected=[]
    for group in layout['image_groups']:
        checks=[placement_check(items[bid].get('figure_quality', {}), slot*25.4/72, layout.get('minimum_figure_font_pt',7)) for bid in group['block_ids']]
        if any(check['size_passed'] is False for check in checks):
            rejected.append({'block_ids':group['block_ids'], 'reason':'并排后字号过小，改整行', 'checks':checks})
        else:
            kept.append(group)
    layout['image_groups']=kept
    layout['rejected_image_groups']=rejected
    explicit=(project.data.get('template') or {}).get('layout',{})
    from .report_protocol import RequirementConflict
    for key,low,high,default in [('body_leading_factor',1,2.2,1.5),('image_max_height',120,420,300)]:
        value=layout.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not low<=value<=high:
            if key in explicit:raise RequirementConflict(f'模板版面值无效：{key}={value!r}，允许{low}—{high}，未覆盖用户约束')
            layout[key]=default
    return layout
