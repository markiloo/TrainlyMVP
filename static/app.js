const app=document.querySelector('#app'),toastEl=document.querySelector('#toast');
const S={user:null,csrf:'',modules:[],module:null,view:'home',attempt:null,progress:null,asked:new Set(),config:{max_video_bytes:1024**3,max_video_seconds:7200,ai_enabled:false,default_pass_score:70},uploadState:null,localPreview:null,draft:null,selectedQuestion:null,editorSeek:null,admin:null};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(s){toastEl.textContent=s;toastEl.classList.add('show');setTimeout(()=>toastEl.classList.remove('show'),2700)}
async function api(path,method='GET',data){const opts={method,headers:{}};if(data instanceof FormData)opts.body=data;else if(data!==undefined){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data)}if(method!=='GET'&&method!=='HEAD')opts.headers['X-CSRF-Token']=S.csrf;const r=await fetch(path,opts);let j={};try{j=await r.json()}catch{}if(!r.ok)throw Error(j.error||'Something went wrong.');return j}
function brand(){return '<a class="brand" href="#" data-home><span class="brand-mark">T</span>trainly</a>'}
let displayedPage=null;
function pageTransition(key){
  if(displayedPage===key)return;
  const previous=displayedPage;
  displayedPage=key;
  if(previous===null||!app.cloneNode||!document.body?.append||globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
  const outgoing=app.cloneNode(true);
  outgoing.classList.add('page-outgoing');
  outgoing.setAttribute('aria-hidden','true');
  document.body.append(outgoing);
  outgoing.addEventListener('animationend',()=>outgoing.remove(),{once:true});
  setTimeout(()=>outgoing.remove(),450);
  app.classList.remove('page-entering');
  void app.offsetWidth;
  app.classList.add('page-entering');
  app.addEventListener('animationend',()=>app.classList.remove('page-entering'),{once:true});
}
function shell(inner){pageTransition(S.view);app.innerHTML=`<header class="topbar">${brand()}<nav class="topnav"><span>${esc(S.user.name)} · ${S.user.role==='creator'?'Creator workspace':S.user.role==='admin'?'Admin console':'Learner space'}</span><button data-logout>Sign out</button></nav></header><main class="shell">${inner}</main>`;app.querySelector('[data-home]').onclick=e=>{e.preventDefault();home()};app.querySelector('[data-logout]').onclick=logout}
function login(adminMode=false){
  pageTransition(adminMode?'admin-login':'login');
  app.innerHTML=`<main class="login-wrap"><section class="login-brand">${brand()}<div><span class="eyebrow" style="color:var(--gold)">LEARNING THAT MOVES WORK FORWARD</span><h1>Turn good work into great learning.</h1><p>Bring training to life with focused lessons, thoughtful check-ins, and progress your team can see.</p></div><small style="color:var(--mist)">A simpler way to learn at work.</small><i class="orb"></i></section><section class="login-side"><form class="login-box" id="login"><span class="eyebrow">${adminMode?'ADMINISTRATOR':'WELCOME BACK'}</span><h2>${adminMode?'Admin sign in':'Sign in to Trainly'}</h2><p>${adminMode?'Manage creator and learner accounts for your workspace.':'Pick up where your learning journey left off.'}</p><div class="field"><label for="email">Work email</label><input id="email" type="email" value="${adminMode?'admin@trainly.local':'creator@trainly.local'}" required autocomplete="username"></div><div class="field"><label for="password">Password</label><input id="password" type="password" value="trainly" required autocomplete="current-password"></div><button class="button" style="width:100%;margin-top:8px">Sign in</button><div class="demo-box"><strong>Explore with demo accounts</strong>Creator: creator@trainly.local<br>Learner: learner@trainly.local<br>Admin: admin@trainly.local<br>Password: trainly</div><p class="switch-auth">${adminMode?'<a href="/">Standard sign in</a>':'<a href="/admin">Administrator sign in</a>'}</p></form></section></main>`;
  document.querySelector('#login').onsubmit=async e=>{
    e.preventDefault();
    try{
      const x=await api('/api/login','POST',{email:document.querySelector('#email').value,password:document.querySelector('#password').value});
      if(adminMode&&x.user.role!=='admin'){
        await fetch('/api/logout',{method:'POST',headers:{'X-CSRF-Token':x.csrf}}).catch(()=>{});
        throw Error('Admin access is required.');
      }
      S.user=x.user;S.csrf=x.csrf;
      if(x.user.role==='admin'){history.replaceState({},'', '/admin');adminHome()}
      else home();
    }catch(e){toast(e.message)}
  };
}
async function boot(){
  try{S.config=await api('/api/config')}catch{}
  const path=location.pathname.replace(/\/+$/,'')||'/';
  if(path==='/setup')return showAccountSetup(new URLSearchParams(location.hash.slice(1)).get('token'));
  const token=new URLSearchParams(location.hash.slice(1)).get('invite');
  if(token)return showInvitation(token);
  if(path==='/admin'){
    try{const x=await api('/api/me');if(x.user&&x.user.role==='admin'){S.user=x.user;S.csrf=x.csrf;adminHome()}else login(true)}catch{login(true)}
    return;
  }
  try{const x=await api('/api/me');if(x.user){S.user=x.user;S.csrf=x.csrf;home()}else login()}catch{login()}
}
async function showInvitation(token){try{const info=await api('/api/invitations/inspect','POST',{token});app.innerHTML=`<main class="login-wrap"><section class="login-brand">${brand()}<div><span class="eyebrow" style="color:var(--gold)">JOIN YOUR TEAM</span><h1>Learning starts here.</h1><p>You have been invited to ${esc(info.workspace)}.</p></div></section><section class="login-side"><form class="login-box" id="accept-invite"><span class="eyebrow">INVITATION</span><h2>Create your learner account</h2><p>${esc(info.email)}${info.module?' · '+esc(info.module):''}</p><div class="field"><label for="invite-name">Your name</label><input id="invite-name" required maxlength="100" autocomplete="name"></div><div class="field"><label for="invite-password">Password</label><input id="invite-password" type="password" required minlength="8" autocomplete="new-password"></div><button class="button" style="width:100%">Join workspace</button></form></section></main>`;document.querySelector('#accept-invite').onsubmit=async e=>{e.preventDefault();try{const result=await api('/api/invitations/accept','POST',{token,name:document.querySelector('#invite-name').value,password:document.querySelector('#invite-password').value});S.user=result.user;S.csrf=result.csrf;history.replaceState({},'',location.pathname);home()}catch(error){toast(error.message)}}}catch(error){history.replaceState({},'',location.pathname);login();toast(error.message)}}
async function showAccountSetup(token){
  if(!token){history.replaceState({},'','/');login();return toast('This setup link is incomplete.')}
  try{
    const info=await api('/api/account-setup/inspect','POST',{token});
    app.innerHTML=`<main class="login-wrap"><section class="login-brand">${brand()}<div><span class="eyebrow" style="color:var(--gold)">YOUR ACCOUNT</span><h1>One last step.</h1><p>Choose a password to finish setting up your ${esc(info.role)} account for ${esc(info.workspace)}.</p></div><small style="color:var(--mist)">Your password is never displayed or emailed.</small></section><section class="login-side"><form class="login-box" id="account-setup"><span class="eyebrow">FIRST SIGN-IN</span><h2>Set up your account</h2><p>${esc(info.email)} · ${esc(info.role==='creator'?'Creator':'Learner')}</p><div class="field"><label for="setup-name">Your name</label><input id="setup-name" required maxlength="100" value="${esc(info.name)}" autocomplete="name"></div><div class="field"><label for="setup-password">Password</label><input id="setup-password" type="password" required minlength="8" autocomplete="new-password"><span class="hint">Use at least 8 characters.</span></div><div class="field"><label for="setup-confirm">Confirm password</label><input id="setup-confirm" type="password" required minlength="8" autocomplete="new-password"></div><button class="button" style="width:100%">Save password and sign in</button></form></section></main>`;
    document.querySelector('#account-setup').onsubmit=async e=>{
      e.preventDefault();
      const password=document.querySelector('#setup-password').value,confirm=document.querySelector('#setup-confirm').value;
      if(password!==confirm)return toast('The passwords do not match.');
      try{
        const result=await api('/api/account-setup/complete','POST',{token,name:document.querySelector('#setup-name').value,password});
        S.user=result.user;S.csrf=result.csrf;history.replaceState({},'','/');home();toast('Your account is ready.')
      }catch(error){toast(error.message)}
    };
  }catch(error){history.replaceState({},'','/');login();toast(error.message)}
}

async function copyText(text){try{await navigator.clipboard.writeText(text);return true}catch{return false}}

function showSetupLink(result,account){
  const label=account?.name&&account?.email?`${account.name} (${account.email})`:account?.name||account?.email||'the new account';
  const link=location.origin+'/setup#token='+encodeURIComponent(result.token);
  const share=appModal('Share the setup link',`<p>Send this single-use link to ${esc(label)}. It expires in seven days and is shown only now. They choose their own password; it is never shown or stored here.</p><div class="field"><label for="setup-link">Setup link</label><input id="setup-link" readonly value="${esc(link)}"></div>`,async(_,done)=>{const copied=await copyText(link);if(copied){done();toast('Setup link copied.')}else{const input=share.querySelector('#setup-link');if(input){input.focus();input.select()}toast('Copy the selected setup link.')}});
  share.querySelector('[data-submit]').textContent='Copy link';
  share.querySelector('[data-cancel]').textContent='Close';
  setTimeout(()=>{const input=share.querySelector('#setup-link');if(input){input.focus();input.select()}},0);
}

async function reissueSetup(id){
  try{const result=await api('/api/admin/accounts/'+id+'/setup','POST',{});const account=S.admin?.accounts.find(a=>a.id===id);showSetupLink(result,account);adminHome()}
  catch(error){toast(error.message)}
}

async function adminHome(){
  S.view='admin';
  try{S.admin=await api('/api/admin/accounts')}catch(error){toast(error.message);return login(true)}
  const accounts=S.admin.accounts||[],now=Math.floor(Date.now()/1000);
  shell(`<div class="editor-head"><div class="titlebar"><span class="eyebrow">ADMINISTRATOR</span><h1>Account management</h1><p>Create creator and learner accounts, choose their workspace, and share a one-time setup link.</p></div><div class="actions"><button class="button" id="create-account">＋ Create account</button></div></div><section class="panel"><h2>Workspace accounts</h2><p>New accounts choose their own password from a single-use link. Trainly never stores or displays it.</p>${accounts.length?`<table class="results-table admin-table"><thead><tr><th>Account</th><th>Role</th><th>Workspace</th><th>Status</th><th></th></tr></thead><tbody>${accounts.map(a=>{const pending=!!a.setup_pending,expired=pending&&a.setup_expires&&a.setup_expires<now,status=pending?(expired?'Setup link expired':'Waiting for first sign-in'):'Active';return `<tr><td>${esc(a.name)}<br><span class="hint">${esc(a.email)}</span></td><td><span class="pill ${a.role==='creator'?'published':'draft'}">${esc(a.role)}</span></td><td>${esc(a.workspace_name)}</td><td>${status}</td><td>${pending?`<button class="button secondary small" data-setup-account="${a.id}" title="Generate a new setup link; the previous link stops working.">New setup link</button>`:''}</td></tr>`}).join('')}</tbody></table>`:'<div class="empty">No accounts yet. Create a creator or learner account to get started.</div>'}</section>`);
  document.querySelector('#create-account').onclick=createAccountModal;
  document.querySelectorAll('[data-setup-account]').forEach(b=>b.onclick=()=>reissueSetup(+b.dataset.setupAccount));
}

function createAccountModal(){
  const workspaces=S.admin?.workspaces||[];
  if(!workspaces.length)return toast('Create a workspace before adding accounts.');
  const options=workspaces.map(w=>`<option value="${esc(w.id)}">${esc(w.name)}</option>`).join('');
  const dialog=appModal('Create an account','<div class="field"><label for="account-name">Full name</label><input id="account-name" required maxlength="100" autocomplete="off"></div><div class="field"><label for="account-email">Work email</label><input id="account-email" type="email" required autocomplete="off"></div><div class="field"><label for="account-role">Access</label><select id="account-role"><option value="learner">Learner</option><option value="creator">Creator</option></select></div><div class="field"><label for="account-workspace">Workspace</label><select id="account-workspace">'+options+'</select></div><p class="hint">The account holder will choose their own password from a one-time setup link.</p>',async(d,close)=>{
    const name=d.querySelector('#account-name').value.trim();
    if(!name)throw Error('Enter the account holder’s name.');
    const result=await api('/api/admin/accounts','POST',{name,email:d.querySelector('#account-email').value.trim(),role:d.querySelector('#account-role').value,workspace_id:d.querySelector('#account-workspace').value});
    close();
    showSetupLink(result,result.account);
    adminHome();
  });
  dialog.querySelector('[data-submit]').textContent='Create account';
}

async function loadModules(){S.modules=await api('/api/modules')}
async function home(){S.view='home';if(S.user.role==='admin'){if(location.pathname!=='/admin')history.replaceState({},'','/admin');return adminHome()}try{await loadModules()}catch(e){return login()}if(S.user.role==='learner')return learnerHome();creatorHome()}
function learnerHome(){const cards=S.modules.filter(m=>m.status==='published');shell(`<section class="hero"><span class="eyebrow" style="color:var(--gold)">YOUR LEARNING SPACE</span><h1>Keep building your<br>confidence, ${esc(S.user.name.split(' ')[0])}.</h1><p>Pick up a new skill or continue where you left off. Every lesson is a step forward.</p></section><div class="row section-head"><div><h2>Your learning</h2><p>${cards.length} ${cards.length===1?'module':'modules'} ready when you are</p></div></div><section class="cards">${cards.map(m=>`<article class="card"><div class="card-art"><span class="badge">${m.completed?'COMPLETED':'READY TO LEARN'}</span></div><div class="card-body"><h3>${esc(m.title)}</h3><p>${esc(m.description||'A focused training module to help you learn by doing.')}</p><div class="card-meta"><span>${m.lessons.length} lessons · ${m.questions.length} check-ins</span><button class="button small" data-learn="${esc(m.id)}">${m.completed?'Review':'Start learning'} →</button></div></div></article>`).join('')||'<div class="empty">Your creator has not shared a module with you yet.</div>'}</section>`);app.querySelectorAll('[data-learn]').forEach(b=>b.onclick=()=>openLearner(b.dataset.learn))}
function creatorHome(){const draft=S.modules.filter(m=>m.status==='draft'),published=S.modules.filter(m=>m.status==='published');shell(`<section class="hero"><span class="eyebrow" style="color:var(--gold)">CREATOR WORKSPACE</span><h1>Make every video<br>a learning moment.</h1><p>Create focused training modules, guide your learners with timely check-ins, and see their progress as they go.</p><button class="button" id="create">＋ Create a module</button></section><div class="workspace" style="margin-top:34px"><aside class="side-nav"><h3>Workspace</h3><button class="side-link active" data-section="modules">▦ &nbsp;My modules</button><button class="side-link" data-section="results">◷ &nbsp;Learner results</button></aside><section class="main-content" id="main-content"></section></div>`);document.querySelector('#create').onclick=createModule;document.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.side-link').forEach(x=>x.classList.remove('active'));b.classList.add('active');b.dataset.section==='modules'?renderModules():renderAllResults()});renderModules()}
function renderModules(){const el=document.querySelector('#main-content');if(!el)return;el.innerHTML=`<div class="titlebar"><h1>My modules</h1><p>Build, publish, and manage your team's training.</p></div><div style="margin-top:22px" class="module-list">${S.modules.map(m=>`<article class="module-row"><div><span class="pill ${m.status}">${m.status}</span><h3 style="margin-top:7px">${esc(m.title)}</h3><p>${esc(m.description||'No description yet')} · ${m.lessons.length} lessons · ${m.questions.length} questions</p></div><div style="display:flex;gap:8px">${m.status==='published'?`<button class="button secondary small" data-assign="${m.id}">Assign</button>`:''}<button class="button secondary small" data-results="${m.id}">Results</button><button class="button small" data-edit="${m.id}">${m.status==='published'?'Edit module':'Continue editing'} →</button></div></article>`).join('')||'<div class="empty">Create your first module to get started.</div>'}</div>`;el.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>editModule(b.dataset.edit));el.querySelectorAll('[data-results]').forEach(b=>b.onclick=()=>results(b.dataset.results));el.querySelectorAll('[data-assign]').forEach(b=>b.onclick=()=>assignLearner(b.dataset.assign))}
function appModal(title,body,onSubmit){const previous=document.activeElement,dialog=document.createElement('dialog');dialog.className='app-modal';dialog.setAttribute('aria-labelledby','app-modal-heading');dialog.innerHTML=`<form method="dialog"><h2 id="app-modal-heading">${esc(title)}</h2>${body}<p class="modal-error" role="alert" hidden></p><div class="modal-actions"><button type="button" class="button secondary" data-cancel>Cancel</button><button class="button" data-submit>Continue</button></div></form>`;document.body.append(dialog);let closing=false;const close=()=>{if(closing)return;closing=true;if(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches){dialog.close();return}dialog.classList.add('closing');setTimeout(()=>dialog.close(),210)};dialog.querySelector('[data-cancel]').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close()});dialog.addEventListener('close',()=>{dialog.remove();previous?.focus()},{once:true});dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const button=dialog.querySelector('[data-submit]'),error=dialog.querySelector('.modal-error');button.disabled=true;error.hidden=true;try{await onSubmit(dialog,close)}catch(ex){error.textContent=ex.message;error.hidden=false}finally{button.disabled=false}};dialog.showModal();dialog.querySelector('input,button')?.focus();return dialog}
function addDeleteButtons(){document.querySelectorAll('#main-content [data-edit]').forEach(edit=>{const button=document.createElement('button');button.className='button secondary small';button.textContent='Delete';button.onclick=()=>{const id=edit.dataset.edit,module=S.modules.find(m=>m.id===id);const dialog=appModal('Delete module',`<p>Delete “${esc(module?.title||'this module')}” and all its learner progress? This cannot be undone.</p>`,async(_,close)=>{await api('/api/modules/'+encodeURIComponent(id),'DELETE');close();S.modules=S.modules.filter(m=>m.id!==id);renderModules();toast('Module deleted.')});dialog.querySelector('[data-submit]').textContent='Delete module'};edit.parentElement.append(button)})}
const renderModulesWithoutDelete=renderModules;
renderModules=function(){renderModulesWithoutDelete();addDeleteButtons()};
function assignLearner(id){appModal('Assign a learner','<div class="field"><label for="modal-email">Learner email</label><input id="modal-email" type="email" autocomplete="email" required></div>',async(d,close)=>{const email=d.querySelector('#modal-email').value.trim();try{await api('/api/modules/'+id+'/assign','POST',{email});close();toast('Learner assigned.')}catch(e){if(e.message!=='No learner account found for that email.')throw e;const invite=await api('/api/invitations','POST',{email,module_id:id});close();const link=location.origin+'/#invite='+encodeURIComponent(invite.token);const share=appModal('Share invitation',`<p>This invitation expires in 7 days.</p><div class="field"><label for="invite-link">Invitation link</label><input id="invite-link" readonly value="${esc(link)}"></div>`,async(_,done)=>{await navigator.clipboard.writeText(link);done();toast('Invitation link copied.')});share.querySelector('[data-submit]').textContent='Copy link';share.querySelector('[data-cancel]').textContent='Close'}})}
function createModule(){appModal('Create a module','<div class="field"><label for="modal-title">Module title</label><input id="modal-title" maxlength="120" required></div>',async(d,close)=>{const title=d.querySelector('#modal-title').value.trim();if(!title)throw Error('Enter a module title.');const m=await api('/api/modules','POST',{title,description:''});close();editModule(m.id)})}
const fld=(label,value,attr='')=>`<div class="field"><label>${label}</label><input ${attr} value="${esc(value)}"></div>`;
function isStarterLesson(x){return x.title==='Introduction'&&x.summary==='Add a short overview for learners.'&&+x.start===0&&+x.end===0}
function draftPanelHtml(){
  const d=S.draft;
  if(!S.config.ai_enabled) return '<h2>AI draft</h2><p>Automatic transcription and draft generation are not configured. You can still write lessons, questions, and transcript segments manually.</p>';
  if(!d) return `<h2>AI draft</h2><p>No generated draft yet. Process a video with ${esc(S.config.ai_provider||'the configured AI provider')} to create a transcript, lessons, and questions for review.</p>`;
  const transcript=(d.transcript||[]).map(x=>`<p><button type="button" class="text-btn" style="color:#94712b" data-draft-seek="${esc(x.start)}">${videoTime(x.start)}</button> ${esc(x.text)}</p>`).join('')||'<p class="hint">No transcript segments.</p>';
  const lessons=(d.lessons||[]).map(x=>`<p><strong>${esc(x.title)}</strong> — ${esc(x.summary)} <span class="hint">${videoTime(x.start)}–${videoTime(x.end)}</span></p>`).join('')||'<p class="hint">No generated lessons.</p>';
  const questions=(d.questions||[]).map((x,i)=>`<div class="lesson-item"><strong>${i+1}. ${esc(x.prompt)}</strong><p>${(x.options||[]).map((o,j)=>`${j===+x.answer?'&#10003; ':''}${esc(o)}`).join('<br>')}</p><small>At ${videoTime(x.at)} · ${esc(x.explanation)}</small></div>`).join('')||'<p class="hint">No generated questions.</p>';
  return `<h2>AI draft</h2><p><span class="pill published">${esc(d.state||'ready')}</span> ${esc(d.provider||'AI provider')} · ${(d.transcript||[]).length} transcript segments · ${(d.lessons||[]).length} lessons · ${(d.questions||[]).length} questions</p><p class="hint">Applying the draft fills empty sections. Creator-written content is kept unless you choose to replace it.</p><label class="hint" style="display:flex;gap:8px;align-items:center;margin:10px 0"><input id="draft-replace" type="checkbox"> Replace existing transcript, lessons, and questions</label><div class="row" style="gap:8px"><button type="button" class="button small" data-draft-apply>Apply generated draft</button><button type="button" class="button secondary small" data-draft-dismiss>Dismiss draft</button></div><details style="margin-top:14px"><summary>Review generated content</summary><div style="margin-top:10px"><h3>Transcript</h3>${transcript}<h3>Lessons</h3>${lessons}<h3>Questions</h3>${questions}</div></details>`;
}
function bindDraftPanel(){const panel=document.querySelector('#draft-panel');if(!panel)return;const apply=document.querySelector('[data-draft-apply]'),dismiss=document.querySelector('[data-draft-dismiss]');if(apply?.addEventListener)apply.addEventListener('click',applyDraft);if(dismiss?.addEventListener)dismiss.addEventListener('click',dismissDraft);document.querySelectorAll('[data-draft-seek]').forEach(b=>b.onclick=()=>{const v=document.querySelector('#draft-player');if(v){v.currentTime=Number(b.dataset.draftSeek);v.play().catch(()=>{})}})}
function renderDraftPanel(){const panel=document.querySelector('#draft-panel');if(!panel)return;panel.innerHTML=draftPanelHtml();bindDraftPanel()}
async function applyDraft(){const button=document.querySelector('[data-draft-apply]');if(button)button.disabled=true;try{const replace=!!document.querySelector('#draft-replace')?.checked;await saveEditor(false);const result=await api('/api/modules/'+encodeURIComponent(S.module.id)+'/draft/apply','POST',{sections:['transcript','lessons','questions','details'],replace});S.module=result.module;S.selectedQuestion=null;S.module.lessons=S.module.lessons.filter(x=>!isStarterLesson(x));S.module.transcript=S.module.transcript||[];S.module.pass_score=S.module.pass_score??70;S.draft=(await api('/api/modules/'+encodeURIComponent(S.module.id)+'/draft').catch(()=>({draft:null}))).draft;S.modules=await api('/api/modules');renderEditor();const skipped=result.skipped.length?` Kept existing ${result.skipped.join(', ')}.`:'';toast(`Draft applied.${skipped} Review generated content before publishing.`)}catch(e){toast(e.message);if(button)button.disabled=false}}
async function dismissDraft(){try{await api('/api/modules/'+encodeURIComponent(S.module.id)+'/draft','DELETE');S.draft=null;renderDraftPanel();toast('Generated draft dismissed.')}catch(e){toast(e.message)}}
async function editModule(id){try{const [module,draftResponse]=await Promise.all([api('/api/modules/'+id),api('/api/modules/'+id+'/draft').catch(()=>({draft:null}))]);S.module=module;S.draft=draftResponse.draft;S.module.lessons=S.module.lessons.filter(x=>!isStarterLesson(x));S.module.transcript=S.module.transcript||[];S.module.pass_score=S.module.pass_score??70;S.selectedQuestion=null;S.editorSeek=null;S.view='edit';renderEditor();const job=S.module.upload_job;if(job){if(job.state==='failed')setUploadState(id,'failed',0,`${job.error||'Video processing failed.'} Select Retry processing to try again.`,job.id);else if(job.state==='ready'&&job.error)setUploadState(id,'warning',100,`${job.error} Video playback is ready; select Retry processing to retry the AI steps.`,job.id);else if(job.state==='ready')setUploadState(id,'ready',100,job.message?`Video is ready. ${job.message}`:'Video is ready.');else{setUploadState(id,job.state==='processing'?'processing':'queued',100,uploadStageMessage(job.state,job.stage),job.id);pollUploadJob(id,job.id).catch(e=>toast(e.message))}}}catch(e){toast(e.message)}}
function uploadStageMessage(state,stage){if(state==='queued')return 'Upload complete. Waiting for video processing…';if(stage==='conversion')return 'Preparing browser playback…';if(stage==='audio')return 'Extracting audio…';if(stage==='transcription')return 'Transcribing speech…';if(stage==='generation')return 'Drafting lessons and questions…';return 'Inspecting video…'}
function checkTimeError(at,m){
  const duration=Number(m?.duration)||0,time=Number(at),lessons=m?.lessons||[];
  if(!Number.isFinite(time)||time<0)return 'Place the knowledge check within the video.';
  if(duration&&time>duration)return 'Place the knowledge check within the video.';
  if(lessons.length&&!(duration&&time===duration)&&!lessons.some(x=>time>=Number(x.start)&&time<=Number(x.end)))return 'Place the knowledge check inside a lesson range or at the end of the video.';
  return '';
}
function checkPlacementError(m){for(let i=0;i<(m.questions||[]).length;i++){const error=checkTimeError(m.questions[i].at,m);if(error)return `Knowledge check ${i+1}: ${error}`}return ''}
function currentPlayhead(){const v=document.querySelector('#draft-player');return v&&Number.isFinite(v.currentTime)?v.currentTime:0}
function editorDuration(){const v=document.querySelector('#draft-player');return Number.isFinite(v?.duration)&&v.duration>0?v.duration:Number(S.module?.duration)||0}
function updateEditorPlayhead(){
  const duration=editorDuration(),time=currentPlayhead(),playhead=document.querySelector('#editor-playhead'),label=document.querySelector('#editor-playhead-label');
  if(playhead&&playhead.style)playhead.style.left=(duration?Math.min(100,Math.max(0,time/duration*100)):0)+'%';
  if(label)label.textContent=videoTime(time);
}
function seekEditorTo(time){
  const v=document.querySelector('#draft-player'),duration=editorDuration();
  if(!v||!Number.isFinite(time))return;
  try{if(duration)v.currentTime=Math.min(duration,Math.max(0,time))}catch{}
  updateEditorPlayhead();
}
function restoreEditorPlayhead(){
  if(!Number.isFinite(S.editorSeek))return;
  const v=document.querySelector('#draft-player');
  if(!v)return;
  const time=S.editorSeek;
  const apply=()=>{try{v.currentTime=time}catch{}S.editorSeek=null;updateEditorPlayhead()};
  if(v.readyState===0&&v.addEventListener)v.addEventListener('loadedmetadata',apply,{once:true});
  else apply();
}
function knowledgeTimelineHtml(m){
  const duration=Number(m?.duration)||editorDuration()||0,questions=m?.questions||[],lessons=m?.lessons||[];
  const pct=t=>duration?Math.min(100,Math.max(0,Number(t)/duration*100)):0;
  const bands=lessons.map((x,i)=>`<span class="timeline-lesson" style="left:${pct(x.start)}%;width:${Math.max(0,pct(x.end)-pct(x.start))}%" title="Lesson ${i+1}: ${esc(x.title)}"><em>${i+1}</em></span>`).join('');
  const markers=questions.map((q,i)=>`<button type="button" class="timeline-marker${S.selectedQuestion===i?' selected':''}" data-check-marker="${i}" style="left:${pct(q.at)}%" aria-label="Knowledge check ${i+1} at ${videoTime(q.at)}" title="Check ${i+1} · ${videoTime(q.at)}">${i+1}</button>`).join('');
  return `<div class="timeline-meta"><span>Video timeline</span><span id="editor-playhead-label">${videoTime(currentPlayhead())}</span></div><div class="check-timeline-track" data-editor-track role="group" aria-label="Video timeline with lesson ranges and knowledge check markers">${bands}${markers}<i class="timeline-playhead" id="editor-playhead" style="left:${pct(currentPlayhead())}%"></i></div><div class="timeline-legend"><span><i class="legend-band"></i>Lessons</span><span><i class="legend-marker"></i>Knowledge checks</span></div><div class="timeline-actions"><button type="button" class="button small" id="addquestion">＋ Add check at playhead</button><button type="button" class="button secondary small" id="move-selected-check" ${S.selectedQuestion==null?'disabled':''}>Move selected check here</button></div><p class="hint">Play or drag across the timeline. Select a marker, scrub to a new point, then choose <strong>Move selected check here</strong>.</p>`;
}
function selectQuestion(i,seek=true){
  if(!S.module?.questions?.[i])return;
  S.selectedQuestion=i;
  document.querySelectorAll('[data-check-marker]').forEach((b,j)=>b.classList.toggle('selected',j===i));
  document.querySelectorAll('[data-question-card]').forEach((card,j)=>card.classList.toggle('selected',j===i));
  const move=document.querySelector('#move-selected-check');if(move)move.disabled=false;
  if(seek){const v=document.querySelector('#draft-player');if(v&&v.pause)v.pause();seekEditorTo(S.module.questions[i].at)}
  const card=document.querySelector(`[data-question-card="${i}"]`);
  if(card?.scrollIntoView)card.scrollIntoView({behavior:'smooth',block:'center'});
}
function addKnowledgeCheck(){
  const m=collect(),at=currentPlayhead(),error=checkTimeError(at,m);
  if(error)return toast(error);
  S.editorSeek=at;
  m.questions.push({id:'',prompt:'',options:['',''],answer:0,explanation:'',at});
  S.selectedQuestion=m.questions.length-1;
  renderEditor();
  const card=document.querySelector(`[data-question-card="${S.selectedQuestion}"]`);
  if(card?.scrollIntoView)card.scrollIntoView({behavior:'smooth',block:'center'});
  const prompt=card?.querySelector?.('textarea');if(prompt?.focus)prompt.focus();
  toast(`Knowledge check added at ${videoTime(at)}.`);
}
function moveCheckToPlayhead(i){
  if(i==null||!S.module?.questions?.[i])return toast('Select a knowledge check marker first.');
  const m=collect(),at=currentPlayhead(),error=checkTimeError(at,m);
  if(error)return toast(error);
  S.editorSeek=at;
  m.questions[i].at=at;
  S.selectedQuestion=i;
  renderEditor();
  toast(`Knowledge check ${i+1} moved to ${videoTime(at)}.`);
}
function renderKnowledgeTimeline(){
  const panel=document.querySelector('#check-timeline-panel');
  if(!panel)return;
  panel.innerHTML=knowledgeTimelineHtml(S.module);
  const add=document.querySelector('#addquestion');if(add)add.onclick=addKnowledgeCheck;
  const move=document.querySelector('#move-selected-check');if(move)move.onclick=()=>moveCheckToPlayhead(S.selectedQuestion);
  const track=document.querySelector('[data-editor-track]');
  if(track&&track.addEventListener){
    const seek=e=>{const rect=track.getBoundingClientRect?.(),duration=editorDuration();if(!rect||!rect.width||!duration)return;seekEditorTo(Math.min(1,Math.max(0,(e.clientX-rect.left)/rect.width))*duration)};
    track.addEventListener('pointerdown',e=>{if(e.target.closest?.('[data-check-marker]'))return;seek(e);track.setPointerCapture?.(e.pointerId)});
    track.addEventListener('pointermove',e=>{if(e.buttons)seek(e)});
    track.addEventListener('click',e=>{if(e.target.closest?.('[data-check-marker]'))return;seek(e)});
  }
  document.querySelectorAll('[data-check-marker]').forEach(b=>b.onclick=e=>{e.stopPropagation();selectQuestion(+b.dataset.checkMarker)});
  document.querySelectorAll('[data-play-check]').forEach(b=>b.onclick=()=>{const q=S.module.questions[+b.dataset.playCheck];if(!q)return;seekEditorTo(q.at);const v=document.querySelector('#draft-player'),playing=v?.play?.();if(playing&&playing.catch)playing.catch(()=>{})});
  document.querySelectorAll('[data-move-check]').forEach(b=>b.onclick=()=>moveCheckToPlayhead(+b.dataset.moveCheck));
  const v=document.querySelector('#draft-player');
  if(v&&v.addEventListener){
    v.addEventListener('timeupdate',updateEditorPlayhead);
    v.addEventListener('seeked',updateEditorPlayhead);
    v.addEventListener('play',updateEditorPlayhead);
    v.addEventListener('loadedmetadata',()=>{restoreEditorPlayhead();updateEditorPlayhead()});
  }
  restoreEditorPlayhead();
}
function previewTimelineHtml(m){
  const duration=Number(m?.duration)||editorDuration()||0,pct=t=>duration?Math.min(100,Math.max(0,Number(t)/duration*100)):0;
  const markers=(m?.questions||[]).map((q,i)=>`<button type="button" class="timeline-marker" data-preview-marker="${i}" style="left:${pct(q.at)}%" aria-label="Preview knowledge check ${i+1} at ${videoTime(q.at)}" title="Check ${i+1} · ${videoTime(q.at)}">${i+1}</button>`).join('');
  return markers?`<div class="timeline-meta"><span>Knowledge checks pause playback here</span><span id="preview-playhead-label">0:00</span></div><div class="check-timeline-track" data-preview-track role="group" aria-label="Knowledge check markers">${markers}<i class="timeline-playhead" id="preview-playhead" style="left:0%"></i></div>`:'';
}
function renderPreviewTimeline(show){
  const panel=document.querySelector('#preview-timeline-panel');
  if(!panel)return;
  panel.innerHTML=previewTimelineHtml(S.module);
  const v=document.querySelector('#draft-player');
  const update=()=>{const time=v&&Number.isFinite(v.currentTime)?v.currentTime:0,duration=editorDuration(),bar=document.querySelector('#preview-playhead'),label=document.querySelector('#preview-playhead-label');if(bar&&bar.style)bar.style.left=(duration?Math.min(100,time/duration*100):0)+'%';if(label)label.textContent=videoTime(time)};
  document.querySelectorAll('[data-preview-marker]').forEach(b=>b.onclick=()=>{const q=S.module.questions[+b.dataset.previewMarker];if(!q)return;seekEditorTo(q.at);show(q.at);const playing=v?.play?.();if(playing&&playing.catch)playing.catch(()=>{})});
  if(v&&v.addEventListener){v.addEventListener('timeupdate',update);v.addEventListener('seeked',update);v.addEventListener('play',update);v.addEventListener('loadedmetadata',update)}
  update();
}

function renderEditor(){S.view='edit';let m=S.module;shell(`<div class="editor-head"><div class="titlebar"><span class="eyebrow">${m.status==='published'?'PUBLISHED MODULE':'DRAFT MODULE'}</span><h1>Edit your module</h1><p>Everything stays a draft until you're ready to publish.</p></div><div class="actions"><button class="button secondary small" id="back">← Dashboard</button> <button class="button secondary small" id="preview">Preview learner view</button> <button class="button small" id="save">Save changes</button></div></div><div class="editor-layout"><div><section class="panel"><h2>Module details</h2><p>Give your learners a clear idea of what they'll learn.</p><div class="field"><label for="mtitle">Module title</label><input id="mtitle" value="${esc(m.title)}" maxlength="120"></div><div class="field"><label for="mdesc">Description</label><textarea id="mdesc" maxlength="500">${esc(m.description)}</textarea></div><div class="field"><label for="mpass">Passing score (0–100)</label><input id="mpass" type="number" min="0" max="100" step="1" value="${esc(m.pass_score??70)}"><span class="hint">Learners must score at least this percentage to pass. Completion still requires every lesson and question.</span></div></section><section class="panel"><h2>Lessons</h2><p>Break the training into easy to follow sections with time ranges.</p><div id="lessons">${m.lessons.map((x,i)=>lessonHtml(x,i)).join('')}</div><button class="button secondary small" id="addlesson">＋ Add lesson</button></section><section class="panel"><h2>Transcript</h2><p>Add reviewed transcript segments with timestamps. Selecting a segment seeks the video to that point.</p><div id="transcript">${(m.transcript||[]).map((x,i)=>`<div class="lesson-item"><div class="row"><strong>Segment ${i+1}</strong><button type="button" class="icon-btn" data-remove-transcript="${i}">Remove</button></div><div class="item-grid"><div class="field"><label>Start (sec)</label><input type="number" min="0" step="0.1" data-t="${i}" data-k="start" value="${esc(x.start)}"></div><div class="field"><label>End (sec)</label><input type="number" min="0" step="0.1" data-t="${i}" data-k="end" value="${esc(x.end)}"></div></div><div class="field"><label>Transcript text <span class="hint">${x.origin==='generated'?(x.edited?'Generated &middot; edited':'Generated &middot; review needed'):'Manual'}</span></label><textarea data-t="${i}" data-k="text">${esc(x.text)}</textarea><button type="button" class="text-btn seek-transcript" data-seek-transcript="${i}" style="color:#94712b">? Play from this segment</button></div></div>`).join('')}</div><button class="button secondary small" id="addtranscript">? Add transcript segment</button></section><section class="panel" id="draft-panel">${draftPanelHtml()}</section><section class="panel"><h2>Knowledge checks</h2><p>Select a marker on the video timeline to edit a check, or add one at the current playhead.</p><div id="questions">${m.questions.map((x,i)=>questionHtml(x,i)).join('')}</div><button class="button secondary small" id="savequestions" type="button">Save knowledge checks</button></section></div><aside><section class="panel"><h2>Training video</h2><p>Upload the source video for your module.</p><div class="upload-zone"><p id="upload-note">${m.video?'A video is saved for this module. Upload a replacement if needed.':`MP4, MOV, or WebM · Up to ${S.config.max_video_bytes/(1024**3)} GiB · ${Math.ceil(S.config.max_video_seconds/60)} min`}</p>${m.video?`<video id="draft-player" controls playsinline style="width:100%;border-radius:8px;margin:10px 0" src="/media/${encodeURIComponent(m.id)}">${captionTrack(m,m.version)}</video>`:''}<div id="check-timeline-panel" class="check-timeline"></div><input id="video-file" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" style="width:100%;font-size:11px"><button id="upload" class="button secondary small" style="margin-top:12px">Upload video</button><progress id="upload-progress" max="100" value="0" hidden></progress><p id="upload-status" role="status" aria-live="polite"></p></div><div class="warning">${S.config.ai_enabled?`Automatic transcription and lesson drafting use ${esc(S.config.ai_provider||'the configured AI provider')}. Uploaded video and transcript content may be sent to that provider for processing.`:'Automatic transcription is not configured. You can build and publish this module manually, or configure a provider and retry processing.'}</div></section><section class="panel"><h2>Ready to publish?</h2><p>Your module needs a title, a playable video, one valid lesson, and one valid quiz question.</p><button class="button" id="publish" style="width:100%">Publish module →</button><p style="margin:12px 0 0">Publishing makes this version available to learners in this workspace.</p></section></aside></div>`);document.querySelector('#back').onclick=home;document.querySelector('#save').onclick=saveEditor;document.querySelector('#preview').onclick=async()=>{try{await saveEditor(false);renderDraftPreview()}catch(e){toast(e.message)}};document.querySelector('#addtranscript').onclick=()=>{collect();m.transcript.push({id:'',start:0,end:1,text:'',origin:'manual',edited:true});renderEditor()};document.querySelectorAll('[data-remove-transcript]').forEach(b=>b.onclick=()=>{collect();m.transcript.splice(+b.dataset.removeTranscript,1);renderEditor()});document.querySelectorAll('[data-seek-transcript]').forEach(b=>b.onclick=()=>{const x=m.transcript[+b.dataset.seekTranscript];const v=document.querySelector('#draft-player');if(v){v.currentTime=x.start;v.play().catch(()=>{})}});document.querySelector('#addlesson').onclick=()=>{collect();m.lessons.push({id:'',title:'',summary:'',start:0,end:0});renderEditor()};document.querySelectorAll('[data-remove-lesson]').forEach(b=>b.onclick=()=>{collect();m.lessons.splice(+b.dataset.removeLesson,1);renderEditor()});document.querySelectorAll('[data-move-lesson]').forEach(b=>b.onclick=()=>{collect();const i=+b.dataset.moveLesson,j=i+Number(b.dataset.direction);[m.lessons[i],m.lessons[j]]=[m.lessons[j],m.lessons[i]];renderEditor()});document.querySelectorAll('[data-remove-question]').forEach(b=>b.onclick=()=>{collect();S.editorSeek=currentPlayhead();const i=+b.dataset.removeQuestion;m.questions.splice(i,1);if(S.selectedQuestion===i)S.selectedQuestion=null;else if(S.selectedQuestion>i)S.selectedQuestion--;renderEditor()});document.querySelectorAll('[data-add-option]').forEach(b=>b.onclick=()=>{collect();S.editorSeek=currentPlayhead();const i=+b.dataset.addOption,j=m.questions[i].options.length;m.questions[i].options.push('');renderEditor();document.querySelector(`[data-q="${i}"][data-option="${j}"]`)?.focus()});document.querySelectorAll('[data-remove-option]').forEach(b=>b.onclick=()=>{collect();S.editorSeek=currentPlayhead();const i=+b.dataset.removeOption,j=+b.dataset.option,q=m.questions[i];if(q.options.length<=2)return toast('A knowledge check needs at least two choices.');q.options.splice(j,1);if(q.answer===j)q.answer=0;else if(q.answer>j)q.answer--;renderEditor()});document.querySelectorAll('[data-move-question]').forEach(b=>b.onclick=()=>{collect();S.editorSeek=currentPlayhead();const i=+b.dataset.moveQuestion,j=i+Number(b.dataset.direction);[m.questions[i],m.questions[j]]=[m.questions[j],m.questions[i]];if(S.selectedQuestion===i)S.selectedQuestion=j;else if(S.selectedQuestion===j)S.selectedQuestion=i;renderEditor()});document.querySelector('#savequestions').onclick=saveQuestions;document.querySelector('#upload').onclick=uploadVideo;document.querySelector('#publish').onclick=publishModule;bindDraftPanel();renderKnowledgeTimeline();renderUploadState()}
function renderDraftPreview(){S.view='preview';const m=S.module;shell(`<div class="editor-head"><div class="titlebar"><span class="eyebrow">PREVIEW &middot; NOT PUBLISHED</span><h1>${esc(m.title)}</h1><p>${esc(m.description)}</p></div><button class="button secondary small" id="preview-back">Back to editing</button></div><div class="student-layout"><section><div class="video-box">${m.video?`<video id="draft-player" controls playsinline src="/media/${encodeURIComponent(m.id)}">${captionTrack(m,m.version)}</video>`:'<div class="video-placeholder">Upload and process a video to preview playback.</div>'}</div><div id="preview-timeline-panel" class="preview-timeline"></div><div id="draft-question" aria-live="polite"></div><section class="panel" style="margin-top:17px"><h2>Lessons</h2>${m.lessons.map(x=>`<p><strong>${esc(x.title)}</strong> &mdash; ${esc(x.summary)} <button class="text-btn" style="color:#94712b" data-preview-seek="${x.start}">Preview</button></p>`).join('')||'<p>No lessons yet.</p>'}</section></section><aside><section class="panel"><h2>Knowledge checks</h2>${m.questions.map((q,i)=>`<div class="lesson-item"><strong>${i+1}. ${esc(q.prompt)}</strong><p>${q.options.map((o,j)=>`<span>${j===+q.answer?'&#10003; ':''}${esc(o)}</span>`).join('<br>')}</p><small>At ${q.at}s &middot; ${esc(q.explanation)}</small><p><button class="button secondary small" data-preview-question="${q.at}">Preview this question</button></p></div>`).join('')||'<p>No questions yet.</p>'}</section><section class="panel"><h2>Transcript</h2>${(m.transcript||[]).map(x=>`<p><button class="text-btn" style="color:#94712b" data-preview-seek="${x.start}">${x.start}s</button> ${esc(x.text)}</p>`).join('')||'<p>No transcript segments.</p>'}</section></aside></div>`);document.querySelector('#preview-back').onclick=renderEditor;document.querySelectorAll('[data-preview-seek]').forEach(b=>b.onclick=()=>{const v=document.querySelector('#draft-player');if(v){v.currentTime=Number(b.dataset.previewSeek);v.play().catch(()=>{})}});const show=at=>{const q=m.questions.filter(x=>Math.abs(x.at-at)<1).sort((a,b)=>a.at-b.at)[0];if(!q)return;const el=document.querySelector('#draft-question');el.innerHTML=`<section class="quiz-box"><span class="eyebrow">PREVIEW QUESTION</span><h2>${esc(q.prompt)}</h2>${q.options.map((o,i)=>`<p>${i===+q.answer?'&#10003; ':''}${esc(o)}</p>`).join('')}<p>${esc(q.explanation)}</p></section>`};renderPreviewTimeline(show);document.querySelectorAll('[data-preview-question]').forEach(b=>b.onclick=()=>{const v=document.querySelector('#draft-player');const at=Number(b.dataset.previewQuestion);if(v){v.currentTime=at;show(at);v.play().catch(()=>{})}else show(at)});document.querySelector('#draft-player')?.addEventListener('timeupdate',e=>{const q=m.questions.find(x=>Math.abs(x.at-e.currentTarget.currentTime)<0.5);if(q){e.currentTarget.pause();show(q.at)}})}
function lessonHtml(x,i){return `<div class="lesson-item"><div class="row"><strong style="font-size:13px">Lesson ${i+1}</strong>${x.origin==='generated'?'<span class="hint">Generated · review</span>':''}<span><button class="icon-btn" style="color:var(--slate)" data-move-lesson="${i}" data-direction="-1" ${i===0?"disabled":""} aria-label="Move lesson up">&#8593;</button><button class="icon-btn" style="color:var(--slate)" data-move-lesson="${i}" data-direction="1" ${i===S.module.lessons.length-1?"disabled":""} aria-label="Move lesson down">&#8595;</button><button class="icon-btn" data-remove-lesson="${i}">Remove</button></span></div><div class="field"><label>Lesson title</label><input data-l="${i}" data-k="title" value="${esc(x.title)}"></div><div class="field"><label>Short summary</label><textarea data-l="${i}" data-k="summary">${esc(x.summary)}</textarea></div><div class="item-grid">${[['Start (sec)','start'],['End (sec)','end']].map(([l,k])=>`<div class="field"><label>${l}</label><input type="number" min="0" step="1" data-l="${i}" data-k="${k}" value="${esc(x[k])}"></div>`).join('')}</div></div>`}
function questionHtml(x,i){const selected=S.selectedQuestion===i?' selected':'';return `<div class="question-item${selected}" data-question-card="${i}"><div class="row"><strong style="font-size:13px">Question ${i+1}</strong>${x.origin==='generated'?'<span class="hint">Generated · review</span>':''}<span><button class="icon-btn" style="color:var(--slate)" data-move-question="${i}" data-direction="-1" ${i===0?"disabled":""} aria-label="Move question up">&#8593;</button><button class="icon-btn" style="color:var(--slate)" data-move-question="${i}" data-direction="1" ${i===S.module.questions.length-1?"disabled":""} aria-label="Move question down">&#8595;</button><button class="icon-btn" data-remove-question="${i}">Remove</button></span></div><div class="check-placement"><span>Placed at <strong class="check-time">${videoTime(x.at)}</strong></span><button type="button" class="text-btn" style="color:#94712b" data-play-check="${i}">Play from check</button><button type="button" class="text-btn" style="color:#94712b" data-move-check="${i}">Move to playhead</button></div><div class="field"><label>Question prompt</label><textarea data-q="${i}" data-k="prompt">${esc(x.prompt)}</textarea></div><div class="field"><label>Answer options</label>${x.options.map((o,j)=>`<div class="answer-option-row"><input type="radio" name="answer${i}" ${j===+x.answer?'checked':''} aria-label="Correct answer" data-answer="${i}" value="${j}"><input data-q="${i}" data-option="${j}" value="${esc(o)}" placeholder="Option ${j+1}" aria-label="Choice ${j+1}"><button type="button" class="icon-btn" data-remove-option="${i}" data-option="${j}" aria-label="Remove choice ${j+1}" ${x.options.length<=2?'disabled':''}>Remove</button></div>`).join('')}<button class="text-btn" style="color:#94712b;font-size:12px" data-add-option="${i}">＋ Add answer option</button></div><div class="field"><label>Correct answer</label><span class="hint" style="padding:10px 0;display:block">Choose the radio button beside the correct option.</span></div><div class="field"><label>Explanation after answering</label><textarea data-q="${i}" data-k="explanation">${esc(x.explanation)}</textarea></div></div>`}
function collect(){const m=S.module;m.title=document.querySelector('#mtitle').value.trim();m.description=document.querySelector('#mdesc').value;const pass=document.querySelector('#mpass');if(pass)m.pass_score=pass.value===''?NaN:Number(pass.value);document.querySelectorAll('[data-l]').forEach(e=>m.lessons[+e.dataset.l][e.dataset.k]=e.dataset.k==='start'||e.dataset.k==='end'?Number(e.value):e.value);document.querySelectorAll('[data-q][data-k]').forEach(e=>m.questions[+e.dataset.q][e.dataset.k]=e.dataset.k==='at'?Number(e.value):e.value);document.querySelectorAll('[data-q][data-option]').forEach(e=>m.questions[+e.dataset.q].options[+e.dataset.option]=e.value);document.querySelectorAll('[data-answer]:checked').forEach(e=>m.questions[+e.dataset.answer].answer=Number(e.value));document.querySelectorAll('[data-t][data-k]').forEach(e=>m.transcript[+e.dataset.t][e.dataset.k]=e.dataset.k==='start'||e.dataset.k==='end'?Number(e.value):e.value);return m}
async function saveQuestions(){const m=collect(),placement=checkPlacementError(m);if(placement)return toast(placement);try{await api('/api/modules/'+m.id+'/questions','PUT',{items:m.questions});const saved=await api('/api/modules/'+m.id+'/transcript','PUT',{items:m.transcript});S.module.questions=saved.questions;S.module.transcript=saved.transcript;S.editorSeek=currentPlayhead();renderEditor();toast('Knowledge checks saved.')}catch(e){toast(e.message)}}
async function saveEditor(notify=true){const m=collect();if(!Number.isInteger(m.pass_score)||m.pass_score<0||m.pass_score>100){const message='Enter a passing score from 0 to 100.';if(notify)return toast(message);throw Error(message)}const placement=checkPlacementError(m);if(placement){if(notify)return toast(placement);throw Error(placement)}try{await api('/api/modules/'+m.id,'PUT',{title:m.title,description:m.description,pass_score:m.pass_score});await api('/api/modules/'+m.id+'/lessons','PUT',{items:m.lessons});await api('/api/modules/'+m.id+'/questions','PUT',{items:m.questions});const saved=await api('/api/modules/'+m.id+'/transcript','PUT',{items:m.transcript});S.module.questions=saved.questions;S.module.transcript=saved.transcript;S.module.pass_score=saved.pass_score;S.modules=await api('/api/modules');S.editorSeek=currentPlayhead();renderEditor();if(notify)toast('Your changes are saved.')}catch(e){if(notify)toast(e.message);else throw e}}
function renderUploadState(){
  const state=S.uploadState&&S.uploadState.moduleId===S.module?.id?S.uploadState:null;
  const button=document.querySelector('#upload'),progress=document.querySelector('#upload-progress'),status=document.querySelector('#upload-status');
  if(!button||!progress||!status)return;
  const busy=state?.stage==='uploading'||state?.stage==='processing'||state?.stage==='queued';
  button.disabled=!!busy;
  button.textContent=busy?(state.stage==='uploading'?'Uploading…':state.stage==='queued'?'Queued…':'Video processing…'):(state?.stage==='failed'||state?.stage==='warning')&&state.jobId?'Retry processing':'Upload video';
  progress.hidden=state?.stage!=='uploading';
  progress.value=state?.percent||0;
  status.textContent=state?.message||'';
  status.className=state?.stage==='failed'||state?.stage==='warning'?'upload-error':'';
}
function setUploadState(moduleId,stage,percent,message,jobId=null){S.uploadState={moduleId,stage,percent,message,jobId};renderUploadState()}
function previewSelectedVideo(){
  const input=document.querySelector('#video-file'),file=input?.files?.[0];
  if(S.localPreview?.url)URL.revokeObjectURL(S.localPreview.url);
  S.localPreview=file?{moduleId:S.module.id,file,url:URL.createObjectURL(file)}:null;
  showLocalPreview();
}
function showLocalPreview(){
  if(S.localPreview?.moduleId!==S.module?.id)return;
  const zone=document.querySelector('.upload-zone'),old=zone?.querySelector('#draft-player');
  if(!zone)return;
  const video=old||document.createElement('video');
  video.id='draft-player';video.controls=true;video.playsInline=true;
  video.style.cssText='width:100%;border-radius:8px;margin:10px 0';
  video.src=S.localPreview.url;
  video.onloadedmetadata=()=>renderKnowledgeTimeline();
  if(!old)zone.insertBefore(video,zone.querySelector('#check-timeline-panel'));
  const note=document.querySelector('#upload-note');if(note)note.textContent='Local preview. Upload the video to save it to this module.';
  renderKnowledgeTimeline();
}
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function refreshDraft(moduleId){if(S.module?.id!==moduleId)return;try{const result=await api('/api/modules/'+encodeURIComponent(moduleId)+'/draft');S.draft=result.draft;renderDraftPanel()}catch{}}
async function pollUploadJob(moduleId,jobId){
  while(true){
    let job;try{job=await api(`/api/modules/${encodeURIComponent(moduleId)}/uploads/${encodeURIComponent(jobId)}`)}catch{setUploadState(moduleId,'queued',100,'Connection interrupted. Reconnecting to the processing job…',jobId);await delay(2500);continue}
    if(job.state==='ready'){
      if(S.module.id===moduleId){
        if(S.localPreview?.moduleId===moduleId){URL.revokeObjectURL(S.localPreview.url);S.localPreview=null}
        S.module.video=true;S.module.duration=job.duration;
        if(S.view==='edit'){
          S.editorSeek=currentPlayhead();
          try{collect()}catch{}
          renderEditor();
        }
        const note=document.querySelector('#upload-note');if(note)note.textContent=`Video ready (${Math.floor(job.duration/60)} min).`;
      }
      await refreshDraft(moduleId);
      if(job.error){setUploadState(moduleId,'warning',100,`${job.error} Video playback is ready; select Retry processing to retry the AI steps.`,jobId);return job}
      setUploadState(moduleId,'ready',100,job.message?`Video is ready. ${job.message}`:'Video is ready.');return job;
    }
    if(job.state==='failed'){
      setUploadState(moduleId,'failed',0,`${job.error||'Video processing failed.'} Select Retry processing to try again.`,jobId);
      throw Error(job.error||'Video processing failed.');
    }
    if(job.state==='superseded')throw Error('A newer upload replaced this one.');
    const stage=job.state==='processing'?'processing':'queued';
    setUploadState(moduleId,stage,100,uploadStageMessage(stage,job.stage),jobId);
    await delay(1200);
  }
}
function sendVideo(moduleId,file){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest(),form=new FormData();form.append('file',file);
    xhr.open('POST','/api/modules/'+encodeURIComponent(moduleId)+'/upload');
    xhr.setRequestHeader('X-CSRF-Token',S.csrf);
    xhr.upload.onprogress=e=>{if(e.lengthComputable){const percent=Math.min(100,Math.round(e.loaded/e.total*100));setUploadState(moduleId,percent===100?'processing':'uploading',percent,percent===100?'Upload complete. Checking video…':`Uploading video: ${percent}%`)}};
    xhr.upload.onload=()=>setUploadState(moduleId,'processing',100,'Upload complete. Checking video…');
    xhr.onload=()=>{let result={};try{result=JSON.parse(xhr.responseText)}catch{}if(xhr.status>=200&&xhr.status<300)resolve(result);else reject(Error(result.error||'Video upload failed. Try again.'))};
    xhr.onerror=()=>reject(Error('Upload interrupted. Choose Upload video to retry.'));
    xhr.onabort=()=>reject(Error('Upload interrupted. Choose Upload video to retry.'));
    xhr.send(form);
  });
}
async function uploadVideo(){
  const input=document.querySelector('#video-file'),moduleId=S.module.id,file=input?.files[0]||((S.localPreview?.moduleId===moduleId)&&S.localPreview.file);
  if(!file&&S.uploadState?.moduleId===moduleId&&(S.uploadState.stage==='failed'||S.uploadState.stage==='warning')&&S.uploadState.jobId){
    const jobId=S.uploadState.jobId;setUploadState(moduleId,'queued',0,'Retry queued.',jobId);
    try{await api(`/api/modules/${encodeURIComponent(moduleId)}/uploads/${encodeURIComponent(jobId)}/retry`,'POST',{});const job=await pollUploadJob(moduleId,jobId);toast(job.error?'Video is ready. Retry the AI steps when you are ready.':'Video is ready.')}catch(error){if(S.uploadState?.stage!=='failed'&&S.uploadState?.stage!=='warning')setUploadState(moduleId,'failed',0,error.message+' Select Retry processing to try again.',jobId);toast(error.message)}
    return;
  }
  if(!file)return toast('Choose a video first.');
  if(file.size>S.config.max_video_bytes)return toast('This video exceeds the configured upload limit.');
  setUploadState(moduleId,'uploading',0,'Starting upload…');
  try{
    const result=await sendVideo(moduleId,file);
    setUploadState(moduleId,'queued',100,result.message,result.job_id);
    await pollUploadJob(moduleId,result.job_id).then(job=>toast(job?.error?'Video is ready. Retry the AI steps when you are ready.':'Video is ready.'));
  }catch(error){if(S.uploadState?.stage!=='failed')setUploadState(moduleId,'failed',0,error.message+' Your module edits are still here.');toast(error.message)}
}

async function publishModule(){try{await saveEditor(false);await api('/api/modules/'+S.module.id+'/publish','PATCH',{});toast('Your module is published.');home()}catch(e){toast(e.message)}}
async function results(id){const m=S.modules.find(x=>x.id===id);try{const rows=await api('/api/modules/'+id+'/results');S.view='results';shell(`<div class="editor-head"><div class="titlebar"><span class="eyebrow">LEARNER PROGRESS</span><h1>${esc(m?.title||'Module results')}</h1><p>See who has started and completed this training. Passing mark: ${esc(m?.pass_score??70)}%.</p></div><button class="button secondary small" id="back">← Dashboard</button></div>${rows.length?`<table class="results-table"><thead><tr><th>Learner</th><th>Status</th><th>Latest score</th><th>Result</th><th>Attempts</th><th>Started</th><th>Completed</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}<br><span class="hint">${esc(r.email)}</span></td><td>${r.status==='completed'?'<span class="success">Completed</span>':r.status==='not_started'?'Not started':'In progress'}</td><td>${r.score===null?'&mdash;':r.score+'%'}</td><td>${r.outcome==='passed'?'<span class="success">Passed</span>':r.outcome==='not_passed'?'Not passed':'&mdash;'}</td><td>${r.attempt_count}</td><td>${r.started?new Date(r.started*1000).toLocaleDateString():'&mdash;'}</td><td>${r.completed_at?new Date(r.completed_at*1000).toLocaleDateString():'—'}</td></tr>`).join('')}</tbody></table>`:'<div class="empty" style="margin-top:22px">No learners assigned yet. Use Assign to give a learner access to this module.</div>'}`);document.querySelector('#back').onclick=home}catch(e){toast(e.message)}}
async function renderAllResults(){const mods=S.modules.filter(m=>m.status==='published');const all=await Promise.all(mods.map(async m=>({m,rows:await api('/api/modules/'+m.id+'/results')})));const el=document.querySelector('#main-content');el.innerHTML=`<div class="titlebar"><h1>Learner results</h1><p>Progress across your published modules.</p></div>${all.flatMap(({m,rows})=>rows.map(r=>({m,r}))).length?`<table class="results-table" style="margin-top:20px"><thead><tr><th>Learner</th><th>Module</th><th>Status</th><th>Latest score</th><th>Result</th><th>Attempts</th><th>Completed</th></tr></thead><tbody>${all.flatMap(({m,rows})=>rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(m.title)}</td><td>${r.status==='completed'?'Completed':r.status==='not_started'?'Not started':'In progress'}</td><td>${r.score===null?'&mdash;':r.score+'%'}</td><td>${r.outcome==='passed'?'<span class="success">Passed</span>':r.outcome==='not_passed'?'Not passed':'&mdash;'}</td><td>${r.attempt_count}</td><td>${r.completed_at?new Date(r.completed_at*1000).toLocaleDateString():'—'}</td></tr>`)).join('')}</tbody></table>`:'<div class="empty" style="margin-top:20px">Results appear here when learners begin a module.</div>'}`}
async function openLearner(id){try{S.module=await api('/api/modules/'+id);S.view='learn';S.attempt=await api('/api/attempts','POST',{module_id:id});S.progress={position:S.attempt.position||0,completed:new Set(S.attempt.completed_lessons||[]),lastSaved:0};S.asked=new Set(S.attempt.answered_questions||[]);S.activeQuestion=null;renderLearner()}catch(e){toast(e.message)}}
function videoTime(seconds){const total=Math.floor(Number(seconds)||0);return `${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`}
function captionTrack(m,version){if(!m?.transcript?.length)return '';return `<track kind="captions" srclang="en" label="English" default src="/media/${encodeURIComponent(m.id)}/captions.vtt${version?`?version=${encodeURIComponent(version)}`:''}">`}
function renderLearner(){const m=S.module;const idx=Math.max(0,m.lessons.findIndex(x=>S.progress.position>=x.start&&S.progress.position<x.end));const initial=m.lessons[idx];shell(`<div class="editor-head"><div class="titlebar"><span class="eyebrow">YOUR TRAINING</span><h1>${esc(m.title)}</h1><p>${esc(m.description)}</p><p class="hint">Passing score: ${esc(m.pass_score??70)}%${S.attempt?.passed?' · Passed':''}</p></div><div class="actions"><button class="button secondary small" id="reset-progress">Reset progress</button> <button class="button secondary small" id="back">&larr; My learning</button></div></div><div class="student-layout"><section><div class="video-box" id="video-box">${m.video?`<video id="player" controls playsinline src="/media/${encodeURIComponent(m.id)}?version=${encodeURIComponent(m.version||0)}">${captionTrack(m,m.version)}</video>`:`<div class="video-placeholder"><div class="play-icon">&#9654;</div><strong>Lesson video</strong><p>The creator has not added a video yet.<br>You can still work through the lessons and questions below.</p></div>`}</div><div id="quiz-area" aria-live="polite" aria-atomic="true"></div><section class="panel" style="margin-top:17px"><h2 id="lesson-title">${esc(initial?.title||'Welcome')}</h2><p id="lesson-summary">${esc(initial?.summary||'Choose a lesson to begin.')}</p><div class="progress"><i id="lesson-progress" style="width:${Math.round(S.progress.completed.size/Math.max(m.lessons.length,1)*100)}%"></i></div><p class="hint" id="resume-note">${S.progress.position>0?'Your progress is saved. Resume from where you left off.':''}</p></section></section><aside><section class="panel"><h2>Course outline</h2><p>${m.lessons.length} short lessons</p><div class="lesson-list">${m.lessons.map((x,i)=>`<button class="lesson-button" data-jump="${i}"><span class="lesson-number">${S.progress.completed.has(x.id)?'&#10003;':i+1}</span><span><strong style="font-size:12px">${esc(x.title)}</strong><small>${m.questions.filter(q=>q.at>=x.start&&q.at<=x.end).map(q=>'Question at '+videoTime(q.at)).join(' · ')||'Starts at '+videoTime(x.start)}</small></span></button>`).join('')}</div></section></aside></div>`);document.querySelector('#back').onclick=home;document.querySelector('#reset-progress').onclick=resetLearnerProgress;document.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>jumpLesson(+b.dataset.jump));const v=document.querySelector('#player');if(v){v.addEventListener('loadedmetadata',()=>{if(S.progress.position>0&&S.progress.position<v.duration)v.currentTime=S.progress.position});v.addEventListener('timeupdate',()=>{checkQuestions(v.currentTime);trackPlayback(v.currentTime)});v.addEventListener('ended',()=>{trackPlayback(v.duration,true);checkQuestions(Infinity)});v.addEventListener('pause',()=>{S.progress.lastSaved=0;trackPlayback(v.currentTime)});v.addEventListener('play',()=>{if(S.activeQuestion)v.pause()});v.addEventListener('seeking',()=>{const q=S.activeQuestion?S.module.questions.find(x=>x.id===S.activeQuestion):S.module.questions.filter(x=>!S.asked.has(x.id)&&x.at<v.currentTime).sort((a,b)=>a.at-b.at)[0];if(q){v.pause();v.currentTime=q.at;showQuestion(q)}});v.addEventListener('seeked',()=>{const q=S.activeQuestion?S.module.questions.find(x=>x.id===S.activeQuestion):S.module.questions.filter(x=>!S.asked.has(x.id)&&x.at<=v.currentTime).sort((a,b)=>a.at-b.at)[0];if(q){v.pause();if(Math.abs(v.currentTime-q.at)>.1)v.currentTime=q.at;showQuestion(q)}trackPlayback(v.currentTime);checkQuestions(v.currentTime)})}}
async function resetLearnerProgress(){const button=document.querySelector('#reset-progress');button.disabled=true;const video=document.querySelector('#player');if(video)video.pause();try{await S.progress.queue;await api('/api/modules/'+S.module.id+'/reset-progress','POST',{});S.attempt=await api('/api/attempts','POST',{module_id:S.module.id});S.progress={position:0,completed:new Set(),lastSaved:Date.now()};S.asked=new Set();S.activeQuestion=null;S.modules=await api('/api/modules');renderLearner();toast('Progress reset. Start the video from the beginning.')}catch(e){button.disabled=false;toast(e.message)}}
function saveProgress(position,lessonId){const attemptId=S.attempt.id;const lessons=S.module.lessons;const send=async(attempt=0)=>{try{const result=await api('/api/attempts/'+attemptId+'/progress','POST',{position,lesson_id:lessonId});if(S.attempt.id!==attemptId)return;S.progress.position=result.position;S.progress.completed=new Set(result.completed_lessons);S.progress.pending=null;lessons.forEach((x,i)=>{const mark=document.querySelector(`[data-jump="${i}"] .lesson-number`);if(mark)mark.textContent=S.progress.completed.has(x.id)?String.fromCharCode(10003):String(i+1)});const bar=document.querySelector('#lesson-progress');if(bar)bar.style.width=Math.round(S.progress.completed.size/Math.max(S.module.lessons.length,1)*100)+'%';return result}catch(e){if(S.attempt.id===attemptId&&attempt<4){await delay(500*Math.pow(2,attempt));return send(attempt+1)}S.progress.pending={position,lessonId};throw e}};S.progress.queue=(S.progress.queue||Promise.resolve()).then(()=>send()).catch(()=>toast('Progress could not be saved. It will retry at the next checkpoint.'));return S.progress.queue}
function lessonWatched(x){const v=document.querySelector('#player');if(!v)return false;for(let i=0;i<v.played.length;i++)if(v.played.start(i)<=x.start+1&&v.played.end(i)>=x.end-1)return true;return false}
function trackPlayback(position,ended=false){const now=Date.now();const lesson=S.module.lessons.find(x=>position>=x.start&&position<x.end);if(lesson){document.querySelector('#lesson-title').textContent=lesson.title;document.querySelector('#lesson-summary').textContent=lesson.summary}const completedLesson=S.module.lessons.find(x=>!S.progress.completed.has(x.id)&&lessonWatched(x));if(completedLesson){S.progress.completed.add(completedLesson.id);const button=document.querySelector(`[data-jump="${S.module.lessons.indexOf(completedLesson)}"] .lesson-number`);if(button)button.textContent=String.fromCharCode(10003);document.querySelector('#lesson-progress').style.width=Math.round(S.progress.completed.size/Math.max(S.module.lessons.length,1)*100)+'%';S.progress.lastSaved=now;saveProgress(position,completedLesson.id)}else if(now-S.progress.lastSaved>5000){S.progress.lastSaved=now;saveProgress(position)}}
function jumpLesson(i){const x=S.module.lessons[i];document.querySelector('#lesson-title').textContent=x.title;document.querySelector('#lesson-summary').textContent=x.summary;const v=document.querySelector('#player');if(v){v.currentTime=x.start;v.play().catch(()=>{})}else{saveProgress(x.start,x.id);if(S.module.questions.length){const q=S.module.questions.find(q=>!S.asked.has(q.id));if(q)showQuestion(q)}}}
function checkQuestions(t){if(S.activeQuestion)return;const q=S.module.questions.filter(q=>!S.asked.has(q.id)).sort((a,b)=>a.at-b.at)[0];if(q&&q.at<=t){const v=document.querySelector('#player');if(v)v.pause();showQuestion(q)}}
function showQuestion(q){if(S.asked.has(q.id)||S.activeQuestion)return;S.activeQuestion=q.id;const el=document.querySelector('#quiz-area');el.innerHTML=`<section class="quiz-box" role="dialog" aria-modal="false" aria-labelledby="quiz-prompt" tabindex="-1"><span class="eyebrow">KNOWLEDGE CHECK</span><h2 id="quiz-prompt" style="font-size:18px;margin:5px 0 15px">${esc(q.prompt)}</h2><form id="answer-form"><fieldset style="border:0;padding:0;margin:0"><legend class="hint" style="margin-bottom:8px">Choose one answer</legend>${q.options.map((o,i)=>`<label class="quiz-option"><input required type="radio" name="choice" value="${i}"> &nbsp;${esc(o)}</label>`).join('')}</fieldset><button class="button small" style="margin-top:10px">Check answer</button></form></section>`;el.querySelector('input')?.focus();document.querySelector('#answer-form').onsubmit=async e=>{e.preventDefault();const choice=+new FormData(e.currentTarget).get('choice');try{const result=await api('/api/attempts/'+S.attempt.id,'POST',{question_id:q.id,choice});S.asked.add(q.id);S.activeQuestion=null;el.innerHTML=`<section class="quiz-box" role="status" aria-live="polite" tabindex="-1"><span class="pill ${result.correct?'published':'draft'}">${result.correct?'Correct':'Not quite'}</span><p style="margin:10px 0">${esc(result.explanation)}</p><strong>Current score: ${result.score}% · Passing: ${result.pass_score}%</strong><p style="margin-bottom:0">${result.completed?(result.passed?'You passed this module. Nice work!':`You completed every lesson and question, but the score is below the ${result.pass_score}% passing mark.`):'Continue with the next lesson when you’re ready.'}</p></section>`;el.querySelector('.quiz-box')?.focus();const v=document.querySelector('#player');if(v&&v.currentTime<v.duration){checkQuestions(v.currentTime);if(!S.activeQuestion)v.play().catch(()=>{})}}catch(e){toast(e.message)}}}
async function logout(){const adminMode=location.pathname==='/admin';await api('/api/logout','POST',{}).catch(()=>{});S.user=null;S.csrf='';S.admin=null;login(adminMode)}
const renderEditorBase=renderEditor;
renderEditor=function(){renderEditorBase();const input=document.querySelector('#video-file');if(input)input.onchange=previewSelectedVideo;showLocalPreview()};
boot();
