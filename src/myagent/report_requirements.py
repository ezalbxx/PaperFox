"""Authored requirement contracts and bounded report feedback, without execution tools."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from .jobs import atomic_json
from .lab_project import now
from .report_writing import profile_for


REQUIREMENT_REVIEW = '''你是报告要求反馈角色。只根据给定合同和本阶段草稿检查，不执行实验、不搜索、不审计历史。
先检查文章是否交代清楚实验对象、问题和各项任务的关系，是否围绕任务展开过程与分析，再处理篇幅和措辞。
重点关注各章职责、段落引入、解释深度和跨章重复。反馈引用具体段落，给出可直接执行的修改方向。
修复建议直接改正或删除错误结论，保留有依据的观察和必要机制，不用“可能/不能说明/尚未验证”替换为防御段落，不追加实验。
统计曲线和机制图可依据真实数据制图，provenance留后台；不因重绘本身要求图注增加“重绘、已核验、非截图”小字。只有教师明确要求真实界面截图时才检查capture来源。
用户本轮明确指令优先。presentation_scope=background的日志交付、自检等由后台材料承担，不要求正文增加目录映射、自检表或未核验说明；acceptance中的旧正文位置建议不覆盖用户新要求。禁止为解除假想质疑添加防御段落、审计、额外消融或核查代码。
逐项判断本阶段相关教师要求与用户决定是否实际得到满足，不能因为段落声明了R编号就算覆盖。
sample只检查sample_scope内的内容，不要求补全文；截图、日志、源码的来源关系以capture_catalog元数据为准。
outline阶段检查要求是否安排到具体章节及证据，不要求提纲已经包含完整正文、逐题答案或最终提交自检结论；正文阶段再检查实际完成内容。明确计划只做一题而其余不做仍属缺项。
source_context.teacher_pages给出引用页完整原文，原文优先于acceptance的解释；不可把短quote只摘一题误判为原始指导书缺其余题干。
source_context.supplied_files是已登记的真实材料目录。缺少正文安排、目录中已有但尚未使用、材料确实缺失分别判断；目录不完整时不能从未列出推出不存在。
已安排的问答在提纲中概括要点和来源即可，不能因为改写题干或没有逐字列题而判缺项。现有分析已覆盖检查点或问答时，不强制新增重复小节。三个实验各自v0/v1即三组对照，不凭“三轮”推导必须第三版本。
按标题和内容判断实验归属；T1/E1等目录名本身不构成“没有按实验留痕”的证据，不新增教师未规定的目录命名门槛。
教师原话允许截图/grep、截图/entry id的替代时保留替代；用户另外要求真实截图时按用户要求检查，不伪称是教师原话。
检查：事实有依据、章节承担相应职责、机制解释清楚、图文对应、没有越过样稿范围、用户已认可的选择得到执行。代码默认省略，不要求为机制解释补代码。
hard用于明确的教师/用户要求缺漏、数据或证据不对应、实质逻辑错误。用户本轮明确禁止的W01防御段落与W06正文细节堆列，识别到具体违规时按用户要求处理，不降为泛泛偏好；普通措辞润色才是soft。historical_acceptance仅存旧摘要，不作为要求，不能据此要求像素核查。
缺项判断须引用要求原话，并说明当前稿确实缺了什么；已经写出的核对判定与理由算核对内容，不能仅因没单列一列就判缺失。
“自己的核对”不自动等于必须另跑一次实验、必须由学生亲自grep；
capture_catalog的evidence_ref.line是定位锚点，不是截图起止范围。没有像素或范围证据时，不得断言“截图只有这一行”“其他行未截到”。
正文定义行与截图调用行可以不同；只在二者被明确混同且有直接矛盾证据时判hard。无法确认的疑问标soft并说明未验证。
不能声称看过图片像素，不新增双人核验/统计检验/审计脚本等任务，不要求重跑已完成实验。
adopted_figures.grounding区分原图元数据与有来源的制图规格。source_json_values中的数字、标签及render_spec支持相应数值比较、坐标方向或标注格式说明，这些不等于声称目检像素；不得仅以未目检否定有数据/规格依据的读图解释。无遮挡、裁剪正确、字号可读等版面结论仍需像素证据。image_metadata_only不提供图内语义；数据比较可另据evidence中的原始数值，不推断图像外观。内部核验状态不要求写进正文或图注。
实际模板以template.headings为准，不用“模板通常怎样”替代；available_figure_outputs是已存在图表清单，稿中漏放不等于学生未提供。
document.title就是正式报告标题，确定性排版器会把它作为PDF标题输出。字段已有正确标题时，不要求在正文块重复同名标题；“需要确认最终PDF呈现”或没有目检PDF不构成内容缺项。版面查验由最终格式阶段处理，只有给定内容或实际渲染证据存在明确矛盾时才定位hard。
真实的划分、预处理、训练与评价顺序是实验过程，参考资料是出处，不把它们都当成来源自证；来源自证指反复说明谁执行、已核验或未重跑。
要求原话中的“建议、约、目标”保持建议强度，不能以acceptance摘要将它升级为硬性门槛。
依据evidence中有来源的事实检查数值与解释，数学定义支持的直接推导不自动需要额外实验；提炼中的interpretation仍是解释，不自动成为实测事实。没有特征位置或决策轨迹证据时，不能把具体错例说成边界点、离群点或已确认的因果机制。
adopted_figures是本稿实际图片，available_figure_outputs是可用/旧计划目录；优先核对实际采用版本及provenance。图的版式修复与版本沿革保留元数据，不要求图注增加“修复版、已核验”等自证说明。
最多4条具体问题，每条引用现有block_id（提纲可用空数组）和rule_id，给出最小修改。
结果协议：{"issues":[{"rule_id":"要求ID或writing:clarity","severity":"hard|soft","block_ids":["真实块ID"],
"reason":"具体缺项与已有依据","suggestion":"本轮怎样改","needs_material":false}],"summary":"简短结论"}。
已满足则issues=[]；只用finish_stage。'''


def topics_in(text):
    text=text or '';found=list(dict.fromkeys(re.findall(r'Q\d+',text)))
    for lo,hi in re.findall(r'Q(\d+)\s*[-—–~～至到]+\s*Q?(\d+)',text):
        if 0<=int(hi)-int(lo)<=100:
            found.extend(f'Q{i}' for i in range(int(lo),int(hi)+1) if f'Q{i}' not in found)
    return found


class ReportRequirements:
    def __init__(self,project):
        self.project=project
        self._captures=None

    def captures(self):
        if self._captures is not None:return self._captures
        sources=self.project.data.get('report_sources',[]);inventory={}
        for source in sources:
            if Path(source['path']).suffix.lower()=='.json' and 'screenshot_inventory' in Path(source['path']).name.lower():
                for row in json.loads(self.project.file(source['path']).read_text(encoding='utf-8')):
                    inventory[str(row.get('file','')).replace('\\','/').casefold()]=row
        captures=[]
        for source in sources:
            if Path(source['path']).suffix.lower() not in ('.png','.jpg','.jpeg'):continue
            meta=source.get('capture') or inventory.get(str(source.get('original','')).replace('\\','/').casefold(),{})
            if not meta:
                # A library snapshot relocates files. Match unique longest path
                # suffix, never infer capture truth from an image filename alone.
                local=str(source['path']).replace('\\','/').casefold().split('/')
                candidates=[]
                for original,row in inventory.items():
                    parts=original.split('/');score=0
                    for a,b in zip(reversed(local),reversed(parts)):
                        if a!=b:break
                        score+=1
                    if score>=2:candidates.append((score,row))
                candidates.sort(key=lambda item:-item[0])
                if candidates and (len(candidates)==1 or candidates[0][0]>candidates[1][0]):meta=candidates[0][1]
            if not meta.get('is_real_capture'):continue
            subject=meta.get('subject','');label=source.get('label','')
            role=next((r for r in ('answer','source','prompt') if r in subject.lower()),'result')
            question=meta.get('question') or next(iter(topics_in(label+' '+subject)),None)
            captures.append({'id':source['id'],'path':source['path'],'label':label,'role':role,'topic':question,
                'session_id':meta.get('session_id'),'seq':meta.get('seq'),'physical_line':meta.get('physical_line'),
                'part':meta.get('part'),'total':meta.get('total'),'is_real_capture':True,
                'evidence_ref':meta.get('evidence_ref'),'dom_text':meta.get('dom_text','')[:2400],
                'notice':'Capture registry/text metadata; pixels have not been inspected by this role.'})
        self._captures=captures;return captures

    def ensure(self):
        p=self.project;documents_path=p.root/'materials.json'
        documents=json.loads(documents_path.read_text(encoding='utf-8'))['documents'] if documents_path.exists() else []
        pages={(d['material_id'],page['page']):page['text'] for d in documents for page in d.get('pages',[])}
        requirements=[]
        for requirement in p.data.get('requirements',[]):
            row=copy.deepcopy(requirement);source=row.get('source',{})
            row['source_page_text']=pages.get((source.get('material_id'),source.get('page')),'')
            if p.data.get('report_architecture_version',1)>=2:
                quote=source.get('quote','')
                if quote:
                    row['historical_acceptance']=row.get('acceptance','')
                    row['acceptance']=quote
                    row['acceptance_basis']='教师原文及本轮用户指令；历史摘要不作为额外验收条件'
                background=('报告' not in quote and '正文' not in quote and (
                    '[ ]' in quote or ('jsonl' in quote.lower() and any(w in quote for w in ('提交','保留','日志')))))
                row['presentation_scope']='background' if background else 'body'
                if background:
                    row['report_acceptance']='在后台保存现有原始材料和必要记录；不要求正文说明目录差异、自检状态或额外核查。'
            row['required_for_project']=row.get('required',False) or (row.get('category')=='bonus' and p.data.get('include_bonus',False))
            requirements.append(row)
        profile=profile_for(p)
        contract={'version':1,'requirements':requirements,'preferences':copy.deepcopy(p.data.get('report_preferences',{})),
            'writing_rules':[{'id':'writing:clarity','level':'soft','text':'先讲清观察和机制，再用必要代码/行号支撑，避免只列符号。'},
                {'id':'writing:evidence','level':'hard','text':'真实截图、生成机制图、源码转录分别标注，不互相冒充；证据对应同题同次运行。'},
                {'id':'writing:decisions','level':'hard','text':'遵守本人已经确认的范围、篇幅和心得写法；不反复询问已答问题。'},
                {'id':'writing:figures','level':'soft','text':'图表帮助正文解释，避免冗余和无用途的插图。'}],
            'human_decisions':[{k:r[k] for k in ('stage','text','decision') if k in r}
                for r in p.data.get('report_workflow',{}).get('interactions',[])],
            'loop_policy':{'max_repairs':2,'no_progress':'stop_with_specific_gaps','soft_issues':'display_without_forced_rewrite'},
            'notice':'Runtime requirement feedback, not teacher grading or model training.'}
        contract['writing_rules'].extend(copy.deepcopy(profile['rules']))
        from .report_section_policy import policy_packet
        contract['section_policy']=policy_packet(p)
        contract['writing_profile']={'version':profile['version'],'sha256':profile['sha256']}
        p.data['report_requirement_contract']=contract
        folder=p.root/'outputs';folder.mkdir(exist_ok=True)
        atomic_json(folder/'requirements-contract.json',contract);p.save();return contract

    def slots(self,topics=None):
        if not self.project.data.get('report_preferences',{}).get('require_result_screenshots'):return []
        catalog=self.captures()
        topics=topics if topics is not None else list(dict.fromkeys(c['topic'] for c in catalog if c['topic']))
        slots=[]
        for topic in topics:
            for role,label in (('answer','回答/运行结果'),('source','源码核对')):
                candidates=[c for c in catalog if c['topic']==topic and c['role']==role]
                slots.append({'id':f'capture:{topic}:{role}','topic':topic,'role':role,
                    'label':f'{topic} 的真实{label}截图','candidate_ids':[c['id'] for c in candidates],
                    'origin':copy.deepcopy(self.project.data['report_preferences'].get('source',{'kind':'user'}))})
        return slots

    def packet(self,stage,topics=None):
        contract=self.project.data.get('report_requirement_contract') or self.ensure()
        from .report_section_policy import policy_packet
        slots=self.slots(topics)
        selected={sid for slot in slots for sid in slot['candidate_ids']}
        return {'stage':stage,'scope_topics':topics,'requirements':contract['requirements'],
            'section_policy':policy_packet(self.project),
            'writing_rules':contract['writing_rules'],'preferences':contract['preferences'],'human_decisions':contract['human_decisions'],
            'proof_slots':slots,'capture_catalog':[c for c in self.captures() if c['id'] in selected],
            'loop_policy':contract['loop_policy'],'notice':'Source alternatives and user screenshot policy are distinct; check only this stage.'}

    def check(self,stage,document,*,topics=None):
        issues=[];catalog=self.captures();by_path={str(self.project.file(c['path'])):c for c in catalog}
        from .report_section_policy import structural_issues
        if stage in ('sample','writing','editing','delivery'):issues.extend(structural_issues(document))
        used_ids=set();blocks=[b for s in document.get('sections',[]) for b in s.get('blocks',[])]
        if stage=='outline':
            used_ids={sid for f in document.get('figure_plan',[]) if f.get('kind')=='screenshot' for sid in f.get('source_ids',[])}
        else:
            for b in blocks:
                if b.get('type')=='image':
                    capture=by_path.get(str(self.project.file(b['path'])))
                    if capture:used_ids.add(capture['id'])
            if stage=='sample' and topics:
                for b in blocks:
                    texts=[b.get('text','')] if b.get('type')=='heading' else [str(row[0]) for row in b.get('rows',[]) if row]
                    outside=set(topics_in(' '.join(texts)))-set(topics)
                    if outside:issues.append({'code':'sample_scope','rule_id':'writing:decisions','severity':'hard',
                        'block_ids':[b['id']],'reason':'样稿范围超出已认可题目：'+','.join(sorted(outside)),
                        'suggestion':'只保留本次样稿范围 '+','.join(topics),'needs_material':False})
            if stage in ('writing','editing','delivery'):
                covered={rid for b in blocks for rid in b.get('requirements',[])}
                contract=self.project.data.get('report_requirement_contract') or self.ensure()
                for rule in contract['requirements']:
                    if rule['required_for_project'] and rule.get('presentation_scope')!='background' and rule['id'] not in covered:
                        issues.append({'code':'missing_requirement','rule_id':rule['id'],'severity':'hard','block_ids':[],
                            'reason':'尚未覆盖：'+rule['text'],'suggestion':'在对应章节补充有实际证据的内容','needs_material':False})
        fulfilled=[]
        for slot in self.slots(topics):
            matches=used_ids.intersection(slot['candidate_ids'])
            if matches:fulfilled.append({'slot_id':slot['id'],'source_ids':sorted(matches),'label':slot['label']})
            else:issues.append({'code':'missing_capture','rule_id':slot['id'],'slot_id':slot['id'],'severity':'hard',
                'block_ids':[],'reason':('已有素材尚未用于正文：' if slot['candidate_ids'] else '材料中尚未找到：')+slot['label'],
                'asset_state':'available_not_used' if slot['candidate_ids'] else 'missing_material',
                'suggestion':'从candidate_ids选取对应原图并插入正文，提问图与转录不抵充',
                'candidate_ids':slot['candidate_ids'],'needs_material':not bool(slot['candidate_ids'])})
        return {'status':'needs_material' if any(i['needs_material'] for i in issues) else 'needs_revision' if issues else 'satisfied',
            'issues':issues,'fulfilled':fulfilled,'stage':stage,'at':now(),'semantic_review':'not_run'}
