'use strict';
const $ = id => document.getElementById(id);
const state = {workspace:'',session:'',mode:'general',depth:'auto',busy:false,online:false,following:true,status:null,source:null,turns:new Map(),attachments:[],sessionRows:[],filePath:'.',activity:0,limits:{max_steps:100,max_cost:.5,max_seconds:3600,max_tokens:0}};
const emptyGoal = $('goalPanel').innerHTML;
const escapeHTML = text => String(text ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function inline(text){return escapeHTML(text).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,(all,label,url)=>/^(https?:\/\/|\/api\/file\?)/.test(url)?`<a href="${url}" target="_blank" rel="noopener">${label}</a>`:/^(?![a-z]+:)(?!\/)[^<>]+\.(pdf|json|jsonl|md|txt|png|svg)$/i.test(url)?`<a href="/api/file?${new URLSearchParams({workspace:state.workspace,path:url.replaceAll('&amp;','&')})}" target="_blank" rel="noopener">${label}</a>`:label);}
function markdown(text){
  const blocks=[];
  text=String(text||'').replace(/```([^\n]*)\n([\s\S]*?)(?:```|$)/g,(_,lang,code)=>{blocks.push(`<div class="code-block"><div class="code-head"><span>${escapeHTML(lang||'代码')}</span><button type="button" data-copy>复制</button></div><pre><code>${escapeHTML(code.replace(/\n$/,''))}</code></pre></div>`);return `\n\n@@BLOCK${blocks.length-1}@@\n\n`;});
  const lines=text.split('\n');let html='',list=null;
  const closeList=()=>{if(list){html+=`</${list}>`;list=null;}};
  for(let i=0;i<lines.length;i++){
    const line=lines[i],block=line.match(/^@@BLOCK(\d+)@@$/);
    if(block){closeList();html+=blocks[+block[1]];continue;}
    if(!line.trim()){closeList();continue;}
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      closeList();const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|');html+='<div class="table-wrap"><table><thead><tr>'+cells(line).map(x=>`<th>${inline(x.trim())}</th>`).join('')+'</tr></thead><tbody>';i++;
      while(i+1<lines.length&&lines[i+1].includes('|')&&lines[i+1].trim()){i++;html+='<tr>'+cells(lines[i]).map(x=>`<td>${inline(x.trim())}</td>`).join('')+'</tr>';}
      html+='</tbody></table></div>';continue;
    }
    let m=line.match(/^(#{1,3})\s+(.+)/);if(m){closeList();html+=`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`;continue;}
    m=line.match(/^\s*(?:([-*])|\d+\.)\s+(.+)/);if(m){const type=m[1]?'ul':'ol';if(list!==type){closeList();list=type;html+=`<${type}>`;}html+=`<li>${inline(m[2])}</li>`;continue;}
    closeList();if(line.startsWith('> ')){html+=`<blockquote>${inline(line.slice(2))}</blockquote>`;}else if(/^---+$/.test(line)){html+='<hr>';}else{html+=`<p>${inline(line)}</p>`;}
  }
  closeList();return html;
}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,5000);}
function readLocal(key,fallback=null){try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}}
function writeLocal(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{}}
const draftKey=(workspace=state.workspace,session=state.session)=>'wisdom.draft:'+workspace+'|'+session;
function saveDraft(){if(!state.session)return;writeLocal(draftKey(),{text:$('input').value,attachments:state.attachments,mode:state.mode,depth:state.depth,limits:state.limits});}
function restoreDraft(){const draft=readLocal(draftKey(),{});$('input').value=draft.text||'';state.attachments=draft.attachments||[];state.limits=draft.limits||state.limits;state.depth=draft.depth||state.status?.depth||'auto';$('depth').value=state.depth;renderAttachments();resizeInput();return draft.mode;}
function resizeInput(){$('input').style.height='auto';$('input').style.height=Math.min(Math.max($('input').scrollHeight,64),220)+'px';}
function followScroll(force=false){if(force){state.following=true;$('jumpLatest').hidden=true;}if(!state.following)return;cancelAnimationFrame(followScroll.frame);followScroll.frame=requestAnimationFrame(()=>{if(state.following)$('scroll').scrollTop=$('scroll').scrollHeight;});}
async function api(route,data){let response;try{response=await fetch(route,{...(data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});}catch{connected(false);throw new Error('无法连接本机服务。请运行“启动个人Agent.cmd”，恢复连接后继续。');}let result;try{result=await response.json();}catch{throw new Error('本机服务没有返回有效结果，请确认服务仍在运行。');}if(!response.ok){const error=new Error(result.error||'请求失败');error.status=response.status;throw error;}return result;}
const query=()=>new URLSearchParams({workspace:state.workspace,session:state.session}).toString();
async function action(action,extra={}){return api('/api/action',{workspace:state.workspace,session:state.session,action,...extra});}
function readableResult(text){return {MaxTokens:'已到 Token 上限；可在额度中调整后继续。',MaxSteps:'已到模型步骤上限；可在“额度”中调整后继续。',MaxCost:'已到估算费用上限；可在“额度”中调整后继续。',MaxSeconds:'已到运行时长上限；可在“额度”中调整后继续。'}[text]||text;}
function setAnswer(body,text){body.dataset.raw=text;body.innerHTML=markdown(readableResult(text));}
function message(role,text){$('welcome').hidden=true;const row=document.createElement('article');row.className=`message ${role}`;const body=document.createElement('div');body.className='body';let content=body;if(role==='assistant'){const avatar=document.createElement('div');avatar.className='avatar';avatar.innerHTML='<img src="/paperfox.svg" alt="纸狐">';row.append(avatar);content=document.createElement('div');content.className='message-text';setAnswer(content,text);const copy=document.createElement('button');copy.type='button';copy.className='copy-answer';copy.dataset.copyMessage='';copy.textContent='复制回复';copy.title='复制完整回复（Markdown原文）';body.append(content,copy);}else{body.textContent=text;}row.append(body);$('messages').append(row);followScroll();return content;}
function setMode(mode){state.mode=mode;document.querySelectorAll('.modes button').forEach(b=>{b.classList.toggle('active',b.dataset.mode===mode);b.setAttribute('aria-pressed',String(b.dataset.mode===mode));});$('modeHint').textContent={consult:'快速问答，能读本地文件',general:'回答问题，也能动手完成工作',goal:'设好额度，持续推进到达标'}[mode];$('input').placeholder={consult:'问个问题，或让我读一份本地文件…',general:'说说你想做什么…',goal:'描述目标、期望的结果，以及需要保留的检查点…'}[mode];$('limitsButton').hidden=mode!=='goal';updateBusy();}
function updateBusy(){
  $('input').disabled=!state.session;
  $('depth').disabled=!state.session||state.loading;
  $('filesButton').disabled=!state.session||state.loading;
  $('exportChat').disabled=!state.session||state.loading;
  document.querySelectorAll('.modes button,.suggestions button').forEach(button=>button.disabled=!state.session||state.loading);
  $('pause').hidden=!state.busy;
  const canSteer=state.status?.mode==='goal'&&state.mode!=='general';
  $('send').disabled=!state.online||state.loading||state.sending||!state.session||(state.busy&&!canSteer)||(!$('input').value.trim()&&!state.attachments.length);
  $('send').title=state.busy&&canSteer?(state.mode==='consult'?'插问，回答后继续目标':'补充目标要求'):'发送';
  const goalPhase=state.mode==='goal'&&!state.busy?{paused:'目标已暂停',waiting_for_user:'等待你的确认',budget_exhausted:'已到额度上限，可调整后继续',completed:'目标已完成',cancelled:'目标已结束'}[state.status?.goal?.status]:null;
  $('phase').textContent=state.loading?'正在打开对话':state.sending?'正在发送':goalPhase||state.phase||'准备就绪';
  $('goalPanel').querySelector('[data-goal="continue"]')?.toggleAttribute('disabled',!state.online||state.busy||state.loading);
}
function updateStatus(status){if(!status)return;state.status=status;$('title').textContent=status.title||'新对话';document.title=`${status.title||'纸狐'} · 纸狐`;
  if(!state.busy){setMode(status.mode||'general');state.depth=status.depth||'auto';$('depth').value=state.depth;}$('depth').disabled=!state.session||state.loading;$('depth').title='本轮策略：'+(status.response_policy?.depth||'自动')+' · '+(status.response_policy?.reason||'');
  const totals=status.totals||{},usage=totals.usage||{};const count=usage.total_tokens||((usage.prompt_tokens||0)+(usage.completion_tokens||0));$('usage').textContent=`${Number(count).toLocaleString()} tokens · ≈ $${Number(totals.cost||0).toFixed(4)}${status.usage_uncertain?' · 部分用量未知':''}`;
  const goal=status.goal;if(!goal){$('goalPanel').innerHTML=emptyGoal;updateBusy();return;}
  const labels={running:'正在生长',paused:'已暂停',waiting_for_job:'等待后台作业',completed:'目标已完成',cancelled:'目标已结束',budget_exhausted:'已到额度上限',waiting_for_user:'等待你的输入'};
  const finished=['completed','cancelled'].includes(goal.status);
  $('goalPanel').innerHTML=`<span class="goal-tag">${labels[goal.status]||escapeHTML(goal.status)}</span><h3 class="goal-objective">${escapeHTML(goal.objective)}</h3><p class="goal-summary">${escapeHTML(readableResult(goal.summary))}</p>${goal.plan?.length?`<ol class="goal-plan">${goal.plan.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ol>`:''}<div class="goal-metrics">模型步骤 ${goal.steps} / ${goal.max_steps||'不限'}<br>估算费用 $${Number(goal.cost||0).toFixed(4)} / $${goal.max_cost||'不限'}<br>累计 Token ${Number(goal.tokens||0).toLocaleString()} / ${goal.max_tokens||'不限'}<br>停止原因 ${escapeHTML(goal.stop_reason||'运行中')}<br>累计运行 ${Math.floor(goal.elapsed_seconds/60)} 分钟 / ${goal.max_seconds?Math.round(goal.max_seconds/60)+' 分钟':'不限'}${Object.keys(goal.jobs||{}).length?'<br>后台作业 '+Object.entries(goal.jobs).map(([id,s])=>escapeHTML(id+' · '+s)).join('<br>'):''}</div><div class="goal-actions">${!finished?'<button data-goal="continue" class="primary">继续目标</button><button data-goal="limits">调整额度</button><button data-goal="cancel_goal">结束</button>':''}</div>${goal.evidence?.length?'<h4>结果与证据</h4><div class="goal-evidence">'+goal.evidence.map(x=>`<div>${escapeHTML(x)}</div>`).join('')+'</div>':''}`;
  updateBusy();
}
function renderSessions(){const search=$('sessionSearch').value.trim().toLocaleLowerCase(),rows=state.sessionRows.filter(row=>(row.title||'新对话').toLocaleLowerCase().includes(search));$('sessions').replaceChildren();for(const row of rows){const button=document.createElement('button');button.className='session'+(row.session_id===state.session?' active':'');if(row.session_id===state.session)button.setAttribute('aria-current','true');const title=document.createElement('span');title.textContent=row.title||'新对话';button.append(title);const small=document.createElement('small');small.textContent=({consult:'咨询',general:'通用',goal:'Goal'}[row.mode]||'对话')+' · '+new Date(row.updated_at||row.created_at).toLocaleDateString('zh-CN');button.append(small);button.title=row.title;button.onclick=()=>loadSession(row.session_id).catch(showError);$('sessions').append(button);}if(!rows.length){const empty=document.createElement('p');empty.className='history-empty';empty.textContent=search?'没有匹配标题，清空搜索可查看全部。':'还没有历史对话。';$('sessions').append(empty);}}
async function sessions(){const workspace=state.workspace,rows=await api('/api/sessions?'+new URLSearchParams({workspace}));if(workspace!==state.workspace)return;state.sessionRows=rows;renderSessions();}
function connected(online){state.online=online;$('connection').textContent=online?'本机服务已连接':'连接断开，正在重连';$('connectionNotice').hidden=online;$('connectionHint').textContent='本机服务未连接。草稿会保留；若服务已关闭，请运行“启动个人Agent.cmd”。';document.querySelector('.dot').classList.toggle('offline',!online);updateBusy();}
function activity(event){if(!['tool_call','tool_result','context_preparing','api_retry','job_finished','paused','compaction','steering_applied','response_policy','first_answer','api_end'].includes(event.kind))return;state.activity++;$('activityCount').textContent=state.activity;if(state.activity===1)$('activities').replaceChildren();const detail=document.createElement('details'),summary=document.createElement('summary');const name=event.name||event.tool||event.tool_name||'';summary.textContent=({tool_call:'使用工具',tool_result:'工具返回',context_preparing:'整理上下文',api_retry:'重试连接',job_finished:'后台作业结束',paused:'暂停',compaction:'上下文摘要',steering_applied:'已收到目标补充',response_policy:'本轮回答策略',first_answer:'首个答案耗时',api_end:'模型调用结束'}[event.kind]||event.kind)+(name?' · '+name:'');const pre=document.createElement('pre');const {id,kind,time,turn_id,...payload}=event;pre.textContent=JSON.stringify(payload,null,2).slice(0,16000);detail.append(summary,pre);$('activities').prepend(detail);while($('activities').children.length>80)$('activities').lastChild.remove();}
function renderPending(items){state.pending=items;$('pendingMessages').replaceChildren();for(const item of items){const row=document.createElement('div');row.className='pending-row';const text=document.createElement('span');text.textContent=(item.interrupted?'中断待确认':item.processing?'正在处理':item.mode==='consult'?'待回答':'待合入')+' · '+item.text;row.append(text);const recover=document.createElement('button');recover.textContent='取回';recover.disabled=!!item.processing;recover.title='取回输入框，移出待处理队列';recover.onclick=async()=>{const workspace=state.workspace,session=state.session;recover.disabled=true;try{await api('/api/action',{workspace,session,action:'discard_pending',client_id:item.client_id});if(workspace===state.workspace&&session===state.session){$('input').value=[$('input').value,item.text].filter(Boolean).join('\n');saveDraft();resizeInput();updateBusy();$('input').focus();}else{const key=draftKey(workspace,session),draft=readLocal(key,{});draft.text=[draft.text,item.text].filter(Boolean).join('\n');writeLocal(key,draft);}}catch(err){recover.disabled=false;showError(err);}};row.append(recover);$('pendingMessages').append(row);}$('pendingMessages').hidden=!items.length;}
function streamBody(event){const key=event.segment_id||event.turn_id;let segment=state.turns.get(key);if(!segment){segment={text:'',body:null,turn_id:event.turn_id};state.turns.set(key,segment);}if(!segment.body)segment.body=message('assistant','');return segment;}
function eventReceived(event){
  if(event.kind==='resync'){saveDraft();applySnapshot(event.snapshot);return;}
  activity(event);
  if(event.kind==='state')updateStatus(event.status);
  else if(event.kind==='pending')renderPending(event.pending);
  else if(event.kind==='busy'){state.busy=event.busy;state.phase=event.phase;if(!event.busy){setMode(state.status?.mode||state.mode);saveDraft();sessions().catch(()=>{});}updateBusy();}
  else if(event.kind==='user_message'){if(!event.queued){message('user',event.text);followScroll(true);}}
  else if(event.kind==='answer_delta'){
    const segment=streamBody(event);segment.text+=event.text;
    if(!segment.scheduled){segment.scheduled=true;requestAnimationFrame(()=>{segment.scheduled=false;setAnswer(segment.body,segment.text);followScroll();});}
    state.phase='正在回答';updateBusy();
  }else if(event.kind==='assistant_message'){
    const segment=streamBody(event);segment.text=event.text;setAnswer(segment.body,event.text);followScroll();
  }else if(event.kind==='answer_end'){
    const hadBody=[...state.turns.values()].some(segment=>segment.turn_id===event.turn_id&&segment.body);
    if(event.display_result||(event.display_result===undefined&&!hadBody&&event.text))message('assistant',event.text);
    for(const [key,segment] of state.turns)if(segment.turn_id===event.turn_id)state.turns.delete(key);followScroll();
  }else if(event.kind==='error'){message('error',event.message);toast(event.message);}
  else if(event.kind==='tool_progress'){state.phase=`${event.name} 已运行 ${Math.floor(event.seconds)} 秒 · 可暂停`;updateBusy();}
  else {const phases={api_wait:'等待模型响应',api_first_event:'已收到模型响应',model_reasoning:'模型正在深入分析',first_answer:'正在回答',tool_call:'正在使用本地工具',tool_result:'工具已返回',context_preparing:'整理上下文',api_retry:'连接重试中',paused:'已暂停'};if(phases[event.kind]){state.phase=phases[event.kind];updateBusy();}}
}
let loadGeneration=0;
async function loadSession(id=null,isNew=false,workspace=state.workspace){
  saveDraft();const generation=++loadGeneration;state.loading=true;updateBusy();
  try{const snapshot=isNew?await api('/api/new',{workspace}):await api('/api/session?'+new URLSearchParams({workspace,...(id?{session:id}:{})}));if(generation!==loadGeneration)return;applySnapshot(snapshot);}finally{if(generation===loadGeneration){state.loading=false;updateBusy();}}
}
function applySnapshot(snapshot){
  clearTimeout(reconnectTimer);
  const sameSession=state.session===snapshot.session_id&&state.workspace===snapshot.workspace,scrollTop=$('scroll').scrollTop,following=sameSession?state.following:true;
  state.following=following;
  state.source?.close();state.source=null;
  state.session=snapshot.session_id;state.workspace=snapshot.workspace;state.busy=snapshot.busy;state.phase=snapshot.phase;state.turns.clear();$('messages').replaceChildren();$('welcome').hidden=snapshot.messages.length>0;for(const item of snapshot.messages)message(item.role,item.text);
  if(snapshot.active_text){const body=message('assistant',snapshot.active_text);state.turns.set(snapshot.active_segment||snapshot.active_turn,{text:snapshot.active_text,body,turn_id:snapshot.active_turn});}
  updateStatus(snapshot.status);const draftMode=restoreDraft();setMode(draftMode||snapshot.status?.mode||'general');renderPending(snapshot.pending||[]);
  $('model').textContent=snapshot.model+' · 自动保存';$('workspaceLabel').textContent=state.workspace.split(/[\\/]/).filter(Boolean).pop()||state.workspace;$('workspaceButton').title=state.workspace;
  try{localStorage.setItem('wisdom.workspace',state.workspace);localStorage.setItem('wisdom.session',state.session);}catch{}writeLocal('wisdom.session:'+state.workspace,state.session);
  const url=new URL(location.href);url.searchParams.set('workspace',state.workspace);url.searchParams.set('session',state.session);history.replaceState(null,'',url);
  const source=new EventSource('/api/events?'+query()+'&after='+snapshot.cursor+'&stream='+encodeURIComponent(snapshot.stream_id||''));state.source=source;
  source.onopen=()=>{if(state.source===source)connected(true);};source.onerror=()=>{if(state.source===source)connected(false);};source.onmessage=e=>{if(state.source!==source)return;try{eventReceived(JSON.parse(e.data));}catch(err){console.error(err);}};
  connected(true); // A fresh HTTP snapshot already confirms the service is reachable.
  state.activity=0;$('activityCount').textContent='0';$('activities').innerHTML='<p class="muted">工具与执行状态会显示在这里。</p>';
  for(const event of snapshot.activities||[])activity(event);
  if(!sameSession){$('panel').hidden=!snapshot.status?.goal||!matchMedia('(min-width:851px)').matches;$('sessionSearch').value='';}sessions().catch(showError);$('jumpLatest').hidden=following;if(following)followScroll(true);else $('scroll').scrollTop=scrollTop;$('sidebar').classList.remove('open');
}
function renderAttachments(){$('attachments').replaceChildren();state.attachments.forEach((path,index)=>{const chip=document.createElement('span');chip.className='attachment';chip.textContent='▤ '+path;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.title='移除引用';remove.setAttribute('aria-label','移除引用 '+path);remove.onclick=()=>{state.attachments.splice(index,1);renderAttachments();saveDraft();};chip.append(remove);$('attachments').append(chip);});$('selectedFiles').textContent=`已引用 ${state.attachments.length} 个文件`;updateBusy();}
let fileGeneration=0;
async function files(path='.'){
  clearTimeout(files.timer);
  const generation=++fileGeneration,workspace=state.workspace;const result=await api('/api/files?'+new URLSearchParams({workspace,path,q:$('fileSearch').value}));if(generation!==fileGeneration||workspace!==state.workspace)return;state.filePath=result.path;$('filePath').textContent=result.path;$('fileUp').disabled=result.path==='.';$('fileList').replaceChildren();
  for(const item of result.files){const row=document.createElement('div');row.className='file-row';if(item.directory){const button=document.createElement('button');button.type='button';button.textContent='▱ '+item.name;button.onclick=()=>{$('fileSearch').value='';files(item.path).catch(showError);};row.append(button);}else{const label=document.createElement('label'),checkbox=document.createElement('input'),name=document.createElement('span');label.className='file-choice';checkbox.type='checkbox';checkbox.checked=state.attachments.includes(item.path);checkbox.onchange=()=>{if(checkbox.checked){if(!state.attachments.includes(item.path))state.attachments.push(item.path);}else state.attachments=state.attachments.filter(x=>x!==item.path);renderAttachments();saveDraft();};name.textContent=item.name;label.append(checkbox,name);row.append(label);const a=document.createElement('a');a.textContent='预览 ↗';a.setAttribute('aria-label','预览 '+item.name);a.target='_blank';a.rel='noopener';a.href='/api/file?'+new URLSearchParams({workspace,path:item.path});row.append(a);}$('fileList').append(row);}
  if(!result.files.length)$('fileList').textContent='没有匹配文件。';$('fileCount').textContent=result.truncated?`显示前 250 项，共 ${result.total} 项；输入文件名缩小范围。`:`${result.total??result.files.length} 项`;
}
function activeGoal(){const goal=state.status?.goal;return goal&&!['completed','cancelled'].includes(goal.status)?goal:null;}
function showLimits(){const limits=activeGoal()||state.limits;$('maxSteps').value=limits.max_steps;$('maxCost').value=limits.max_cost;$('maxMinutes').value=limits.max_seconds/60;$('maxTokens').value=limits.max_tokens||0;$('limitsDialog').showModal();}
function showError(error){const text=error.message||String(error),dialog=document.querySelector('dialog[open]');if(!dialog){toast(text);return;}let alert=dialog.querySelector('.dialog-error');if(!alert){alert=document.createElement('p');alert.className='dialog-error';alert.setAttribute('role','alert');dialog.append(alert);}alert.textContent=text;}
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>dialog.querySelector('.dialog-error')?.remove()));
$('composer').onsubmit=async e=>{
  e.preventDefault();if($('send').disabled)return;const original=$('input').value.trim();if(!original&&!state.attachments.length){$('input').focus();return;}
  const text=original+(state.attachments.length?'\n\n引用当前工作目录文件（按需读取）：\n'+state.attachments.map(x=>'- '+x).join('\n'):'');
  const workspace=state.workspace,session=state.session,key=draftKey(),draftText=$('input').value,draftFiles=JSON.stringify(state.attachments);saveDraft();state.sending=true;updateBusy();
  try{await api('/api/action',{workspace,session,action:'send',text,mode:state.mode,depth:state.depth,limits:state.limits,client_id:crypto.randomUUID()});const saved=readLocal(key,{});if(saved.text===draftText&&JSON.stringify(saved.attachments||[])===draftFiles)writeLocal(key,{});if(session===state.session&&workspace===state.workspace){if($('input').value===draftText&&JSON.stringify(state.attachments)===draftFiles){$('input').value='';state.attachments=[];renderAttachments();resizeInput();$('input').focus();}saveDraft();}}
  catch(err){showError(err);}finally{state.sending=false;updateBusy();}
};
$('input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('composer').requestSubmit();}};
$('input').oninput=()=>{resizeInput();saveDraft();updateBusy();};
$('scroll').addEventListener('scroll',()=>{const el=$('scroll');state.following=el.scrollHeight-el.scrollTop-el.clientHeight<60;$('jumpLatest').hidden=state.following;},{passive:true});
$('jumpLatest').onclick=()=>{followScroll(true);$('jumpLatest').hidden=true;};
$('sessionSearch').oninput=renderSessions;
document.querySelectorAll('.modes button').forEach(button=>button.onclick=()=>{setMode(button.dataset.mode);saveDraft();if(!state.busy||state.mode==='general')action('mode',{mode:state.mode}).catch(showError);if(state.mode==='goal'&&matchMedia('(min-width:851px)').matches)$('panel').hidden=false;});
document.querySelectorAll('.suggestions button').forEach(button=>button.onclick=()=>{setMode(button.dataset.mode);$('input').value=button.dataset.prompt;saveDraft();resizeInput();$('input').focus();updateBusy();if(state.mode==='goal'){if(matchMedia('(min-width:851px)').matches)$('panel').hidden=false;showLimits();}});
$('pause').onclick=()=>action('pause').catch(showError);
$('newChat').onclick=()=>loadSession(null,true).catch(showError);
$('refreshSessions').onclick=()=>sessions().catch(showError);
$('exportChat').onclick=()=>{if(!state.session)return;const link=document.createElement('a');link.href='/api/export?'+query();link.download=`conversation-${state.session}.json`;link.click();};
$('rename').onclick=()=>{$('renameInput').value=state.status?.title||'新对话';$('renameDialog').showModal();$('renameInput').select();};
$('closeRename').onclick=()=>$('renameDialog').close();
$('renameForm').onsubmit=async e=>{e.preventDefault();const title=$('renameInput').value.trim();if(!title)return;try{await action('rename',{title});$('renameDialog').close();}catch(err){showError(err);}};
$('togglePanel').onclick=()=>$('panel').hidden=!$('panel').hidden;
$('closePanel').onclick=()=>$('panel').hidden=true;
$('menu').onclick=()=>$('sidebar').classList.toggle('open');
$('help').onclick=()=>$('helpDialog').showModal();
$('workspaceButton').onclick=()=>{$('workspaceInput').value=state.workspace;$('workspaceDialog').showModal();};
$('pickFolder').onclick=async()=>{try{const result=await api('/api/pick',{kind:'folder',workspace:state.workspace});if(result.path)$('workspaceInput').value=result.path;}catch(err){showError(err);}};
$('applyWorkspace').onclick=async()=>{try{const workspace=$('workspaceInput').value.trim();await loadSession(readLocal('wisdom.session:'+workspace),false,workspace);$('workspaceDialog').close();}catch(err){showError(err);}};
$('filesButton').onclick=()=>{$('fileSearch').value='';$('fileList').textContent='正在读取文件…';$('filesDialog').showModal();$('selectedFiles').textContent=`已引用 ${state.attachments.length} 个文件`;files().catch(showError);};
$('fileSearch').oninput=()=>{clearTimeout(files.timer);files.timer=setTimeout(()=>files(state.filePath).catch(showError),180);};
$('closeFiles').onclick=()=>$('filesDialog').close();
$('finishFiles').onclick=()=>{$('filesDialog').close();$('input').focus();};
$('fileUp').onclick=()=>{const parts=state.filePath.split(/[\\/]/);parts.pop();$('fileSearch').value='';files(parts.join('/')||'.').catch(showError);};
$('limitsButton').onclick=showLimits;
$('depth').onchange=()=>{state.depth=$('depth').value;saveDraft();action('depth',{depth:state.depth}).catch(showError);};
$('saveLimits').onclick=async()=>{const limits={max_steps:Number($('maxSteps').value),max_cost:Number($('maxCost').value),max_seconds:Number($('maxMinutes').value)*60,max_tokens:Number($('maxTokens').value)};if(Object.entries(limits).some(([k,x])=>!Number.isFinite(x)||(k==='max_tokens'?x<0:x<=0))||!Number.isInteger(limits.max_steps)||!Number.isInteger(limits.max_tokens)){showError(new Error('步骤、费用与时长需大于0；步骤与Token需为整数，Token为0表示不限。'));return;}try{if(activeGoal())await action('limits',limits);state.limits=limits;saveDraft();$('limitsDialog').close();toast('运行额度已保存');}catch(err){showError(err);}};
$('goalPanel').onclick=e=>{const operation=e.target.closest('[data-goal]')?.dataset.goal;if(!operation)return;if(operation==='limits')showLimits();else if(operation==='cancel_goal')$('endGoalDialog').showModal();else{setMode('goal');action(operation).catch(showError);}};
$('confirmEndGoal').onclick=()=>{action('cancel_goal').then(()=>$('endGoalDialog').close()).catch(showError);};
$('messages').onclick=async e=>{const button=e.target.closest('[data-copy],[data-copy-message]');if(!button)return;const text=button.hasAttribute('data-copy-message')?button.closest('.body').querySelector('.message-text').dataset.raw:button.closest('.code-block').querySelector('code').textContent;const label=button.hasAttribute('data-copy-message')?'复制回复':'复制';try{await navigator.clipboard.writeText(text);button.textContent='已复制';setTimeout(()=>button.textContent=label,1400);}catch{toast('复制失败，可选择文字手动复制');}};
let reconnectTimer=null;
async function connectPage(){
  if(state.connecting)return;state.connecting=true;$('reconnect').disabled=true;clearTimeout(reconnectTimer);updateBusy();
  try{
    if(state.session){await loadSession(state.session);}
    else{const url=new URL(location.href);let lastWorkspace='';try{lastWorkspace=localStorage.getItem('wisdom.workspace')||'';}catch{}const workspace=url.searchParams.get('workspace')||lastWorkspace;const bootstrap=await api('/api/bootstrap?'+new URLSearchParams({workspace}));let id=url.searchParams.get('session')||bootstrap.selected_session_id||readLocal('wisdom.session:'+bootstrap.workspace);if(!bootstrap.sessions.some(x=>x.session_id===id))id=null;await loadSession(id,false,bootstrap.workspace);if(!bootstrap.configured)toast('当前未配置 API 密钥，请在项目 .env 中配置后重启服务。');}
  }catch(err){connected(false);if(err.status){$('connectionHint').textContent=err.message+'。请通过右上角选择有效工作目录。';}else if(!state.session){reconnectTimer=setTimeout(connectPage,5000);}}
  finally{state.connecting=false;$('reconnect').disabled=false;updateBusy();}
}
$('reconnect').onclick=connectPage;
window.addEventListener('beforeunload',()=>{saveDraft();clearTimeout(reconnectTimer);state.source?.close();});
connectPage();
