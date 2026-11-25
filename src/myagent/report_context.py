"""Small, source-addressable report packets and bounded document edits.

Authored here. DSH inspired prune-before-summary and separate archive/surface;
no DSH runtime or code is imported. Original requirements and events stay on disk.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

from .report_section_policy import DEFENSIVE_TRANSITION


CONTEXT_VERSION = 39
REPORT_LIMITS = {'max_steps': 400, 'max_cost': 1.0, 'max_seconds': 7200}


def sentence_tail(text,count=2):
    sentences=re.findall(r'.+?(?:[。！？!?]|\.(?=\s|$)|$)',text,re.S)
    return ' '.join(s.strip() for s in sentences[-count:] if s.strip())


def paragraph_reflow_context(document,block_ids):
    selected=set(block_ids);all_blocks=[(s['heading'],b) for s in document['sections'] for b in s['blocks']]
    contexts=[]
    for index,(heading,block) in enumerate(all_blocks):
        if block['id'] not in selected:continue
        prior=all_blocks[index-1][1] if index else None
        prose=next((b for _,b in reversed(all_blocks[:index]) if b['type']=='text'),None)
        following=all_blocks[index+1][1] if index+1<len(all_blocks) else None
        contexts.append({'block_id':block['id'],'heading':heading,'original_paragraph':block['text'],
            'previous_block':{'id':prior['id'],'type':prior['type'],'tail':sentence_tail(prior.get('text',''))} if prior else None,
            'previous_prose':{'id':prose['id'],'tail':sentence_tail(prose['text']),
                'rewritten_in_this_request':prose['id'] in selected} if prose else None,
            'next_block':{'id':following['id'],'type':following['type'],'entry':following.get('text','')[:180]} if following else None})
    return contexts


def validate_paragraph_reflows(result,document,tasks):
    wanted={t['block_id'] for t in tasks};patches=result.get('patches')
    if not isinstance(patches,list) or len(patches)!=len(wanted) or {p.get('target_id') for p in patches}!=wanted:
        raise ValueError('每个选中正文块必须提交一次完整段落重写，不能遗漏、重复或越界')
    notes=result.get('reflow_notes')
    if not isinstance(notes,list) or len(notes)!=len(wanted) or {n.get('block_id') for n in notes}!=wanted:
        raise ValueError('每个重流段落须给entry_bridge和judgment后台说明')
    before={b['id']:b for s in document['sections'] for b in s['blocks']}
    for note in notes:
        if not all(isinstance(note.get(k),str) and note[k].strip() for k in ('entry_bridge','judgment')):
            raise ValueError('承接和判断说明不能为空')
    for patch in patches:
        block=patch.get('block',{});bid=patch['target_id']
        if patch.get('op')!='replace' or block.get('id')!=bid or block.get('type')!='text':
            raise ValueError('整段重流只接受完整text块替换，不接受单句删改、删除、插入或移动')
        text=block.get('text','')
        if not isinstance(text,str) or not text.strip() or text==before[bid]['text'] or '\n\n' in text:
            raise ValueError('提交与原文不同的完整自然段，不以修稿说明或整章拼接代替')
        if '综上所述' in text or DEFENSIVE_TRANSITION.search(text):
            raise ValueError('整段重流不能引入机械套话或防御性铺垫')


def prune_repeated_results(messages):
    """Remove only exact duplicate observations, keeping the latest full copy."""
    updated=list(messages);seen={};removed=[]
    for i in range(len(messages)-1,1,-1):
        msg=messages[i]
        if msg.get('role')!='tool' or len(msg.get('content',''))<2000:continue
        content=msg['content'];key=hashlib.sha256(content.encode()).hexdigest()
        try:
            result=json.loads(content)
        except (ValueError, TypeError):
            continue
        if not isinstance(result,dict) or result.get('returncode')!=0 or result.get('error'):
            continue
        if key in seen:
            updated[i]={**msg,'content':json.dumps({'returncode':0,'output':
                f'Exact duplicate observation. Full identical result retained later at tool_call_id={seen[key]}.',
                'source_sha256':key,'error':'','truncated':False})}
            removed.append({'tool_call_id':msg['tool_call_id'],'retained_call_id':seen[key],'sha256':key})
        else:seen[key]=msg['tool_call_id']
    return updated,removed


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def compact_contract(packet):
    """Remove repeated page bodies/DOM dumps, never requirement text or quotes."""
    packet = copy.deepcopy(packet)
    for rule in packet.get('requirements', []):
        rule.pop('source_page_text', None)
        rule.pop('historical_acceptance', None)  # Archive old interpretations without re-injecting them into writing.
    for capture in packet.get('capture_catalog', []):
        capture.pop('dom_text', None)
    packet['original_contract_path'] = 'outputs/requirements-contract.json'
    return packet


def writing_continuity(design, section_index, part_index, previous_blocks, completed_sections):
    """Bounded prose continuity, distinct from factual source evidence."""
    previous = previous_blocks
    if not previous and completed_sections:
        # Core chapters may be generated first: continuity follows template order.
        before={s['heading'] for s in design['sections'][:section_index]}
        preceding=[s for s in completed_sections if s['heading'] in before]
        if preceding:previous=preceding[-1].get('blocks', [])
    text_blocks = [b for b in previous if b.get('type') in ('text', 'heading')]
    tail = [{'id': b['id'], 'type': b['type'], 'text': b.get('text', '')[-600:]}
            for b in text_blocks[-3:]]
    sections = design['sections']
    parts = sections[section_index]['parts']
    following = parts[part_index+1] if part_index+1 < len(parts) else (
        sections[section_index+1]['parts'][0] if section_index+1 < len(sections) else {})
    return {'main_thread': design.get('main_thread', ''), 'previous_blocks': tail,
            'next_part': {k: following[k] for k in
                          ('focus', 'question', 'main_claim', 'why_here') if k in following}}


def document_units(document, max_chars=6000, max_blocks=12):
    """Each unit belongs to a section/subheading; IDs survive stitching/resume."""
    units = []
    for si, section in enumerate(document['sections']):
        current, size, subheading = [], 0, ''
        for block in section['blocks']:
            length = len(json.dumps(block, ensure_ascii=False))
            if current and (block.get('type') == 'heading' or size + length > max_chars or len(current) >= max_blocks):
                units.append({'section': si, 'heading': section['heading'], 'subheading': subheading, 'blocks': current})
                current, size = [], 0
            if block.get('type') == 'heading':
                subheading = block.get('text', '')
            current.append(block)
            size += length
        if current:
            units.append({'section': si, 'heading': section['heading'], 'subheading': subheading, 'blocks': current})
    return units


def assign_issues(units, issues):
    assigned = [[] for _ in units]
    for issue in issues:
        block_ids = set(issue.get('block_ids', []))
        matches = [i for i, u in enumerate(units) if block_ids.intersection(b['id'] for b in u['blocks'])]
        if matches:
            # A located cross-paragraph issue belongs to every affected unit.
            for index in matches:
                assigned[index].append(issue)
            continue
        if not matches:
            topics = re.findall(r'Q\d+', issue.get('rule_id', '') + ' ' + issue.get('reason', ''))
            def heading_topics(text):
                found=set(re.findall(r'Q\d+',text))
                for a,b in re.findall(r'Q(\d+)\s*[-—–~～至到]+\s*Q?(\d+)',text):
                    lo,hi=int(a),int(b)
                    if 0<=hi-lo<=100:found.update(f'Q{n}' for n in range(lo,hi+1))
                return found
            candidates=[(len(heading_topics(u['subheading'])),i) for i,u in enumerate(units)
                if set(topics).intersection(heading_topics(u['subheading']))]
            matches=[i for _,i in sorted(candidates)]
        if not matches:
            matches = [i for i, u in enumerate(units) if any(
                issue.get('rule_id') in b.get('requirements', []) for b in u['blocks'])]
        # An unlocated requirement can be addressed in a small final section;
        # never send the entire draft back just because block_ids is empty.
        assigned[matches[0] if matches else len(units)-1].append(issue)
    return assigned


def apply_local_patches(document, patches, allowed_ids, locked_ids=()):
    updated = copy.deepcopy(document)
    locked_ids = set(locked_ids)
    existing = {b['id'] for s in updated['sections'] for b in s['blocks']}
    replaced, removed, insertions, moves = set(), set(), {}, {}
    for patch in patches:
        target, op = patch['target_id'], patch['op']
        if target not in allowed_ids or target not in existing:
            raise ValueError('补丁只能定位本轮候选块：' + target)
        if target in removed:
            raise ValueError('不能再次修改或在已删除块后插入：' + target)
        if op == 'move_after':
            anchor = patch.get('after_id')
            if target in locked_ids or target in moves:
                raise ValueError('不能移动已锁定块或重复移动同一块：' + target)
            if anchor == target or anchor not in allowed_ids or anchor not in existing or anchor in removed:
                raise ValueError('移动位置after_id必须是本轮其他仍保留的候选块')
            moves[target] = anchor
            continue
        if op == 'merge':
            sources = patch.get('merge_ids')
            if (not isinstance(sources, list) or not 1 <= len(sources) <= 8
                    or any(not isinstance(bid, str) for bid in sources)
                    or len(set(sources)) != len(sources) or target in sources):
                raise ValueError('merge_ids需要1—8个不含target_id且不重复的原文段落ID')
            members = [target, *sources]
            if any(bid not in allowed_ids or bid not in existing for bid in members):
                raise ValueError('合并只能使用本轮候选块')
            if any(bid in locked_ids or bid in replaced or bid in insertions or bid in moves for bid in members):
                raise ValueError('不能合并已锁定、已修改或用作本轮定位的块')
            originals = {b['id']: b for s in updated['sections'] for b in s['blocks']}
            block = copy.deepcopy(patch.get('block'))
            if (any(originals[bid].get('type') != 'text' for bid in members)
                    or not isinstance(block, dict) or block.get('type') != 'text'
                    or block.get('id') != target or not isinstance(block.get('text'), str)
                    or not block['text'].strip()):
                raise ValueError('merge只合并text段落，保留目标ID并提供合并后的text；图表、标题和代码保持独立')
            # The model edits prose; the controller retains all source/requirement links.
            merged = {**originals[target], **block}
            for field in ('requirements', 'evidence'):
                links = [rid for bid in members for rid in originals[bid].get(field, [])]
                if links or field in block:
                    merged[field] = list(dict.fromkeys([*links, *block.get(field, [])]))
            for section in updated['sections']:
                section['blocks'] = [merged if b['id'] == target else b for b in section['blocks']]
            replaced.update(members)
            removed.update(sources)
            continue
        if op == 'link_requirements':
            if target in locked_ids or target in replaced:
                raise ValueError('不能修改已锁定块或重复修改要求关联')
            requirements = patch.get('requirements')
            if not isinstance(requirements, list) or any(not isinstance(rid, str) for rid in requirements):
                raise ValueError('link_requirements需要requirements字符串数组')
            for section in updated['sections']:
                for old in section['blocks']:
                    if old['id'] == target:
                        old['requirements'] = list(dict.fromkeys([*old.get('requirements', []), *requirements]))
            replaced.add(target)
            continue
        if op == 'delete':
            if target in locked_ids or target in replaced or target in insertions or target in moves:
                raise ValueError('不能删除已锁定块、重复修改块或本轮插入的定位块')
            removed.add(target)
            replaced.add(target)
            continue
        block = copy.deepcopy(patch.get('block'))
        if not isinstance(block, dict):
            raise ValueError('replace或insert_after需要block对象')
        if op == 'replace':
            if target in locked_ids or target in replaced or block.get('id') != target:
                raise ValueError('替换保留原ID，不能修改已锁定块或重复替换')
            for section in updated['sections']:
                for i, old in enumerate(section['blocks']):
                    if old['id'] == target:
                        for field in ('requirements', 'evidence'):
                            if field not in block and field in old:
                                block[field] = copy.deepcopy(old[field])
                        section['blocks'][i] = block
            replaced.add(target)
        elif op == 'insert_after':
            bid = block.get('id')
            if not bid or bid in existing:
                raise ValueError('新增块必须使用未占用的唯一ID：'+str(bid)+'；该内容若已在preserved_section_blocks中则勿再插入，否则使用new_block_id_prefix')
            existing.add(bid)
            insertions.setdefault(target, []).append(block)
        else:
            raise ValueError('只支持replace、insert_after、delete、link_requirements、merge或move_after')
    for section in updated['sections']:
        section['blocks'] = [item for b in section['blocks'] if b['id'] not in removed for item in [b, *insertions.get(b['id'], [])]]
    for target, anchor in moves.items():
        if anchor in removed:
            raise ValueError('移动位置after_id已被删除或合并：' + anchor)
        block = next(b for s in updated['sections'] for b in s['blocks'] if b['id'] == target)
        for section in updated['sections']:
            section['blocks'] = [b for b in section['blocks'] if b['id'] != target]
        for section in updated['sections']:
            for index, old in enumerate(section['blocks']):
                if old['id'] == anchor:
                    section['blocks'].insert(index + 1, block)
                    break
    return updated


PATCH = '''你是报告局部修订角色。candidate只包含本轮可改的小节/片段，其他正文由控制器保留。
只提交必要补丁，不重交全文，不把整节正文塞进一个text块。无需修改时patches=[]。
mode=requirements时只处理requirement_feedback的明确缺项，mode=editing时改善本片段逻辑、重复和图文衔接。
已有截图未采用不是学生缺材料。capture_catalog给出的同题同类真实图片可直接插入；多页截图按part/total理解，不能把提问图当回答图、转录当真实截图，也不能声称已检查像素。
新增图放在解释它的对应题目附近，用明确图注说明内容；无需把其他主题的截图塞入本小节。
上下文只给本轮事实和证据，未知数字按需用report_materials读取，不重新审计所有资料、不运行实验。
replace使用原块ID；insert_after使用新的唯一ID；delete仅提供op和target_id，用于删去无新增信息的重复段、图注或小标题。只能定位editable_block_ids，不能修改或删除locked_blocks。删除前保留仍需的证据和要求关联，可在本轮其他保留块中合并；同一块不能同时删除和替换/插入。
merge用于把重复text段落收束在一个目标段：target_id为保留位置，merge_ids为其余1—8个现有段落ID，block只需目标id/type=text及合并后text。控制器自动汇集各段requirements/evidence并删除被吸收段，保留全部必要事实与推导，不把不相关事实强拼在一起。图表/标题/代码不得合并，不能跨出editable_block_ids。
move_after只提供target_id和after_id，在本轮可改范围内把原块移到另一原块之后；原ID、来源和内容保留，可另用replace改同一块的图注。移动不需要复制block，不用插入副本再删除原图。目标位置after_id不能在同轮删去或被合并。
adopted_figures是candidate实际采用的图片及来源；旧figure_outputs仅是可用或计划目录，不能覆盖较新的实际采用版本。允许用有来源的已登记新版替换图片，不能因修正文删掉该图。
保留已正确的正文、数据与证据，禁止把大段现有内容再复制进新增块。只返回变更。
preserved_section_blocks是本章已存在但不在本轮编辑范围内的内容摘要，控制器会保留；不能因为candidate没显示图表就当成缺失并重复插入。当前只改editable_block_ids。确需新增块时，用new_block_id_prefix开头的唯一ID。
结果协议：{"patches":[{"op":"replace|insert_after|delete|link_requirements|merge|move_after","target_id":"现有块ID","block":{"id":"块ID","type":"text|heading|image|table|code|list", ...}}]}。
delete补丁不需要block；link_requirements只提供target_id和requirements数组，仅附加关联ID、不复制或改动其他字段。用finish_stage提交。'''


STRUCTURE_EDIT = """你是正文删减与信息移位编辑。只处理本次requirement_feedback，按用户明确要求实际修改，不写评审或核查建议。
对于PNG像素核查、阈值擦边假设、自我削弱和免责段落，直接delete整段；保留的实验结论用现有预测、曲线和实际方法解释。
对于重复数字或变量密集的正文，保留操作目的、选择理由、关键发现与解释；必要参数/数值由已有表图承担，无关细节删除，不把它们转存为代码。不要仅删一两个数字后保留原来的罗列结构。
同一事实在结果与分析重复时保留主要位置，其他段落删除或压缩为有新信息的解释。不得把取证、自检、可复现性核查当成正文主题。
无需保留与用户新规则冲突的旧措辞和旧摘要。sources/evidence/requirements属于后台关联，控制器继承；不要在正文解释为什么删改。
本轮可改范围是editable_block_ids，其他块由控制器保留。保留关键实验与教师必做内容及必要图表；代码默认省略，只有教师明确要求报告内展示或核心机制不可替代时保留最短片段。
只用finish_stage提交patches数组，每项含op和target_id；delete无需block，replace保留原id并给完整新block，insert_after需新id。只提交改动，禁止原样replace。
"""
