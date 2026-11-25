'use strict';
// Real editing is server-backed. Explicit ?demo=1 remains an isolated UI example.
const $=id=>document.getElementById(id);
const query=new URLSearchParams(location.search);
let workspace=query.get('workspace')||'', project=query.get('project')||'';
let manuscript,original,reportVersion=0,previewKey='',saved={},activeId='',selection=null,pdfURL='',sending=false;
let live=false,editorBusy=false,refreshingEditor=false,threadRenderKey='',pollTimer;
const copy=value=>JSON.parse(JSON.stringify(value));
const make=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
const uid=()=>crypto.randomUUID();
const SAMPLE={title:'神经网络图像分类实验',subtitle:'从训练过程到结果分析 · 用一份示例文稿体验改稿',sections:[
 {heading:'一、实验目的',blocks:[{id:'sample-purpose',type:'text',text:'本实验围绕图像分类任务，观察神经网络如何在训练中逐步形成分类能力，并结合训练曲线分析模型的学习过程。重点记录关键操作的目的、训练中的变化，以及这些变化与最终表现之间的关系。'}]},
 {heading:'二、实验方法',blocks:[{id:'sample-method-title',type:'heading',text:'2.1 从输入图像到类别预测'},
 {id:'sample-method',type:'text',text:'训练代码中设置了学习率、批大小和训练轮数，调用优化器完成梯度更新，使用损失函数计算误差，并在每轮记录训练集与验证集指标。随后通过若干变量保存预测结果、损失和准确率，最后将这些内容输出为曲线和表格。'},
 {id:'sample-process',type:'text',text:'训练过程按数据准备、参数更新和验证三个阶段组织。数据准备阶段先完成输入与标签的配对；训练阶段根据预测误差更新参数；验证阶段使用独立数据观察模型表现。正文需要解释这些阶段怎样支撑实验目标，具体配置适合集中放入表格。'},
 {id:'sample-method-title-2',type:'heading',text:'2.2 通过曲线理解训练过程'},
 {id:'sample-curves',type:'text',text:'只比较最后一个训练结果，容易忽略模型是在什么阶段发生变化的。因此，报告保留每轮训练与验证的曲线，并结合关键阶段的变化展开分析。曲线承担完整趋势，正文着重解释值得关注的现象。'}]},
 {heading:'三、结果与分析',blocks:[{id:'sample-results',type:'text',text:'结果部分应先说明最重要的发现，再用图表提供依据，并联系训练中的操作解释原因。同一组数据只在主要位置完整展示，后续分析围绕新的问题展开，避免把表格逐行复述成段落。'},
 {id:'sample-defense',type:'text',text:'为了证明本次实验是正确可靠的，还需要说明这并不是偶然得到的结果，而是经过充分检查之后的结论。虽然已有实验现象，但这些现象不能完全说明模型已经达到了预期目标。'}]},
 {heading:'四、实验总结',blocks:[{id:'sample-conclusion',type:'text',text:'总结回到实验最初的问题，概括通过关键过程观察到的变化，以及这些发现对后续实验选择的启发。具体数据由结果部分承载，这里保留值得带走的判断。'}]}
]};
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,4600);}
async function api(route,params={}){const r=await fetch(route+'?'+new URLSearchParams({workspace,...params}));const v=await r.json();if(!r.ok)throw Error(v.error||'无法读取报告');return v;}
async function post(route,data){const r=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace,project,...data})});const v=await r.json();if(!r.ok)throw Error(v.error||'操作未完成');return v;}
function fileURL(path){return '/api/lab/file?'+new URLSearchParams({workspace,project,path});}
function persist(){if(!live)saved.document=manuscript;saved.updatedAt=new Date().toISOString();try{localStorage.setItem(previewKey,JSON.stringify(live?{drafts:saved.drafts||{},candidateDrafts:saved.candidateDrafts||{},outbox:saved.outbox,updatedAt:saved.updatedAt}:saved));if(!live)$('saveStatus').textContent='预览稿已保存在本机';}catch{toast('浏览器未能暂存输入，请复制尚未发送的内容。');}}
function setupDocument(reportDocument,{version=0,pdf='',sample=false,server=false}={}){
 live=server;
 original=copy(reportDocument);reportVersion=version;pdfURL=pdf;previewKey='paperfox-ui-preview-v1:'+workspace+':'+(sample?'sample':project)+':'+version;
 if(live)previewKey='paperfox-editor-drafts-v1:'+workspace+':'+project;
 try{saved=JSON.parse(localStorage.getItem(previewKey)||'{}');}catch{saved={};}
 manuscript=copy(live?reportDocument:saved.document||reportDocument);saved.threads=saved.threads||[];saved.memories=saved.memories||[];saved.drafts=saved.drafts||{};saved.candidateDrafts=saved.candidateDrafts||{};
 activeId='';selection=null;closeDiscussion();$('sidebarTitle').replaceChildren(make('span',sample?'神经网络图像分类实验':reportDocument.title),make('small',sample?'示例文稿 · 交互体验':`原报告 v${version} · 正式报告`));
 $('breadcrumbTitle').textContent=reportDocument.title;$('pdfLink').hidden=!pdf;$('pdfLink').href=pdf;$('pdfTab').disabled=!pdf;
 $('documentSource').textContent=live?'正式报告 · 修改按版本保存':sample?'示例文稿 · 非实验结果':'真实报告 · 浏览器预览副本';$('saveStatus').textContent=live?'报告已保存 · v'+version:saved.updatedAt?'已恢复本机预览稿':'原稿已读取 · 可开始选句';
 if(live){$('previewNotice').querySelector('p').textContent='选中文字，和纸狐讨论改法；点击采用后更新报告与 PDF，自动整理本次修改中的写作经验。';$('previewNotice').querySelector('span').textContent='✦';document.querySelector('.preview-badge').textContent='● DeepSeek 已接入';document.querySelector('.composer-bottom span').textContent='DeepSeek · 对话自动保存';$('resetPreview').title='刷新正式报告';$('resetPreview').setAttribute('aria-label','刷新正式报告');}
 else{$('previewNotice').querySelector('p').textContent='这是隔离的交互演示，回复为预设示例，修改仅保存在本浏览器。';document.querySelector('.preview-badge').textContent='交互演示';$('resetPreview').title='还原当前预览稿';$('resetPreview').setAttribute('aria-label','还原当前预览稿');}
 renderPaper(sample);renderThreads();switchView('reading');
}
function renderPaper(sample=previewKey.includes(':sample:')){
 const paper=$('paper');paper.replaceChildren();
 if(sample)paper.append(make('div','示例文稿','sample-callout'));
 paper.append(make('h1',manuscript.title));
 $('outline').replaceChildren();let count=0;
 manuscript.sections.forEach((section,si)=>{
  const id='section-'+si,h=make('h2',section.heading);h.id=id;paper.append(h);
  const a=make('a',section.heading.replace(/^[一二三四五六七八九十\d]+[、.．]\s*/,''));a.href='#'+id;$('outline').append(a);
  section.blocks.forEach(block=>{
   let element;const kind=block.type||'text';
   if(kind==='text'){element=make('p',block.text||'');element.dataset.editable='true';element.dataset.section=si;count+=Array.from(block.text||'').length;}
   else if(kind==='heading'){element=make('h3',block.text||'');}
   else if(kind==='image'){element=make('figure');const img=make('img');img.src=fileURL(block.path);img.alt=block.caption||'实验图';img.loading='lazy';element.append(img,make('figcaption',block.caption||'','figure-caption'));}
   else if(kind==='table'){element=make('table');if(block.caption)element.append(make('caption',block.caption));const head=make('thead'),tr=make('tr');for(const v of block.headers||[])tr.append(make('th',String(v)));head.append(tr);const body=make('tbody');for(const row of block.rows||[]){const r=make('tr');for(const v of row)r.append(make('td',String(v)));body.append(r);}element.append(head,body);}
   else if(kind==='code'){element=make('pre',block.text||'');}
   else if(kind==='list'){element=make('ol');for(const value of block.items||[])element.append(make('li',value));}
   else return;
   element.dataset.blockId=block.id;element.id='block-'+block.id;
   if(saved.threads.some(t=>t.applied&&t.anchor.some(s=>s.blockId===block.id)))element.classList.add('revised');paper.append(element);
  });
 });
 if(sample)paper.append(make('p','这是一份为界面体验准备的示例文稿，没有引用真实测量结果。其中特意保留了参数堆列、防御性表达等修改对象。','paper-note'));
 $('wordCount').textContent=count.toLocaleString()+' 字';
}
function switchView(view){$('readerView').hidden=view!=='reading';$('pdfView').hidden=view!=='pdf';$('readingTab').setAttribute('aria-selected',view==='reading');$('pdfTab').setAttribute('aria-selected',view==='pdf');if(view==='pdf'&&pdfURL&&$('pdfFrame').getAttribute('src')!==pdfURL)$('pdfFrame').src=pdfURL;$('selectionAction').hidden=true;}
function captureSelection(){
 if(!$('discussionDrawer').hidden||$('readerView').hidden)return;
 const s=window.getSelection();if(!s||s.isCollapsed||!s.rangeCount){$('selectionAction').hidden=true;return;}
 const range=s.getRangeAt(0),paper=$('paper');if(!paper.contains(range.startContainer)||!paper.contains(range.endContainer)){return;}
 const blocks=[...paper.querySelectorAll('[data-editable]')].filter(e=>range.intersectsNode(e));
 if(!blocks.length){$('selectionAction').hidden=true;return;}
 const section=blocks[0].dataset.section;if(blocks.some(b=>b.dataset.section!==section)){toast('请在同一章节中选择连续正文。');return;}
 const all=manuscript.sections[Number(section)].blocks,first=all.findIndex(b=>b.id===blocks[0].dataset.blockId),last=all.findIndex(b=>b.id===blocks.at(-1).dataset.blockId);
 if(all.slice(first,last+1).some(b=>(b.type||'text')!=='text')){toast('这版先支持连续正文选句；请避开中间的图表和标题。');return;}
 const anchor=blocks.map(e=>{
  const start=e.contains(range.startContainer)?(()=>{const p=range.cloneRange();p.selectNodeContents(e);p.setEnd(range.startContainer,range.startOffset);return p.toString().length;})():0;
  const end=e.contains(range.endContainer)?(()=>{const p=range.cloneRange();p.selectNodeContents(e);p.setEnd(range.endContainer,range.endOffset);return p.toString().length;})():e.textContent.length;
  return {blockId:e.dataset.blockId,section:Number(section),start,end,original:e.textContent,quote:e.textContent.slice(start,end)};
 }).filter(a=>a.end>a.start);
 if(!anchor.length||!anchor.map(a=>a.quote).join('').trim())return;
 selection={anchor,quote:anchor.map(a=>a.quote).join('\n\n')};
 const rect=range.getBoundingClientRect(),button=$('selectionAction');button.hidden=false;button.style.left=Math.min(window.innerWidth-230,Math.max(75,rect.left+rect.width/2-100))+'px';button.style.top=Math.max(8,rect.top-45)+'px';
}
function currentThread(){return saved.threads.find(t=>t.id===activeId);}
function openDiscussion(id){
 activeId=id;const t=currentThread();if(!t)return;
 $('selectedQuote').textContent=t.quote;$('selectionLocation').textContent=manuscript.sections[t.anchor[0].section]?.heading||'原文位置';
 $('discussionDrawer').hidden=false;document.body.classList.add('discussion-open');$('selectionAction').hidden=true;window.getSelection()?.removeAllRanges();
 $('discussionInput').value=live?saved.drafts[t.id]||'':t.draft||'';threadRenderKey='';renderConversation();setTimeout(()=>$('discussionInput').focus(),120);
}
async function createDiscussion(){if(!selection)return;if(live){try{selection.client_id=selection.client_id||uid();const t=await post('/api/lab/report/discussion',{action:'create',anchor:selection.anchor,version:reportVersion,client_id:selection.client_id});await refreshEditor();openDiscussion(t.id);}catch(e){toast(e.message);await refreshEditor();}return;}const t={id:uid(),anchor:copy(selection.anchor),quote:selection.quote,messages:[],createdAt:new Date().toISOString(),applied:false};saved.threads.push(t);persist();renderThreads();openDiscussion(t.id);}
function closeDiscussion(){$('discussionDrawer').hidden=true;document.body.classList.remove('discussion-open');$('selectionAction').hidden=true;}
function renderThreads(){
 $('threadCount').textContent=saved.threads.length;const list=$('threadList');list.replaceChildren();
 if(!saved.threads.length){list.append(make('p','选中一句话，开始第一次讨论。','empty-small'));return;}
 for(const t of [...saved.threads].reverse()){const b=make('button',undefined,'thread-item');b.title=t.quote;b.append(make('span',t.applied?'✓':'◦','thread-dot'),document.createTextNode(t.quote.slice(0,24)));b.onclick=()=>openDiscussion(t.id);list.append(b);}
}
function renderConversation(){
 const thread=currentThread(),area=$('conversation');area.replaceChildren();if(!thread)return;
 $('discussionInput').disabled=thread.applied;$('sendMessage').disabled=thread.applied||sending||(live&&(editorBusy||!!thread.pending));$('suggestions').hidden=thread.messages.length>0||thread.applied;
 if(!thread.messages.length){const welcome=make('div',undefined,'chat-welcome');welcome.append(make('span','✦','welcome-symbol'),make('h3','你读到这里，哪里卡住了？'),make('p','可以是几个字不顺、一句话没讲清，也可以是整段的思路。先说你的感受，再一起试一个新版本。'));area.append(welcome);}
 for(const message of thread.messages){
  const wrap=make('section',undefined,'message '+message.role),author=make('div',undefined,'message-author');
  author.append(make('span',message.role==='user'?'Y':'','tiny-avatar '+(message.role==='assistant'?'fox-avatar':'')),make('span',message.role==='user'?'你':live?'纸狐 · DeepSeek':'纸狐 · 演示'),make('time',new Date(message.at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})));wrap.append(author,make('div',message.text,'message-text'));
  if(message.candidate!==undefined){
   const card=make('div',undefined,'candidate'),head=make('div',undefined,'candidate-head');head.append(make('span','候选改稿 '+message.revision),make('span','可直接编辑'));
   const content=make('textarea',undefined,'candidate-text');content.value=live?(saved.candidateDrafts[message.id]??message.edited_text??message.candidate):message.candidate;content.setAttribute('aria-label','候选改稿 '+message.revision);content.disabled=thread.applied||(live&&editorBusy);
   content.oninput=()=>{if(live)saved.candidateDrafts[message.id]=content.value;else message.candidate=content.value;persist();};
   const details=make('details'),summary=make('summary','为什么这样改');details.append(summary,make('p',message.reason));
   const buttons=make('div',undefined,'candidate-actions');buttons.append(make('span',thread.applied&&thread.acceptedId===message.id?'你采用了这个版本':'只替换选中的内容'));
   const accept=make('button',thread.applied?(thread.acceptedId===message.id?'已采用':'未采用'):live&&!content.value?'删除选中文字 ↗':'采用这一版 ↗');if(live){const keepDraft=content.oninput;content.oninput=()=>{keepDraft();accept.textContent=content.value?'采用这一版 ↗':'删除选中文字 ↗';};if(!content.value)content.placeholder='这一版将删除选中的文字。';}accept.disabled=thread.applied||(live&&(sending||editorBusy||!!thread.pending));accept.onclick=()=>acceptCandidate(message.id);buttons.append(accept);card.append(head,content,details,buttons);wrap.append(card);
  }area.append(wrap);
 }
 if(live&&thread.pending){const note=make('div',thread.error||({turn:'纸狐正在结合原文与讨论尝试改稿…',accept:'正在更新报告、重新排版并整理写作经验…',learn:'正在整理本次写作经验…',undo:'正在恢复上一版内容并重新排版…'}[thread.pending.kind]),'accepted-note');if(!editorBusy){const retry=make('button','继续这个请求');retry.onclick=()=>runLiveAction('resume');note.append(retry);}else{const pause=make('button','暂停这个请求');pause.onclick=async()=>{try{await post('/api/lab/pause',{});toast('已请求暂停，已有对话和修改会保留。');}catch(e){toast(e.message);}};note.append(pause);}area.append(note);}
 if(thread.applied){const note=make('div',undefined,'accepted-note');note.append(document.createTextNode(live?'✓ 已更新正式报告与 PDF，旧版仍保留。':'✓ 已写入预览稿。改稿和讨论都已保存。'));const undo=make('button','撤销本次采用');undo.disabled=live&&editorBusy;undo.onclick=undoApply;note.append(undo);if(live&&thread.learning?.status==='failed'){note.append(make('p','报告已更新；经验提炼暂未完成：'+thread.learning.error));const retry=make('button','重试经验提炼');retry.disabled=editorBusy;retry.onclick=()=>runLiveAction('learn');note.append(retry);}else if(live&&thread.learning?.summary)note.append(make('p',thread.learning.summary));area.append(note);}
 area.scrollTop=area.scrollHeight;
}
function demoReply(thread,feedback){
 const revision=thread.messages.filter(m=>m.role==='assistant').length+1;
 const latest=thread.messages.filter(m=>m.candidate!==undefined).at(-1),source=latest?.candidate||thread.quote;
 let candidate=source,reason='这是未连接模型的交互预览。这里保留原句作为可编辑候选，用于体验对话、采用和回看经验；你也可以直接在候选框里填写理想版本。',text='收到。先把候选放在这里，你可以直接改字，也可以继续告诉我哪里不满意。正式接入后，这一步会由 Agent 结合原文和讨论生成。',lesson='对局部内容先讨论、再修改；保留用户采用的表达和上下文。';
 if(thread.quote===SAMPLE.sections[1].blocks[1].text){
  const variants=['训练按参数更新与验证两个环节推进：先根据预测误差调整参数，再观察模型在验证数据上的表现。每轮记录的指标用于呈现这一过程，具体配置集中放在表格中。','每轮训练先根据预测误差更新参数，再用验证数据观察模型的变化。报告结合这些记录解释训练过程，具体参数由配置表承载。','为观察模型怎样逐步形成分类能力，训练过程中持续记录参数更新后的表现，并用验证数据跟踪变化。具体配置放入表格，正文围绕关键阶段和观察展开。'];
  candidate=variants[Math.min(revision-1,2)];text=revision===1?'这段先后报出了参数、函数和产物，但操作的目的没有串起来。下面用一个预设改稿演示：把训练和验证的关系放到前面，细节交给表格。':'继续往你说的方向收一收。这里换一个预设版本，试试哪种组织更接近你的习惯。';reason='先交代关键操作之间的关系，再说明指标记录的用途；具体参数不占用正文。当前为预设示例，尚未依据真实实验材料生成。';lesson='解释训练过程时，先说明关键操作的目的和关系；完整配置放表格，正文不逐项转述参数与接口。';
 }else if(thread.quote===SAMPLE.sections[2].blocks[1].text){
  candidate=revision===1?'实验结论围绕已有观察展开：说明关键现象，结合训练过程解释变化，并回答实验最初提出的问题。':'结合训练过程解释关键现象，再据此回答实验问题。';reason='删除可靠性自证和假想质疑，让正文服务于实验发现与解释。此处为预设示例，未添加新的实验结论。';lesson='实验正文直接呈现观察、解释和判断，删除可靠性自证、假想质疑和免责式铺垫。';text='这段主要在解释为什么值得相信，真正的实验发现被挤到了后面。可以把这部分篇幅还给观察和解释。下面是预设改稿示例。';
 }
 if(/^[“"「]/.test(feedback)&&/[”"」]$/.test(feedback.trim())){candidate=feedback.trim().slice(1,-1);text='把你给出的措辞放进候选框了。你可以继续调整，或采用这一版。';reason='采用你在引号内明确提供的措辞；仍需由你点击采用后才写入预览稿。';}
 return {id:uid(),role:'assistant',text,candidate,reason,lesson,revision,at:new Date().toISOString(),origin:'ui_demo'};
}
async function sendMessage(event){
 event?.preventDefault();const t=currentThread(),text=$('discussionInput').value.trim();if(!t||!text||sending||t.applied)return;
 if(live){const candidate=[...t.messages].reverse().find(m=>m.candidate!==undefined);await runLiveAction('turn',{text,...(candidate?{candidate_text:saved.candidateDrafts[candidate.id]??candidate.edited_text??candidate.candidate}:{})});return;}
 t.messages.push({id:uid(),role:'user',text,at:new Date().toISOString()});t.draft='';$('discussionInput').value='';persist();renderConversation();
 // No API or simulated model latency: all preview messages identify their origin.
 t.messages.push(demoReply(t,text));persist();renderConversation();renderThreads();
}
async function acceptCandidate(messageId){
 const t=currentThread(),message=t?.messages.find(m=>m.id===messageId);if(!message||t.applied)return;
 if(live){await runLiveAction('accept',{message_id:messageId,replacement:saved.candidateDrafts[messageId]??message.edited_text??message.candidate});return;}
 if(!message.candidate.trim()){toast('候选内容为空，请先填写要采用的文字。');return;}
 const section=manuscript.sections[t.anchor[0].section];
 for(const a of t.anchor){if(section.blocks.find(b=>b.id===a.blockId)?.text!==a.original){toast('这段原文已经变化，请重新选择后讨论，已有对话会保留。');return;}}
 const first=t.anchor[0],last=t.anchor.at(-1),index=section.blocks.findIndex(b=>b.id===first.blockId),tailIndex=section.blocks.findIndex(b=>b.id===last.blockId);
 t.undoDocument=copy(manuscript);const replacement=first.original.slice(0,first.start)+message.candidate+last.original.slice(last.end);
 const kept=section.blocks[index];kept.text=replacement;
 if(t.anchor.length>1){for(const field of ['requirements','evidence'])kept[field]=[...new Set(section.blocks.slice(index,tailIndex+1).flatMap(b=>b[field]||[]))];section.blocks.splice(index+1,tailIndex-index);}
 t.applied=true;t.acceptedId=message.id;t.acceptedAt=new Date().toISOString();
 saved.memories.push({id:uid(),threadId:t.id,before:t.quote,after:message.candidate,lesson:message.lesson,at:t.acceptedAt,origin:'ui_demo'});
 persist();renderPaper();renderThreads();renderConversation();toast('已采用到预览稿，并保存了一条可核查的经验。');
}
async function undoApply(){
 if(live){await runLiveAction('undo');return;}
 const t=currentThread();if(!t?.applied||!t.undoDocument)return;
 const lastApplied=saved.threads.filter(row=>row.applied).sort((a,b)=>b.acceptedAt.localeCompare(a.acceptedAt))[0];
 if(lastApplied?.id!==t.id){toast('请先撤销后面采用的修改，避免覆盖其他改稿。');return;}
 manuscript=copy(t.undoDocument);t.applied=false;delete t.acceptedId;delete t.undoDocument;saved.memories=saved.memories.filter(m=>m.threadId!==t.id);
 persist();renderPaper();renderThreads();renderConversation();toast('已撤销采用，讨论仍然保留。');
}
$('selectionAction').onpointerdown=e=>e.preventDefault();$('selectionAction').onclick=createDiscussion;
document.addEventListener('pointerup',e=>{if($('paper').contains(e.target))setTimeout(captureSelection,0);});
document.addEventListener('keyup',e=>{if(e.key==='Shift')captureSelection();if(e.key==='Enter'&&!$('selectionAction').hidden){e.preventDefault();createDiscussion();}});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#selectionAction')&&!$('paper').contains(e.target))$('selectionAction').hidden=true;});
window.addEventListener('scroll',()=>$('selectionAction').hidden=true,{passive:true});
$('closeDiscussion').onclick=closeDiscussion;$('discussionForm').onsubmit=sendMessage;
$('discussionInput').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendMessage();}};
$('discussionInput').oninput=()=>{const t=currentThread();if(t){if(live)saved.drafts[t.id]=$('discussionInput').value;else t.draft=$('discussionInput').value;persist();}};
for(const b of $('suggestions').querySelectorAll('button'))b.onclick=()=>{$('discussionInput').value=b.dataset.prompt;$('discussionInput').focus();};
$('locateSelection').onclick=()=>{const t=currentThread();if(t){switchView('reading');document.getElementById('block-'+t.anchor[0].blockId)?.scrollIntoView({behavior:'smooth',block:'center'});}};
$('navManuscript').onclick=()=>{closeDiscussion();switchView('reading');};
$('readingTab').onclick=()=>switchView('reading');$('pdfTab').onclick=()=>switchView('pdf');$('showAbout').onclick=()=>$('aboutDialog').showModal();$('closeAbout').onclick=()=>$('aboutDialog').close();
$('tryExample').onclick=()=>{location.href='/studio?'+new URLSearchParams({workspace,demo:'1'});};
$('dismissNotice').onclick=()=>$('previewNotice').hidden=true;
$('newReport').onclick=()=>location.href='/report?'+new URLSearchParams({workspace});
$('currentDocument').onclick=()=>$('projectMenu').hidden=!$('projectMenu').hidden;
$('resetPreview').onclick=async()=>{if(live){await refreshEditor();toast('已读取正式报告与已保存的讨论。');return;}if(!confirm('还原这份浏览器预览稿，并清空它的演示讨论和经验？原始报告不受影响。'))return;localStorage.removeItem(previewKey);setupDocument(original,{version:reportVersion,pdf:pdfURL,sample:previewKey.includes(':sample:')});toast('已还原当前预览。');};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeDiscussion();$('selectionAction').hidden=true;}});
async function refreshEditor(){
 if(!live||refreshingEditor)return;refreshingEditor=true;
 try{
  const value=await api('/api/lab/report/editor',{project});editorBusy=value.busy;
  $('showAbout').setAttribute('aria-label','关于纸狐');$('pdfLink').textContent='↗ 最新 PDF';$('pdfFrame').title='当前报告 PDF';
  if(value.validation_origin){document.querySelector('.preview-badge').textContent='● DS 验证项目';$('previewNotice').querySelector('p').textContent='这是独立验证项目，使用真实 DS；这里的模拟采用与经验不会写入你的正式写作习惯。';}
  saved.threads=value.threads;saved.memories=value.memories;
  const report=value.report;if(report&&report.version!==reportVersion){
   manuscript=copy(report.document);reportVersion=report.version;pdfURL=fileURL(report.pdf);$('pdfLink').href=pdfURL;
   renderPaper(false);$('pdfFrame').removeAttribute('src');
  }
  $('saveStatus').textContent=editorBusy?'纸狐正在处理，进度自动保存…':`报告已保存 · v${reportVersion}`;
  $('pdfView').querySelector('p').textContent=`当前报告 v${reportVersion}。每次采用都会更新 PDF，之前的版本仍然保留。`;
  if($('sidebarTitle').lastChild)$('sidebarTitle').lastChild.textContent=`v${reportVersion} · 正式报告`;
  renderThreads();
  const t=currentThread(),key=JSON.stringify({t,busy:editorBusy,sending});
  if(t&&key!==threadRenderKey){threadRenderKey=key;renderConversation();}
 }catch(e){$('saveStatus').textContent='连接中断，已发送的讨论保存在服务器';toast(e.message);}
 finally{refreshingEditor=false;}
}
async function runLiveAction(action,data={}){
 const t=currentThread();if(!t||sending)return;
 if(editorBusy){toast('当前报告正在处理，请稍候。');return;}
 const identity=JSON.stringify({action,thread:t.id,data});
 if(saved.outbox?.identity!==identity)saved.outbox={identity,request_id:uid()};
 const request_id=saved.outbox.request_id;persist();sending=true;renderConversation();
 try{
  await post('/api/lab/report/discussion',{action,thread_id:t.id,request_id,...data});
  if(action==='turn'){saved.drafts[t.id]='';$('discussionInput').value='';}
  delete saved.outbox;persist();
 }catch(e){toast(e.message);}
 finally{sending=false;await refreshEditor();renderConversation();}
}
window.PaperfoxEditor={
 async open(id){
  clearInterval(pollTimer);closeDiscussion();project=id;
  const value=await api('/api/lab/state',{project});
  if(!value.report?.document)throw Error('报告还在制作中，请先查看制作进度。');
  setupDocument(value.report.document,{version:value.report.version,pdf:fileURL(value.report.pdf),server:true});
  await refreshEditor();pollTimer=setInterval(refreshEditor,2200);
  if(query.get('thread'))openDiscussion(query.get('thread'));
 },
 suspend(){clearInterval(pollTimer);closeDiscussion();$('selectionAction').hidden=true;},
 bind(id){project=id;},
 setWorkspace(path){workspace=path;},
 refresh:refreshEditor
};
document.addEventListener('DOMContentLoaded',()=>{
 if(query.get('demo')==='1'){$('mainContent').hidden=false;setupDocument(SAMPLE,{sample:true});return;}
 window.PaperfoxWorkbench.init();
});
