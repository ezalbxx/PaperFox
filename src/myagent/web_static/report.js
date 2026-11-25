const query=new URLSearchParams(location.search);
let workspace=query.get('workspace')||'',project=query.get('project')||'';
const $=id=>document.getElementById(id);
const steps=['确认信息','理解材料','组织图文','撰写报告','排版交付'];
const stages={intake:0,facts:1,story_cards:1,outline:2,sample:2,writing:3,editing:4,formatting:4,delivery:4,done:5};
const headings={intake:'确认报告所需信息',facts:'正在理解实验材料',story_cards:'正在整理各项实验',outline:'正在组织正文与图表',sample:'准备构建完整报告',writing:'正在撰写完整报告',editing:'正在整合正文',formatting:'正在按模板排版',delivery:'正在完成报告交付',done:'你的报告已完成'};
let state,pendingId='',sending=false,starting=false,pdfPath='',refreshing=false;
function node(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
async function request(route,data){const r=await fetch(route+(data?'':'?'+new URLSearchParams({workspace,project})),data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace,project,...data})}:{});const value=await r.json();if(!r.ok)throw Error(value.error||r.statusText);return value}
const api=(route,data)=>request('/api/lab/report/'+route,data);
function fileURL(path){return '/api/lab/file?'+new URLSearchParams({workspace,project,path})}
function showError(text){$('errorBox').hidden=!text;$('error').textContent=text||''}
function friendlyFailure(text){
 if(/503|service_unavailable|Service is too busy/i.test(text))return '模型服务暂时繁忙。已有稿件和进度已保存，服务恢复后可以接着写，无需重新提交材料。';
 if(/429|rate.limit/i.test(text))return '模型服务暂时限流。进度已保存，请稍后恢复。';
 return text;
}
function render(v){
 state=v;$('runView').hidden=false;$('intakeCard').hidden=true;
 const s=v.report_workflow,p=s.pending,output=s.outputs?.[s.stage]||{};
 const busy=!!v.busy,questions=p?(p.questions||output.questions||[]):[];
 const needsAnswer=!!p&&!p.checkpoint&&questions.length>0;
 $('projectTitle').textContent=v.title||'你的实验报告';
 $('status').textContent=busy?'正在生成':needsAnswer?'等你回答':s.stage==='done'?'已完成':s.status==='failed'?'遇到问题':'进度已保存';
 $('heading').textContent=needsAnswer?'需要你补充一点信息':busy||s.stage==='done'?headings[s.stage]||'正在准备报告':'进度已保存';
 $('stageHint').textContent=needsAnswer?'回答后自动继续，不需要确认提纲或样稿。':busy?'可以离开页面，任务在本机继续，进度自动保存。':s.stage==='done'?'报告已保存，可以直接打开或下载。':'已有内容保留，具体状态见下方。';
 const index=stages[s.stage]??0;$('progress').value=index;
 $('progress').setAttribute('aria-valuetext',s.stage==='done'?'已完成':`第 ${Math.min(index+1,5)} 阶段，共 5 阶段：${steps[Math.min(index,4)]}`);
 $('stages').replaceChildren(...steps.map((text,i)=>{const li=node('li',text);li.className=i<index?'finished':i===index?'current':'';if(i===index)li.setAttribute('aria-current','step');return li}));
 const progress=s.progress,latest=s.debug?.latest;
 $('liveProgress').textContent=busy&&progress?`${progress.label} · ${progress.completed}/${progress.total} · ${progress.topic||''}`:busy&&latest?`最近活动：${new Date(latest.at).toLocaleTimeString()} · ${latest.status==='completed'?'已保存一个步骤':'正在处理当前步骤'}`:'';
 $('replyBox').hidden=!needsAnswer||busy;$('questions').replaceChildren();
 for(const [i,q] of questions.entries()){const item=node('div');item.className='question';item.append(node('p',`${i+1}. ${q.question}`));if(q.reason){const why=node('p',q.reason);why.className='reason';item.append(why)}$('questions').append(item)}
 if(p&&pendingId!==p.id){pendingId=p.id;$('answer').value=''}
 $('answerActions').replaceChildren();if(needsAnswer){const b=node('button',sending?'正在提交…':'回答并继续');b.disabled=sending;b.onclick=submit;$('answerActions').append(b)}
 $('continue').hidden=busy||needsAnswer||s.stage==='done'||!['paused','failed','ready','interrupted'].includes(s.status);
 $('continue').disabled=starting;$('continue').textContent=starting?'正在恢复…':'恢复已保存的任务';
 const report=v.report,stoppedWithDraft=!busy&&['paused','failed','awaiting_user','needs_attention'].includes(s.status);
 const showPdf=!!report?.pdf&&(['delivery','done'].includes(s.stage)||stoppedWithDraft);
 $('pdfCard').hidden=!showPdf;
 if(showPdf){const url=fileURL(report.pdf);$('openPdf').href=url;$('downloadPdf').href=url;$('downloadPdf').setAttribute('download','实验报告.pdf');$('pdfState').textContent=s.stage==='done'?'报告已完成':stoppedWithDraft?'完整草稿已保存，修订或终审尚未完成':'完整稿已保存，尚有明确缺项';if(pdfPath!==report.pdf){pdfPath=report.pdf;$('pdfPreview').src=url}}
 showError(needsAnswer||busy?'':friendlyFailure(s.error||''));
 const usage=v.usage||{},limits=v.limits||{},budget=s.budget;
 $('usage').textContent=`项目累计 ${(usage.tokens||0).toLocaleString()} tokens · 已知估算 $${Number(usage.cost_usd||0).toFixed(4)} USD`+(usage.cost_cny!=null?` · ¥${Number(usage.cost_cny).toFixed(4)} CNY`:``)+(budget?`；当前报告预算已用 $${Math.max(0,(usage.cost_usd||0)-budget.baseline_cost_usd).toFixed(4)} / $${limits.max_cost} USD`:'')+'。含缓存输入；以服务商实际账单为准。';
 $('history').replaceChildren();for(const row of s.interactions||[]){const d=node('details');d.append(node('summary','已保存的回答'),node('pre',row.text));$('history').append(d)}
 $('debug').replaceChildren();if(latest){$('debug').append(node('p',`最近保存：${latest.name} · ${latest.status}`));if(s.debug.timeline){const a=node('a','查看调试记录');a.href=fileURL(s.debug.timeline);a.target='_blank';$('debug').append(a)}}
 if(s.error)$('debug').append(node('pre',s.error));
 $('stopRun').hidden=!busy;
}
async function refresh(){if(!project||refreshing)return;refreshing=true;try{render(await api('state'))}catch(e){$('runView').hidden=false;showError(e.message);$('status').textContent='连接中断'}finally{refreshing=false}}
async function submit(){if(sending)return;const text=$('answer').value.trim();if(!text){showError('请先填写回答。');return}sending=true;let error='';try{render(state);await api('reply',{text,decision:'answer',pending_id:pendingId,advance:true,automatic:true});await refresh()}catch(e){error=e.message}finally{sending=false;if(state)render(state);if(error)showError(error)}}
$('continue').onclick=async()=>{if(starting)return;starting=true;let error='';try{render(state);await api('start',{automatic:true});await refresh()}catch(e){error=e.message}finally{starting=false;if(state)render(state);if(error)showError(error)}};
$('stopRun').onclick=async()=>{try{await request('/api/lab/pause',{});await refresh()}catch(e){showError(e.message)}};
$('chooseLibrary').onclick=async()=>{try{const r=await request('/api/pick',{kind:'folder'});if(r.path)$('libraryPath').value=r.path}catch(e){$('createError').textContent=e.message}};
$('createForm').onsubmit=async e=>{e.preventDefault();$('createSubmit').disabled=true;$('createError').textContent='正在读取材料库、建立内容索引…';try{workspace=$('workspaceInput').value.trim();const r=await api('create',{title:$('newTitle').value,library_path:$('libraryPath').value.trim(),student_id:$('studentId').value,instructions:$('newInstructions').value,max_cost:Number($('maxCost').value)});project=r.project;location.href='/report?'+new URLSearchParams({workspace,project})}catch(e){$('createError').textContent=e.message}finally{$('createSubmit').disabled=false}};
(async()=>{try{
 if(!workspace){workspace=localStorage.getItem('wisdom-report-workspace')||'';if(!workspace)workspace=(await request('/api/health')).workspace}
 localStorage.setItem('wisdom-report-workspace',workspace);$('homeLink').href='/?'+new URLSearchParams({workspace});$('studioEntry').href='/studio?'+new URLSearchParams({workspace,...(project?{project}:{})});
 if(project){await refresh();setInterval(refresh,2500);return}
 $('intakeCard').hidden=false;$('status').textContent='准备材料';$('workspaceInput').value=workspace;
 const rows=await request('/api/lab/projects');$('projectList').hidden=!rows.length;
 for(const p of rows){const a=node('a',p.title);a.className='project-link';a.href='/report?'+new URLSearchParams({workspace,project:p.id});$('projects').append(a)}
 }catch(e){$('createError').textContent=e.message}})();
