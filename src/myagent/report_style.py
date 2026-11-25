"""Genre/section-specific positive examples, isolated from experiment facts."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from .report_section_policy import section_roles

STYLE_GUIDANCE = '''报告正文采用学生实验实施者的叙述身份，用简洁、准确的书面语叙述问题、操作、观察和理解；编排和编辑角色按此指导或检查正文。
学生视角不等于多写“我”；不以教师、评分者、教程讲解者或Agent开发者身份宣讲课程评价、验收清单、写作安排。
避免“弄清三件事”“放心交给”“先跑通再说”等聊天、劝说或授课式措辞。自然衔接依靠内容关系，不靠设问、口号或人为戏剧化。
教师要求由后台用于覆盖检查；正文直接完成相应实验与解释。目的节交代实验问题和学习目标，不介绍评价标准或承诺如何得分。
style_reference中只有用户指定的正面范例及自动提炼经验；按文体和章节学习组织方式，不复制旧模型、操作、数据、成绩、署名或个人经历。
本轮明确要求优先于范例；范例含代码/详细配置不代表本次也需要。lesson是模型提炼、尚未逐条人工核查，可查看调整。'''
STYLE_GUIDANCE += '''
写作的起点是当前实验问题、实际材料和教师模板。范例只帮助表达当前内容，不决定本次必须出现什么操作、结果或结论。
先组织本次要表达的内容，再参考示例改善叙述；不沿用示例的句子骨架逐词替换模型名，不补写示例中有而本次未做的步骤。
不照搬范例的章节标题、数量、篇幅比例或固定论证顺序；同一写法只在适合当前问题时使用。
没有匹配的范例时按章节职责自主组织，不勉强套用。principles_only模式只提供可借鉴经验，none模式不提供案例；均以当前事实为依据。'''

SELECTION_VERSION = 2

SOURCE_NAMING_GUIDANCE = """用用户指定的名称或指导书中的正式名称指代实验对象；无正式名称时，按对象或用途命名。
README、运行说明和文件名中的作者称呼、临时简称和内部标签用于定位材料；其中的解释以原始实验记录为准。旧事实包、提纲和图表计划中的内部称呼同样按正式名称或用途转换。小标题、正文、表格和图注用名一致。需要交代来源时写“实验材料提供的”。原始引文、路径、证据编号和数据原样保留。"""

def normalize_sample_names(text):
    """Use neutral names for numbered test programs in visible report prose."""
    text = re.sub(r'(?:老师|教师)(?:的|原始)?测试(?:程序)?(?=[一二三四五六七八九十0-9])',
                  '测试程序', text)
    return re.sub(r'(?:老师|教师)(?:的|原始)?样例', '实验材料中的样例', text)


def normalize_block_sample_names(block):
    if block.get('type') in ('text', 'heading') and 'text' in block:
        block['text'] = normalize_sample_names(block['text'])
    if block.get('type') in ('table', 'image') and 'caption' in block:
        block['caption'] = normalize_sample_names(block['caption'])
    if block.get('type') == 'list' and 'items' in block:
        block['items'] = [normalize_sample_names(item) for item in block['items']]


def normalize_quote(text):
    return re.sub(r'[\W_]+','',text,flags=re.UNICODE).casefold()

def near_duplicate_quote(left,right):
    left,right=normalize_quote(left),normalize_quote(right)
    if not left or not right:return False
    if left==right:return True
    return SequenceMatcher(None,left,right,autojunk=False).ratio()>=0.80

def library_path():
    configured=os.environ.get('MYAGENT_REPORT_STYLE_LIBRARY')
    return Path(configured) if configured else Path(__file__).resolve().parents[3]/'.myagent/report-style-library.json'

def library_for(project):
    if 'report_style_library' not in project.data:
        path=library_path()
        if not path.is_file():return {'version':1,'cards':[],'profiles':[]}
        raw=path.read_bytes();bank=json.loads(raw)
        project.data['report_style_library']={**bank,'sha256':hashlib.sha256(raw).hexdigest()}
    return project.data['report_style_library']

def genre_for(project):
    # Explicit project intent only; examples never change the report's genre.
    if project.data.get('report_genre'):
        return project.data['report_genre']
    title=project.data.get('title','')
    for phrase,genre in [('开题','proposal'),('中期','progress_report'),('结题','final_report')]:
        if phrase in title:return genre
    return 'lab_report'

def target_roles(payload):
    context=payload.get('context',{})
    heading=payload.get('target_heading') or (context.get('heading') if isinstance(context,dict) else None)
    if not heading:
        candidate=payload.get('candidate',payload.get('document',{}))
        sections=candidate.get('sections',[]) if isinstance(candidate,dict) else []
        if len(sections)==1:heading=sections[0].get('heading')
    if not heading:
        plan=payload.get('part_plan',{})
        if isinstance(plan,dict):heading=plan.get('heading')
    return section_roles(heading) if heading else []

def style_packet(project, role, payload, *, max_chars=4600):
    roles={'report_designer','writer','report_patcher','report_requirement_reviewer','reviewer','selection_editor'}
    if role not in roles:return {}
    bank=library_for(project);genre=genre_for(project)
    mode=project.data.get('style_reference_mode','examples')
    if mode not in ('examples','principles_only','none'):raise ValueError('Unknown style_reference_mode')
    excluded=set(project.data.get('style_excluded_source_ids',[]))
    wanted=target_roles(payload)
    selection_key='|'.join((str(project.id),str(bank.get('sha256','')),genre,role,','.join(wanted)))
    stable_order=lambda identity:hashlib.sha256((selection_key+'|'+identity).encode()).hexdigest()
    profiles=[p for p in bank.get('profiles',[]) if p['genre']==genre and p.get('source',{}).get('id',p['id']) not in excluded]
    template_roles={r for heading in (project.data.get('template') or {}).get('headings',[]) for r in section_roles(heading)}
    profiles.sort(key=lambda p:(-len(template_roles.intersection(p.get('section_roles',[]))),stable_order(p['id'])))
    cards=[c for c in bank.get('cards',[]) if c['genre']==genre and c.get('acceptance_status')=='user_designated_positive'
           and c['source']['id'] not in excluded]
    focus=json.dumps({k:payload.get(k) for k in ('focus','target_heading','part_plan','requirement_feedback')},ensure_ascii=False).casefold()
    if wanted:cards=[c for c in cards if c['section_role'] in wanted and wanted!=['support']]
    elif role in ('writer','selection_editor','report_designer') or not any(
            isinstance(payload.get(key),dict) and payload[key].get('sections') for key in ('candidate','document')):
        cards=[]
    # No topic-only fallback across chapter roles. Editorial whole-report packets use representative roles.
    cards=sorted(cards,key=lambda c:(-sum(len(k) for k in c.get('keywords',[]) if k.casefold() in focus),stable_order(c['id'])))
    if mode=='none':cards=[]
    selected=[];used=0;seen_roles=set();seen_sources=set()
    for card in cards:
        if not wanted and card['section_role'] in seen_roles:continue
        if card['source']['id'] in seen_sources:continue
        if any(near_duplicate_quote(card['positive_quote'],previous['positive_quote']) for previous in selected):continue
        public={k:copy.deepcopy(card[k]) for k in ('id','genre','section_role','heading','positive_quote','lesson','source','acceptance_status','lesson_origin','reviewed')}
        size=len(json.dumps(public,ensure_ascii=False))
        if used+size>max_chars:continue
        selected.append(public);used+=size;seen_sources.add(card['source']['id']);seen_roles.add(card['section_role'])
        if len(selected)>=(3 if not wanted else 2):break
    if mode=='principles_only':
        selected=[{k:v for k,v in item.items() if k not in ('positive_quote','heading')} for item in selected]
    return {'version':bank['version'],'library_sha256':bank.get('sha256'),'genre':genre,
        'selection_version':SELECTION_VERSION,'mode':mode,'excluded_source_ids':sorted(excluded),
        'current_section_roles':wanted,'profiles':copy.deepcopy(profiles[:2]) if role=='report_designer' and mode=='examples' else [],
        'examples':selected,'usage':'参考当前问题适用的表达方式；不复用原句骨架、章节配比、旧实验事实或验收判据。匹配不足可少给或不给。来源id/sha256/page仅作追溯。'}
