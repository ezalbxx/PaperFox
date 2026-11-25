'use strict';
// Workspace navigation surrounds the existing server-backed selection editor.
const wb={view:'library',rows:[],current:null,filter:'all',archived:false,fileGroup:'materials',files:null,uploads:[],uploading:false,creating:false,refreshing:false,libraryPath:'',guidePath:'',setup:null,manageId:'',batch:crypto.randomUUID(),libraryAt:0};
const wn=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const wq=id=>document.getElementById(id);
const wstatus=p=>p.busy?'制作中':({paused:'已暂停',interrupted:'可从断点继续',failed:'需要处理',needs_input:'等待补充',awaiting_user:'等待补充'}[p.status])||(p.status==='completed'||p.stage==='done'||p.status==='done'?'已完成':p.report?'待你看稿':({ready:'准备开始',planned:'已规划',needs_attention:'有待处理项',executed:'实验已完成'}[p.status]||'进度已保存'));
const wbytes=n=>n>=1024**3?(n/1024**3).toFixed(1)+' GB':n>=1024**2?(n/1024**2).toFixed(1)+' MB':n>=1024?(n/1024).toFixed(1)+' KB':n+' B';
const wtime=t=>{if(!t)return '刚刚';const d=new Date(t);return Number.isNaN(d.getTime())?'已保存':d.toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});};
const wlink=(id,view='editor')=>'/studio?'+new URLSearchParams({workspace,project:id,view});
const wfile=(path,download=false)=>'/api/lab/file?'+new URLSearchParams({workspace,project,path,...(download?{download:'1'}:{})});
async function wrequest(route,data,params={}){const r=await fetch('/api/lab/'+route+(data?'':'?'+new URLSearchParams({workspace,project,...params})),data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace,project,...data})}:{});const value=await r.json();if(!r.ok)throw Error(value.error||'连接暂时中断');return value;}
function werror(e){toast(e.message||String(e));}
function wurl(){const next='/studio?'+new URLSearchParams({workspace,...(project?{project}:{}),view:wb.view});if(location.pathname+location.search===next)return;history[wb.ready?'pushState':'replaceState'](null,'',next);}
const foxCanvas=document.createElement('canvas');foxCanvas.tabIndex=0;
foxCanvas.setAttribute('aria-label','纸狐三维动画，左右方向键可调整视角');
const showFox=mountPaperFox(foxCanvas);
function progressFox(p){
 const mode=p.busy?p.phase:p.phase==='ready'?'ready':'rest';
 showFox(wq('progressFox'),mode);
}
function wshow(view){
 document.querySelector('.top-actions').hidden=view!=='editor';
 wq('projectNavigation').hidden=view==='library'||!project;
 document.body.classList.remove('outline-visible');wq('toggleOutline').setAttribute('aria-expanded','false');
 wb.view=view;document.body.classList.remove('view-library','view-progress','view-files','view-editor');document.body.classList.add('view-'+view);
 for(const [v,id] of [['library','libraryView'],['progress','progressView'],['files','filesView'],['editor','mainContent']])wq(id).hidden=v!==view;
 for(const [v,id] of [['library','navManuscript'],['editor','navWorkbench'],['progress','navProduction'],['editor','navReader'],['files','navFiles']]){const active=v===view&&(id!=='navFiles'||wb.fileGroup!=='versions');wq(id).classList.toggle('active',active);if(active)wq(id).setAttribute('aria-current','page');else wq(id).removeAttribute('aria-current');}
 wq('navVersions').classList.toggle('active',view==='files'&&wb.fileGroup==='versions');if(view==='files'&&wb.fileGroup==='versions')wq('navVersions').setAttribute('aria-current','page');else wq('navVersions').removeAttribute('aria-current');
 if(view!=='editor')window.PaperfoxEditor.suspend();
 wq('breadcrumbTitle').textContent=view==='library'?'报告库':wb.current?.title||'实验报告';
 wq('navProduction').disabled=!project;wq('navFiles').disabled=!project;
 wq('navReader').disabled=!wb.current?.report;wq('navVersions').disabled=!wb.current?.report;
 if(view==='library')showFox(wq('libraryFox'),'idle');else if(view==='progress'&&wb.current)progressFox(wb.current);else showFox(null,null);
 window.scrollTo(0,0);
 wurl();
}
async function wlibrary(){
 const rows=await wrequest('studio/projects');wb.rows=rows;wb.libraryAt=Date.now();wq('documentCount').textContent=rows.filter(p=>!p.studio.archived).length;
 wrenderCards();let recent=wq('recentReports');if(!recent){recent=wn('div');recent.id='recentReports';wq('currentDocument').parentElement.append(recent);}
 recent.replaceChildren(wn('p','最近报告','recent-label'));
 for(const row of rows.filter(r=>!r.studio.archived).slice(0,5)){const a=wn('a',row.title,'recent-report-link');a.href=wlink(row.id,row.report?'editor':'progress');a.onclick=e=>{e.preventDefault();wselect(row.id,row.report?'editor':'progress').catch(werror);};recent.append(a);}
}
function wrenderCards(){
 const search=wq('projectSearch').value.trim().toLocaleLowerCase();const rows=wb.rows.filter(p=>!!p.studio.archived===wb.archived&&(!search||p.title.toLocaleLowerCase().includes(search))&&(wb.filter==='all'||wb.filter==='running'&&p.busy||wb.filter==='report'&&p.report||wb.filter==='starred'&&p.studio.starred));
 wq('libraryTotal').textContent=rows.length;wq('libraryHeading').firstChild.textContent=wb.archived?'已归档的报告 ':'我的报告 ';wq('toggleArchive').textContent=wb.archived?'↩ 返回报告库':'▱ 已归档';wq('reportCards').replaceChildren();wq('libraryEmpty').hidden=rows.length>0;
 if(!rows.length&&search){wq('libraryEmpty').querySelector('h3').textContent='没有找到这份报告。';wq('libraryEmpty').querySelector('p').textContent='换个关键词，或试试其他筛选。';}else{wq('libraryEmpty').querySelector('h3').textContent=wb.archived?'这里保存暂时收起的报告。':'为下一个实验，留一页空白。';wq('libraryEmpty').querySelector('p').textContent=wb.archived?'归档保留全部文件、历史版本和修改讨论。':'上传指导书、实验材料和模板，纸狐会从这里开始。';}
 for(const p of rows){
  const card=wn('article',undefined,'report-card');const cover=wn('div',undefined,'report-card-cover');cover.setAttribute('role','button');cover.tabIndex=0;cover.setAttribute('aria-label','打开'+p.title);const go=()=>wselect(p.id,p.report?'editor':'progress').catch(werror);cover.onclick=go;cover.onkeydown=e=>{if(e.key==='Enter')go();};
  const sheet=wn('div',undefined,'cover-sheet');sheet.append(wn('i'),wn('i'),wn('i'));sheet.insertAdjacentHTML('beforeend','<svg viewBox="0 0 100 35" aria-hidden="true"><path d="M0 30L22 20L45 24L70 9L100 3"/></svg>');cover.append(sheet,wn('span',p.report?'EXPERIMENT REPORT':'WORK IN PROGRESS','card-cover-label'));
  const star=wn('button',p.studio.starred?'★':'☆','card-star'+(p.studio.starred?' starred':''));star.disabled=p.busy;star.setAttribute('aria-label',p.studio.starred?'取消收藏':'收藏报告');star.onclick=e=>{e.stopPropagation();wmanage(p.id,p.studio.starred?'unstar':'star').catch(werror);};cover.append(star);
  const info=wn('div',undefined,'report-card-info'),title=wn('button',p.title,'report-card-title');title.onclick=go;const state=wn('span',(p.busy?'◌ ':'')+wstatus(p),'card-state'+(p.busy?' running':p.report?' attention':p.status==='failed'?' error':''));const meta=wn('div',undefined,'card-meta');meta.append(wn('span',`${p.materials_count} 份材料 · ${p.report?'v'+p.report.version:'尚未成稿'}`),wn('time',wtime(p.updated_at)));info.append(title,state,meta);
  const bottom=wn('div',undefined,'card-bottom'),open=wn('button',p.report?'阅读与改稿 ↗':'查看制作进度 ↗'),settings=wn('button','•••');settings.setAttribute('aria-label','管理'+p.title);open.onclick=go;settings.onclick=()=>wsettings(p);bottom.append(open,settings);card.append(cover,info);if(p.busy){const line=wn('div',undefined,'card-progress'),fill=wn('i');fill.style.width=p.percent+'%';line.append(fill);card.append(line);}card.append(bottom);wq('reportCards').append(card);
 }
}
async function wselect(id,view){
 window.PaperfoxEditor.suspend();project=id;window.PaperfoxEditor.bind(id);wb.current=await wrequest('studio/progress');wb.files=null;
 if(view==='editor'&&!wb.current.report)view='progress';
 wq('sidebarTitle').replaceChildren(wn('span',wb.current.title),wn('small',wb.current.report?'v'+wb.current.report.version+' · 正式报告':'制作进行中'));
 wshow(view);if(view==='editor'){await window.PaperfoxEditor.open(id);wq('breadcrumbTitle').textContent=wb.current.title;const name=wq('sidebarTitle').firstElementChild;if(name)name.textContent=wb.current.title;}if(view==='progress')wrenderProgress(wb.current);if(view==='files')await wloadFiles();
}
const phaseHeadlines={materials:'材料已接收，准备出发。',planning:'先读懂，再动手。',execution:'让想法，在实验中发生。',structure:'让证据，找到自己的位置。',writing:'一段一段，写出实验的脉络。',formatting:'把内容，折成完整的一稿。',ready:'报告已生成，开始阅读吧。'};
const phaseDescriptions={materials:'文件已存入这份报告，纸狐将开始理解指导书和可用材料。',planning:'阅读任务要求、梳理现有材料，把目标变成可以执行的安排。',execution:'编写并运行实验，保存真实结果、曲线和关键中间产物。',structure:'围绕实验问题安排章节，确定每幅图和每张表的用途。',writing:'依据实验过程与结果逐步成稿，让段落顺着问题自然展开。',formatting:'整合章节、处理图表，按照模板生成可阅读的报告。',ready:'现在可以阅读、选句讨论，聊到满意后把修改写进报告。'};
function wrenderProgress(p){
 const complete=!!p.report&&!p.busy&&p.phase==='ready'&&['done','completed'].includes(p.status);
 if(wb.view==='progress')progressFox(p);
 const side=wq('sidebarTitle').querySelector('small');if(side)side.textContent=p.report?'v'+p.report.version+' · 正式报告':wstatus(p);
 wb.current=p;wq('journeyTitle').textContent=p.title;wq('journeySubtitle').textContent=p.studio.mode==='execute'?'指导书 → 实验执行 → 完整报告 → 对话改稿':'实验材料 → 图文组织 → 完整报告 → 对话改稿';wq('journeyStatus').textContent=wstatus(p);wq('journeyHeadline').textContent=phaseHeadlines[p.phase]||'进度已保存';wq('journeyDescription').textContent=phaseDescriptions[p.phase]||'';
 if(!p.busy&&p.status==='paused')wq('journeyHeadline').textContent='这一程，已替你留好断点。';
 if(!p.busy&&p.status==='failed')wq('journeyHeadline').textContent='遇到一点问题，进度还在。';
 if(!p.busy&&p.questions.length)wq('journeyHeadline').textContent='有个问题，想听听你的想法。';
 if(!p.busy&&p.status==='needs_attention')wq('journeyHeadline').textContent=p.report?'报告已保存，还有待处理项。':'有待处理项，进度已保存。';
 if(complete)wq('journeyDescription').textContent='打开正文继续打磨，或下载排版好的 PDF。每次采用修改，都会保留一个新版本。';
 wq('progressView').classList.toggle('is-running',p.busy);wq('progressView').classList.toggle('production-complete',complete);wq('journeyFill').style.width=p.percent+'%';wq('journeyPercent').replaceChildren(document.createTextNode(String(p.percent)),wn('span','%'));wq('journeyBar').setAttribute('aria-valuenow',p.percent);wq('journeyBar').setAttribute('aria-valuetext',`${p.phases[p.phase_index].name}，流程进度${p.percent}%`);
 wq('journeyDetail').textContent=p.detail.total&&p.busy?`${p.detail.label} · ${p.detail.completed}/${p.detail.total}${p.detail.topic?' · '+p.detail.topic:''}`:p.report?`当前已保存 v${p.report.version} · ${p.versions_count} 个历史版本`:'按已完成的阶段与任务更新，进度自动保存';
 wq('journeyPersistence').textContent=complete?'材料、正文和历史版本已保存。':p.busy?'可以离开页面，任务会在本机继续。':'材料与断点均已保存，可以稍后继续。';wq('pauseProduction').hidden=!p.busy;wq('resumeProduction').hidden=p.busy||p.questions.length>0||['done','completed'].includes(p.status);wq('resumeProduction').textContent=p.report?'继续处理待办 ↗':'继续已保存的任务 ↗';wq('progressRead').hidden=!p.report;
 const pdf=wq('progressPdf');pdf.hidden=!p.report?.pdf;
 if(p.report?.pdf){pdf.href=wfile(p.report.pdf,true);pdf.download=p.title+'.pdf';}else pdf.removeAttribute('href');
 wq('journeyPhases').replaceChildren(...p.phases.map((phase,i)=>{const li=wn('li',undefined,phase.state);li.append(wn('span',phase.state==='done'?'✓':String(i+1),'phase-number'),wn('span',phase.name));if(phase.state==='current')li.setAttribute('aria-current','step');return li;}));
 const productionIssues=(p.issues||[]).filter(i=>i.severity==='major');
 const productionError=p.can_replace_guidance?'当前指导书没有可提取的正文。请选择带正文的 Word 文件或经过 OCR 的 PDF。':/\u5df2\u6682\u505c\u6a21\u578b\u54cd\u5e94|\u7528\u6237\u6682\u505c/.test(p.error)?'':p.error;
 wq('replaceGuidance').hidden=!p.can_replace_guidance;
 if(p.can_replace_guidance)wq('resumeProduction').hidden=true;
 const productionMessages=[productionError,...productionIssues.map(i=>'\u2022 '+i.reason+'\n'+i.suggestion)].filter(Boolean);
 wq('productionError').hidden=!productionMessages.length;wq('productionError').textContent=productionMessages.join('\n\n');
 const reply=wq('productionReply');reply.hidden=p.busy||(!p.questions.length&&!p.pending_checkpoint);const pendingKey=p.pending_id||p.questions.map(q=>q.question).join('|');if(reply.dataset.pending!==pendingKey){reply.dataset.pending=pendingKey;wq('productionAnswer').value='';}wq('productionQuestions').replaceChildren(...p.questions.map(q=>wn('p',q.question)));if(p.pending_checkpoint&&!p.questions.length)wq('productionQuestions').append(wn('p','这一步等待你的意见。可以写下修改方向，或填写“认可”继续。'));
 wq('taskSummary').textContent=p.tasks.length?`${p.tasks.filter(t=>t.status==='done').length} / ${p.tasks.length} 项已保存`:'等待规划';wq('productionTasks').replaceChildren();
 for(const task of p.tasks){const row=wn('div',undefined,'production-task '+task.status),info=wn('div');info.append(wn('h4',task.title),wn('small',task.status==='done'?'结果已保存':task.status==='partial'?'已有部分结果，仍需补充':'等待执行'));row.append(wn('span',task.status==='done'?'✓':task.status==='partial'?'△':'○','task-icon'),info);wq('productionTasks').append(row);}if(!p.tasks.length)wq('productionTasks').append(wn('p','纸狐正在把材料整理成清楚的工作安排。任务确定后，会在这里逐项展开。','waiting-copy'));
 wq('draftProgress').hidden=!p.draft_sections.length;wq('draftChapters').replaceChildren(...p.draft_sections.map(s=>wn('span','✓ '+s.heading,'draft-chapter')));
 const previewKey=JSON.stringify(p.previews||[]);wq('artifactPreviews').hidden=!(p.previews||[]).length;if(wq('artifactPreviewGrid').dataset.key!==previewKey){wq('artifactPreviewGrid').dataset.key=previewKey;wq('artifactPreviewGrid').replaceChildren(...(p.previews||[]).map(file=>{const button=wn('button'),img=wn('img');img.src=wfile(file.path);img.alt=file.name;button.append(img,wn('span',file.name));button.onclick=()=>wpreview(file.path,file.name);return button;}));}
 const activity=p.activity.slice().reverse(),key=JSON.stringify(activity);if(wq('productionActivity').dataset.key!==key){wq('productionActivity').dataset.key=key;wq('productionActivity').replaceChildren(...activity.map(a=>{const row=wn('div',undefined,'activity-item'),info=wn('div');info.append(wn('p',a.text),wn('time',wtime(a.at)));row.append(wn('i',undefined,'activity-point'),info);return row;}));if(!activity.length)wq('productionActivity').append(wn('p','开始制作后，真实保存的动态会出现在这里。','waiting-copy'));}
 wq('metricMaterials').textContent=p.materials_count+' 份';wq('metricVersions').textContent=p.versions_count+' 稿';wq('metricTokens').textContent=Number(p.usage.tokens||0).toLocaleString();wq('metricCost').textContent=p.usage.cost_cny!=null?'¥'+Number(p.usage.cost_cny).toFixed(3):'$'+Number(p.usage.cost_usd||0).toFixed(4);if(p.usage.cost_cny!=null&&p.usage.cost_usd>0)wq('metricCost').textContent+=' + $'+Number(p.usage.cost_usd).toFixed(3);
}
async function wrefresh(){if(wb.exiting||wb.refreshing||document.hidden)return;wb.refreshing=true;try{if(wb.view==='progress'&&project){const selected=project;const state=await wrequest('studio/progress');if(project===selected&&wb.view==='progress')wrenderProgress(state);}if(wb.view==='files'&&wb.current?.busy&&Date.now()-(wb.filesAt||0)>5000){wb.current=await wrequest('studio/progress');await wloadFiles();}if(wb.view==='library'&&Date.now()-wb.libraryAt>5000)await wlibrary();}catch(e){if(wb.view==='progress'&&!wb.exiting){wq('journeyStatus').textContent='连接中断 · 正在重连';wq('journeyPersistence').textContent='已保存的进度保留，恢复连接后继续显示。';}}finally{wb.refreshing=false;}}
async function wmanage(id,action,extra={}){await wrequest('studio/manage',{project:id,action,...extra});await wlibrary();if(project===id)wb.current=await wrequest('studio/progress');}
function wsettings(p){wb.manageId=p.id;wq('renameReportInput').value=p.title;wq('archiveReportButton').textContent=p.studio.archived?'移回报告库':'归档这份报告';wq('archiveReportButton').dataset.archived=String(!!p.studio.archived);wq('archiveReportButton').disabled=p.busy;wq('renameReportInput').disabled=p.busy;wq('renameReportForm').querySelector('button').disabled=p.busy;wq('manageReportDialog').showModal();}
async function wsetupRequest(data){
 const r=await fetch('/api/paperfox/setup',data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{});
 const value=await r.json();if(!r.ok)throw Error(value.error||'无法读取 DeepSeek 设置');return value;
}
function wopenSetup(){
 wq('paperfoxSetupError').hidden=true;wq('paperfoxApiKey').value='';
 wq('paperfoxApiKey').required=!wb.setup?.configured;
 wq('paperfoxApiKey').placeholder=wb.setup?.configured?'留空可继续使用已保存的密钥':'';
 wq('paperfoxConnection').value=wb.setup?.connection||'system';
 const dialog=wq('paperfoxSetupDialog');if(!dialog.open)dialog.showModal();
}
async function wopenCreate(){
 if(wb.creating)return;
 try{wb.setup=await wsetupRequest();if(wb.setup.enabled&&!wb.setup.configured){wopenSetup();return;}}
 catch(e){werror(e);return;}
 wq('createReportDialog').showModal();wq('chooseLocalLibrary').focus();
}
function wuploadRender(){
 wq('uploadFileList').replaceChildren();const roles={guidance:'实验指导书',template:'报告模板',data:'数据 / 代码 / 结果',reference:'参考资料'};
 wb.uploads.forEach((f,i)=>{const row=wn('div',undefined,'upload-file'+(f.error?' failed':'')),info=wn('div');info.append(wn('b',f.file.name),wn('small',`${wbytes(f.file.size)} · ${f.error|| (f.token?'已接收':f.percent!=null?'上传 '+f.percent+'%':'等待上传')}`));const role=wn('select');role.setAttribute('aria-label',f.file.name+'的用途');for(const [k,v]of Object.entries(roles)){const o=wn('option',v);o.value=k;role.append(o);}role.value=f.role;role.disabled=wb.creating;role.onchange=()=>f.role=role.value;const remove=wn('button','×');remove.type='button';remove.setAttribute('aria-label','移除'+f.file.name);remove.disabled=wb.creating;remove.onclick=()=>{wb.uploads.splice(i,1);wuploadRender();};row.append(info,role,remove);wq('uploadFileList').append(row);});
 const total=wb.uploads.reduce((n,f)=>n+f.file.size,0),loaded=wb.uploads.reduce((n,f)=>n+(f.token?f.file.size:f.loaded||0),0),pct=total?Math.round(loaded/total*100):0;wq('uploadTotal').hidden=!wb.creating;wq('uploadTotalBar').value=pct;wq('uploadTotalPercent').textContent=pct+'%';wq('uploadTotalText').textContent=pct===100?'材料已接收，正在建立报告':'正在接收材料 · '+wbytes(loaded)+' / '+wbytes(total);
}
function waddFiles(files){
 if(wb.creating)return;
 for(const file of files){if(wb.uploads.some(f=>f.file.name===file.name&&f.file.size===file.size))continue;
  const isGuide=/\.(pdf|docx?)$/i.test(file.name),template=/模板|template/i.test(file.name),role=template?'template':isGuide&&!wb.uploads.some(f=>f.role==='guidance')?'guidance':'data';wb.uploads.push({file,role,loaded:0});
 }if(!wq('reportTitleInput').value&&wb.uploads.length)wq('reportTitleInput').value=wb.uploads[0].file.name.replace(/\.[^.]+$/,'').replace(/指导书|指导书籍/,'').replace(/[_-]+$/,'');wuploadRender();
}
function wsendFile(file){return new Promise((resolve,reject)=>{
 const xhr=new XMLHttpRequest();xhr.open('POST','/api/lab/studio/upload?'+new URLSearchParams({workspace,batch:wb.batch,name:file.file.name}));xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.upload.onprogress=e=>{file.loaded=e.loaded;file.percent=e.lengthComputable?Math.round(e.loaded/e.total*100):null;wuploadRender();};xhr.onload=()=>{let value;try{value=JSON.parse(xhr.responseText);}catch{reject(Error('文件上传未完成，请重试'));return;}if(xhr.status>=400){reject(Error(value.error||'上传失败'));return;}file.token=value.token;file.loaded=file.file.size;file.error='';wuploadRender();resolve(value);};xhr.onerror=()=>reject(Error('连接中断，点击开始制作可重试未完成文件'));xhr.send(file.file);
 });}
async function wcreate(e){e.preventDefault();if(wb.creating)return;wq('createReportError').hidden=true;
 const mode='report';
 if(!wb.uploads.some(f=>f.role==='data')&&!wb.libraryPath){wq('createReportError').textContent='先放入指导书和实验材料，再开始这一稿。';wq('createReportError').hidden=false;return;}
 if(!wb.guidePath&&!wb.uploads.some(f=>f.role==='guidance')){wq('createReportError').textContent='请选择一份 PDF、DOC 或 DOCX，将用途设为“实验指导书”。';wq('createReportError').hidden=false;return;}
 wb.creating=true;wq('createReportSubmit').disabled=true;wq('closeCreateReport').disabled=true;wq('createReportSubmit').textContent='正在接收材料…';wuploadRender();
 try{for(const file of wb.uploads){if(file.token)continue;try{await wsendFile(file);}catch(e){file.error=e.message;wuploadRender();throw e;}}
  wq('createReportSubmit').textContent='正在建立报告…';const result=await wrequest('studio/create',{request_id:wb.batch,title:wq('reportTitleInput').value,mode,guidance_path:wb.guidePath,files:wb.uploads.map(f=>({token:f.token,role:f.role})),library_path:wb.libraryPath,student_id:wq('newReportStudentId').value,student:{name:wq('newReportStudentName').value},instructions:wq('reportInstructionsInput').value});
  wq('createReportDialog').close();wb.uploads=[];wb.batch=crypto.randomUUID();wb.libraryPath='';wb.guidePath='';wq('chosenLibrary').hidden=true;wq('chosenGuide').hidden=true;wq('reportTitleInput').value='';wq('reportInstructionsInput').value='';wuploadRender();await wlibrary();await wselect(result.project,'progress');toast('材料已接收，纸狐开始制作，进度会自动保存。');
 }catch(e){wq('createReportError').textContent=e.message;wq('createReportError').hidden=false;}finally{wb.creating=false;wq('createReportSubmit').disabled=false;wq('closeCreateReport').disabled=false;wq('createReportSubmit').textContent='开始制作 ↗';wuploadRender();}
}
async function wloadFiles(){wq('filesProjectName').textContent=wb.current?.title||'';wq('downloadBundle').href='/api/lab/bundle?'+new URLSearchParams({workspace,project});wq('downloadBundle').download='paperfox-'+project+'.zip';wb.files=await wrequest('studio/files');wb.filesAt=Date.now();const side=wq('sidebarTitle').querySelector('small');if(side&&wb.files.current_version)side.textContent='v'+wb.files.current_version+' · 正式报告';wrenderFiles();}
function wrenderFiles(){
 if(!wb.files)return;const search=wq('fileSearch').value.toLocaleLowerCase(),list=wq('filesList');list.replaceChildren();
 if(wb.fileGroup==='versions'){
  for(const row of wb.files.versions.slice().reverse().filter(r=>!search||('v'+r.version+' '+wreason(r.reason)).toLocaleLowerCase().includes(search))){const line=wn('div',undefined,'file-row'),info=wn('div',undefined,'file-name'),title=wn('b','报告 v'+row.version);if(row.version===wb.files.current_version)title.append(wn('span','当前版本','version-current'));info.append(title,wn('small',wreason(row.reason)+(row.modified?' · '+wtime(row.modified*1000):'')));const preview=wn('button','查看'),download=wn('a','↓ PDF'),restore=wn('button','恢复为新稿');download.href=wfile(row.pdf,true);download.download='报告-v'+row.version+'.pdf';preview.onclick=()=>wpreview(row.pdf,'报告 v'+row.version);restore.disabled=wb.current?.busy||row.version===wb.files.current_version;restore.onclick=async()=>{try{restore.disabled=true;await wmanage(project,'restore',{version:row.version});await wloadFiles();toast('旧稿已保存为新的当前版本，其他版本与讨论都保留。');}catch(e){restore.disabled=false;werror(e);}};const compare=wn('button','对比当前');compare.disabled=row.version===wb.files.current_version;compare.onclick=()=>wcompare(row.version,wb.files.current_version);line.append(wn('span','v'+row.version,'version-badge'),info,preview,compare,download,restore);list.append(line);}
 }else{
  const rows=wb.files.files.filter(f=>f.group===wb.fileGroup&&(!search||f.name.toLocaleLowerCase().includes(search))).sort((a,b)=>b.modified-a.modified);
  for(const file of rows){const line=wn('div',undefined,'file-row'),info=wn('div',undefined,'file-name'),image=/\.(png|jpg|jpeg|webp|svg|gif)$/i.test(file.name),icon=wn('span',image?'▧':file.extension.slice(1).slice(0,4).toUpperCase()||'FILE','file-icon'+(file.extension==='.pdf'?' pdf':image?' image':''));info.append(wn('b',file.name),wn('small',file.role?({guidance:'实验指导书',template:'报告模板',data:'实验材料',reference:'参考资料'}[file.role]||'实验材料'):file.path));const preview=wn('button','预览'),download=wn('a','↓ 下载');preview.onclick=()=>wpreview(file.path,file.name);download.href=wfile(file.path,true);download.download=file.name;line.append(icon,info,wn('span',wbytes(file.bytes)),preview,download);list.append(line);}
 }if(!list.children.length){const empty=wn('div',undefined,'bench-empty');empty.style.border='0';empty.style.margin='0';empty.append(wn('span','▱'),wn('h3',search?'没有找到匹配项。':wb.fileGroup==='versions'?'第一稿还在路上。':'这里还没有文件。'),wn('p',wb.fileGroup==='materials'?'上传的材料会保存在这里。':'随着制作推进，保存的文件会陆续出现在这里。'));list.append(empty);}
}
function wreason(reason){if(!reason)return '已保存';if(reason.startsWith('selection-adopt'))return '采用了选句讨论中的改稿';if(reason.startsWith('selection-undo'))return '撤销了一次选句修改';if(reason.startsWith('user-restored-version'))return '从历史版本恢复 · 原稿保留';if(reason.includes('layout')||reason.includes('template'))return '模板与版式调整';if(reason.includes('chapter'))return '按章节规范整理正文';if(reason==='initial')return '第一份完整稿';return '正文与图文更新';}
async function wcompare(from,to){
 wq('filePreviewTitle').textContent=`版本对比 · v${from} → v${to}`;wq('filePreviewDownload').hidden=true;const body=wq('filePreviewBody');body.replaceChildren(wn('p','正在比较已保存的正文…','workbench-loading'));wq('filePreviewDialog').showModal();
 try{const value=await wrequest('studio/compare',null,{from,to});body.replaceChildren(wn('p',value.changes.length?`${value.changes.length} 处正文变化 · 左侧 v${from}，右侧 v${to}`:'两个版本的正文内容相同。','compare-summary'));for(const change of value.changes){const row=wn('section',undefined,'compare-row');row.append(wn('h3',change.heading+' · '+({added:'新增',removed:'删除',changed:'修改'}[change.kind])));const cols=wn('div');for(const [label,text]of [[`v${from}`,change.before],[`v${to}`,change.after]]){const col=wn('div');col.append(wn('small',label),wn('p',text||'（无此内容）'));cols.append(col);}row.append(cols);body.append(row);}}catch(e){body.replaceChildren(wn('p',e.message,'workbench-loading'));}
}
async function wpreview(path,name){
 const body=wq('filePreviewBody');body.replaceChildren(wn('p','正在打开文件…','workbench-loading'));wq('filePreviewTitle').textContent=name;wq('filePreviewDownload').hidden=false;wq('filePreviewDownload').href=wfile(path,true);wq('filePreviewDownload').download=name;wq('filePreviewDialog').showModal();
 try{if(/\.(pdf|html)$/i.test(path)){const frame=wn('iframe');frame.title=name;frame.src=wfile(path);if(/\.html$/i.test(path))frame.setAttribute('sandbox','');body.replaceChildren(frame);}else if(/\.(png|jpg|jpeg|svg|webp|gif)$/i.test(path)){const image=wn('img');image.alt=name;image.src=wfile(path);body.replaceChildren(image);}else if(/\.(txt|md|json|jsonl|csv|py|js|r|yaml|yml|toml|log|tex)$/i.test(path)){const result=await wrequest('studio/preview',null,{path});body.replaceChildren(wn('pre',result.text));}else{body.replaceChildren(wn('p','这类文件适合下载后用相应软件打开。','workbench-loading'));}}catch(e){body.replaceChildren(wn('p',e.message,'workbench-loading'));}
}
window.PaperfoxWorkbench={async init(){
 try{if(!workspace){const response=await fetch('/api/health');workspace=(await response.json()).workspace;}window.PaperfoxEditor.setWorkspace(workspace);wshow('library');wq('reportCards').replaceChildren(...[1,2,3].map(()=>wn('div',undefined,'card-skeleton')));await wlibrary();if(project)await wselect(project,query.get('view')||'editor');else wshow('library');wb.ready=true;setInterval(wrefresh,2200);}catch(e){wq('reportCards').replaceChildren(wn('p','暂时无法连接工作台，请确认本机服务已启动。','bench-empty'));werror(e);}
}};
for(const id of ['newReport','heroCreate','emptyCreate'])wq(id).onclick=wopenCreate;
wq('closeCreateReport').onclick=()=>wq('createReportDialog').close();wq('createReportDialog').addEventListener('cancel',e=>{if(wb.creating)e.preventDefault();});wq('createReportForm').onsubmit=wcreate;
wq('uploadDropzone').onclick=()=>{if(!wb.creating)wq('materialFileInput').click();};wq('uploadDropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(!wb.creating)wq('materialFileInput').click();}};wq('materialFileInput').onchange=e=>{waddFiles(e.target.files);e.target.value='';};
for(const event of ['dragenter','dragover'])wq('uploadDropzone').addEventListener(event,e=>{e.preventDefault();wq('uploadDropzone').classList.add('dragover');});for(const event of ['dragleave','drop'])wq('uploadDropzone').addEventListener(event,e=>{e.preventDefault();wq('uploadDropzone').classList.remove('dragover');if(event==='drop')waddFiles(e.dataTransfer.files);});
async function wpick(kind){
 const folder=kind==='folder',key=folder?'libraryPath':'guidePath',hint=wq(folder?'chosenLibrary':'chosenGuide');
 try{
  const r=await post('/api/pick',{kind,initialdir:wb.libraryPath||localStorage.getItem('paperfox:last-material-folder')||undefined});
  if(!r.path)return;
  wb[key]=r.path;hint.textContent=r.path;hint.hidden=false;
  if(folder)localStorage.setItem('paperfox:last-material-folder',r.path);
  else if(!wq('reportTitleInput').value)wq('reportTitleInput').value=r.path.split(/[\\/]/).at(-1).replace(/\.[^.]+$/,'');
 }catch(e){werror(e);}
}
wq('chooseLocalLibrary').onclick=()=>wpick('folder');
wq('chooseGuide').onclick=()=>wpick('guidance');
wq('replaceGuidance').onclick=async()=>{
 const button=wq('replaceGuidance'), selected=project;
 button.disabled=true;
 try{
  const file=await post('/api/pick',{kind:'guidance'});
  if(!file.path||project!==selected)return;
  await wrequest('studio/replace-guidance',{project:selected,path:file.path});
  await wrefresh();
 }catch(e){
  wq('productionError').textContent=e.message||String(e);
  wq('productionError').hidden=false;
 }finally{button.disabled=false;}
};
wq('openPaperfoxSetup').onclick=wopenSetup;
wq('closePaperfoxSetup').onclick=()=>wq('paperfoxSetupDialog').close();
wq('paperfoxSetupDialog').addEventListener('close',()=>{wq('paperfoxApiKey').value='';});
wq('paperfoxSetupForm').onsubmit=async e=>{
 e.preventDefault();const save=wq('paperfoxSetupSave'),error=wq('paperfoxSetupError');
 save.disabled=true;error.hidden=true;
 try{wb.setup=await wsetupRequest({api_key:wq('paperfoxApiKey').value,connection:wq('paperfoxConnection').value});wq('paperfoxSetupDialog').close();toast('DeepSeek 已连接，可以新建报告。');}
 catch(e){error.textContent=e.message;error.hidden=false;}
 finally{save.disabled=false;}
};
const exitDialog=wq('paperfoxExitDialog'),exitConfirm=wq('confirmPaperfoxExit'),exitCancel=wq('cancelPaperfoxExit');
wq('openPaperfoxExit').onclick=()=>{
 wq('paperfoxExitError').hidden=true;
 exitDialog.showModal();
};
exitCancel.onclick=()=>exitDialog.close();
exitDialog.oncancel=e=>{if(exitConfirm.disabled)e.preventDefault();};
exitConfirm.onclick=async()=>{
 const error=wq('paperfoxExitError');
 error.hidden=true;exitConfirm.disabled=true;exitCancel.disabled=true;
 try{
  await post('/api/shutdown',{confirmed:true});
  wb.exiting=true;
  wq('paperfoxExitStatus').textContent='正在退出纸狐。请关闭此页面，稍等片刻后再升级或删除程序。';
  exitConfirm.hidden=true;exitCancel.hidden=true;
 }catch(e){
  error.textContent=e.message;error.hidden=false;exitConfirm.disabled=false;exitCancel.disabled=false;
 }
};
wsetupRequest().then(state=>{wb.setup=state;wq('openPaperfoxSetup').hidden=!state.enabled;wq('openPaperfoxExit').hidden=!state.enabled;if(state.enabled&&!state.configured)wopenSetup();}).catch(werror);
wq('navManuscript').onclick=async()=>{try{wshow('library');await wlibrary();}catch(e){werror(e);}};wq('navWorkbench').onclick=async()=>{
 if(wb.view==='editor')return;
 try{
  if(!wb.rows.length)await wlibrary();
  const id=wb.rows.find(p=>p.id===project&&p.report)?.id || wb.rows.find(p=>p.report&&!p.studio.archived)?.id;
  if(id)await wselect(id,'editor');
  else{wshow('library');toast('有了成稿，就可以在工作台改稿。');}
 }catch(e){werror(e);}
};
wq('backToLibrary').onclick=()=>wq('navManuscript').click();wq('navProduction').onclick=()=>{if(project)wselect(project,'progress').catch(werror);};wq('navReader').onclick=()=>{if(project&&wb.current?.report)wselect(project,'editor').catch(werror);};
function wopenFiles(group='materials'){wb.fileGroup=group;wq('fileSearch').value='';for(const button of wq('fileFilters').children)button.classList.toggle('selected',button.dataset.group===group);if(project)wselect(project,'files').catch(werror);}
wq('navFiles').onclick=()=>wopenFiles();wq('navVersions').onclick=()=>wopenFiles('versions');wq('currentDocument').onclick=()=>{if(project)wselect(project,wb.current?.report?'editor':'progress').catch(werror);};
wq('toggleOutline').onclick=()=>{const open=document.body.classList.toggle('outline-visible');wq('toggleOutline').setAttribute('aria-expanded',String(open));};wq('outline').addEventListener('click',e=>{if(e.target.closest('a')){document.body.classList.remove('outline-visible');wq('toggleOutline').setAttribute('aria-expanded','false');}});document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('outline-visible');wq('toggleOutline').setAttribute('aria-expanded','false');}});
wq('projectSearch').oninput=wrenderCards;wq('toggleArchive').onclick=()=>{wb.archived=!wb.archived;wrenderCards();};wq('projectFilters').onclick=e=>{const button=e.target.closest('[data-filter]');if(!button)return;wb.filter=button.dataset.filter;for(const b of wq('projectFilters').children)b.classList.toggle('selected',b===button);wrenderCards();};
wq('pauseProduction').onclick=async()=>{try{await wrequest('pause',{});toast('已请求暂停，当前步骤和断点会保留。');await wrefresh();}catch(e){werror(e);}};
wq('resumeProduction').onclick=async()=>{try{wq('resumeProduction').disabled=true;const p=wb.current;await wrequest(p.resume_action==='report'?'report/start':'start',{action:p.resume_action,automatic:true});await wrefresh();}catch(e){werror(e);}finally{wq('resumeProduction').disabled=false;}};
wq('progressRead').onclick=()=>wselect(project,'editor').catch(werror);wq('progressFiles').onclick=()=>wopenFiles();
wq('productionReply').onsubmit=async e=>{e.preventDefault();const text=wq('productionAnswer').value.trim();if(!text)return;const button=e.target.querySelector('button');button.disabled=true;try{await wrequest('studio/reply',{text,pending_id:wb.current.pending_id,decision:wb.current.pending_checkpoint?(/^(认可|同意|继续|通过|approve)[。.!！]?$/i.test(text)?'approve':'revise'):'answer',automatic:true});await wrefresh();}catch(e){werror(e);}finally{button.disabled=false;}};
wq('fileFilters').onclick=e=>{const b=e.target.closest('[data-group]');if(!b)return;wb.fileGroup=b.dataset.group;wq('fileSearch').value='';for(const item of wq('fileFilters').children)item.classList.toggle('selected',item===b);wshow('files');wrenderFiles();};wq('fileSearch').oninput=wrenderFiles;wq('closeFilePreview').onclick=()=>{wq('filePreviewDialog').close();wq('filePreviewBody').replaceChildren();};
wq('closeManageReport').onclick=()=>wq('manageReportDialog').close();wq('renameReportForm').onsubmit=async e=>{e.preventDefault();try{await wmanage(wb.manageId,'rename',{title:wq('renameReportInput').value});wq('manageReportDialog').close();toast('报告名称已保存。');}catch(e){werror(e);}};wq('archiveReportButton').onclick=async()=>{try{await wmanage(wb.manageId,wq('archiveReportButton').dataset.archived==='true'?'unarchive':'archive');wq('manageReportDialog').close();toast('报告库已更新，文件和历史版本都保留。');}catch(e){werror(e);}};
window.addEventListener('popstate',()=>{const params=new URLSearchParams(location.search);const id=params.get('project'),view=params.get('view')||'editor';if(id===project&&view===wb.view)return;if(view==='library'||!id){project=id||'';wshow('library');wlibrary().catch(werror);}else wselect(id,view).catch(werror);});
if(query.get('demo')==='1'){
 const home=()=>{location.href='/studio?'+new URLSearchParams({workspace,view:'library'});};
 wq('navWorkbench').classList.add('active');wq('navWorkbench').setAttribute('aria-current','page');wq('navManuscript').classList.remove('active');wq('navWorkbench').onclick=()=>switchView('reading');wq('newReport').onclick=home;wq('navManuscript').onclick=home;
 wq('navProduction').disabled=true;wq('navFiles').disabled=true;
}
