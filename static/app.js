'use strict';
const $ = selector => document.querySelector(selector);
function applyTheme(theme){
  const selected=theme==='light'?'light':'dark';
  document.documentElement.dataset.theme=selected;
  return selected;
}
let initialTheme='dark';
try{initialTheme=localStorage.getItem('klavo-theme')||'dark';}catch(exc){}
applyTheme(initialTheme);
function setupTheme(){
  const control=$('#theme-select');control.value=document.documentElement.dataset.theme;
  control.onchange=()=>{const theme=applyTheme(control.value);try{localStorage.setItem('klavo-theme',theme);}catch(exc){}};
}

const state = {profileId:null,group:localStorage.getItem('klavo-group') || '1',goal:localStorage.getItem('klavo-goal'),section:'dashboard',settingsTab:'goals',catalog:null,goalData:null,data:null,token:null,sort:null,direction:1,page:0,pageSize:40,editing:null,deleteConfirm:false,jobVersion:null,jobRunning:false,polling:false,loading:0,viewLoading:false,committed:null};
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDate = value => value ? value.split('-').reverse().join('.') : '—';
const query = () => state.group === 'all' ? '' : '?group='+encodeURIComponent(state.group);
const displayName = row => row.short_name || row.name;
const matchesVocabulary = (row,search) => [row.name,row.short_name,String(row.id)].some(value=>String(value||'').toLocaleLowerCase('ru').includes(search));
function trainingUrl(id){const url=new URL('https://klavogonki.ru/create/');url.search=new URLSearchParams({gametype:'voc',voc:String(id),type:'practice',level_from:'1',level_to:'8',timeout:'5',submit:'Начать'}).toString();return url.href;}
function error(message){$('#error-box').textContent=message;$('#error-box').hidden=!message;}
let toastTimer;
function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function request(url,body){
  if(state.profileId){if(body===undefined)url+=(url.includes('?')?'&':'?')+'profile='+state.profileId;else body={...body,profile:state.profileId};}
  const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Klavo-Token':state.token},body:JSON.stringify(body)};
  let response;
  try{response=await fetch(url,options);}catch(exc){throw new Error('Нет связи с локальным приложением. Убедитесь, что оно запущено.');}
  const data=await response.json();
  if(!response.ok)throw new Error(data.error || 'Не удалось выполнить запрос.');
  return data;
}
async function loadData(){
  const requestId=++state.loading;
  const selection={goal:state.goal,group:state.group};
  state.viewLoading=true;$('#refresh').disabled=true;$('#view-loading').hidden=false;$('#dashboard-view').setAttribute('aria-busy','true');
  try{
    const missingAsNull=(promise,message)=>promise.catch(exc=>{if(exc.message===message)return null;throw exc;});
    const [data,catalog,goalData]=await Promise.all([
      missingAsNull(request('/api/data'+(selection.group==='all'?'':'?group='+encodeURIComponent(selection.group))),'Группа не найдена.'),
      request('/api/catalog'),
      selection.goal?missingAsNull(request('/api/goal?id='+encodeURIComponent(selection.goal)),'Цель не найдена.'):Promise.resolve(null)
    ]);
    if(requestId!==state.loading)return;
    if(!data){state.group='all';localStorage.setItem('klavo-group','all');return loadData();}
    // Commit one complete snapshot. Stale responses never mutate displayed state.
    Object.assign(state,{profileId:data.profile?.id||data.user_id,data,catalog,goalData,token:data.token,goal:goalData?String(goalData.goal.id):null,group:selection.group});
    if(state.goal)localStorage.setItem('klavo-goal',state.goal);else localStorage.removeItem('klavo-goal');
    state.committed={goal:state.goal,group:state.group};
    configureTable();renderNavigation();renderHeader();renderTable();renderSettings();error('');
  }catch(exc){
    if(requestId!==state.loading)return;
    if(state.committed){Object.assign(state,state.committed);if(state.goal)localStorage.setItem('klavo-goal',state.goal);else localStorage.removeItem('klavo-goal');localStorage.setItem('klavo-group',state.group);renderNavigation();}
    error('Не удалось загрузить выбранный экран: '+exc.message);throw exc;
  }finally{
    if(requestId===state.loading){state.viewLoading=false;$('#view-loading').hidden=true;$('#dashboard-view').setAttribute('aria-busy','false');$('#refresh').disabled=state.jobRunning;$('#add-group').disabled=state.jobRunning;$('#edit-group').disabled=state.jobRunning;}
  }
}
function renderNavigation(){
  const profileField=$('#settings-profile-id');if(profileField&&document.activeElement!==profileField)profileField.value=state.profileId||'';
  const profile=state.data.profile;if(profile){const link=$('#profile-link');link.textContent=profile.name||'Профиль №'+profile.id;link.href='https://klavogonki.ru/u/#/'+profile.id+'/stats/';link.title='Профиль №'+profile.id;}
  const total=new Set(state.data.rows.map(r=>r.id)).size;
  let html=state.catalog.goals.map(g=>`<button class="nav-group ${state.goal===String(g.id)?'active':''}" data-goal="${g.id}" ${state.goal===String(g.id)?'aria-current="page"':''}><span class="nav-icon">◉</span><span class="nav-label">${esc(g.name)}</span><span class="nav-count">${g.total}</span></button>`).join('');
  html+='<div class="nav-divider">СТАТИСТИКА</div>';
  html+=`<button class="nav-group ${!state.goal&&state.group==='all'?'active':''}" data-group="all" ${!state.goal&&state.group==='all'?'aria-current="page"':''}><span class="nav-icon">▦</span><span class="nav-label">Все словари</span></button>`;
  let custom=false;
  state.data.groups.forEach(g=>{if(!g.builtin&&!custom){html+='<div class="nav-divider">МОИ ГРУППЫ</div>';custom=true;}
    html+=`<button class="nav-group ${!state.goal&&state.group===String(g.id)?'active':''}" data-group="${g.id}" ${!state.goal&&state.group===String(g.id)?'aria-current="page"':''}><span class="nav-icon">${g.builtin?'▤':'◇'}</span><span class="nav-label">${esc(g.name)}</span><span class="nav-count">${g.total}</span></button>`;
  });
  $('#groups').innerHTML=html;
}
function currentGroup(){return state.data.groups.find(g=>String(g.id)===state.group);}
function renderHeader(){
  if(state.goalData){renderGoalHeader();return;}
  const d=state.data,g=currentGroup();
  $('#group-title').textContent=g?g.name:'Все словари';
  document.title=(g?g.name:'Все словари')+' · KlavoPersonalStat';
  const source=g&&g.source_url?` · <a href="${esc(g.source_url)}" target="_blank" rel="noopener">Источник ↗</a>`:'';
  $('#group-subtitle').innerHTML=`${fmtDate(d.period_from)} — ${fmtDate(d.period_to)} <span>· Москва</span>${source}`;
  $('#edit-group').hidden=true;
  $('#goal-progress').hidden=true;$('#edit-current-goal').hidden=true;
  $('#refresh').title='Обновить результаты с Клавогонок';
  $('#export').href=profileUrl('/api/export'+query());
  $('#count-total').textContent=d.rows.length;
  $('#count-played').textContent=d.rows.filter(r=>r.record!==null).length;
  $('#count-active').textContent=d.rows.filter(r=>r.month_max!==null).length;
  $('#count-races').textContent=d.rows.reduce((sum,r)=>sum+r.month_races,0).toLocaleString('ru');
  const dates=d.rows.map(r=>r.fetched_at).filter(Boolean).sort();
  const missing=d.rows.filter(r=>!r.fetched_at).length;
  $('#freshness').textContent=dates.length?'Данные на '+new Date(dates[0]).toLocaleString('ru',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'})+(missing?` · Ещё не загружено: ${missing}`:''):'Нажмите «Обновить», чтобы загрузить статистику.';
}
function renderTable(){
  if(!state.data)return;
  if(state.goalData){renderGoalTable();return;}
  const search=$('#search').value.trim().toLocaleLowerCase('ru'),filter=$('#filter').value;
  const rows=state.data.rows.filter(r=>matchesVocabulary(r,search)&&(filter==='all'||filter==='played'&&r.record!==null||filter==='active'&&r.month_max!==null||filter==='unplayed'&&r.record===null));
  if(state.sort)rows.sort((a,b)=>{const x=state.sort==='name'?displayName(a):a[state.sort],y=state.sort==='name'?displayName(b):b[state.sort];if(x==null)return y==null?0:1;if(y==null)return -1;return state.direction*(typeof x==='number'?x-y:String(x).localeCompare(String(y),'ru'));});
  state.page=Math.min(state.page,Math.max(0,Math.ceil(rows.length/state.pageSize)-1));
  const from=state.page*state.pageSize;
  $('#rows').innerHTML=rows.slice(from,from+state.pageSize).map(r=>{
    const newRecord=r.record_date&&r.record_date>=state.data.period_from&&r.record_date<=state.data.period_to;
    const pending=!r.fetched_at;
    const number=r.record===null?'<span class="no-value">—</span>':r.record;
    const month=r.month_max===null?(pending?'<span class="pending">Не загружено</span>':'<span class="no-value">—</span>'):r.month_max;
    return `<tr><td><a href="${trainingUrl(r.id)}" title="${esc(r.name)}" target="_blank" rel="noopener">${esc(displayName(r))}</a><small>№${r.id}</small></td><td class="number">${number}</td><td>${fmtDate(r.record_date)}</td><td class="number month-number">${month}${newRecord?'<span class="record-badge">Рекорд</span>':''}</td><td>${fmtDate(r.month_date)}</td><td>${rowActions(r)}</td></tr>`;
  }).join('');
  $('#empty').hidden=!!rows.length;
  $('#shown-count').textContent=rows.length;
  $('#page-info').textContent=rows.length?`${from+1}–${Math.min(from+state.pageSize,rows.length)} из ${rows.length} словарей`:'0 словарей';
  $('#prev').disabled=state.page===0;$('#next').disabled=from+state.pageSize>=rows.length;
  document.querySelectorAll('th').forEach(th=>th.removeAttribute('aria-sort'));
  if(state.sort)document.querySelector(`[data-sort="${state.sort}"]`).parentElement.setAttribute('aria-sort',state.direction===1?'ascending':'descending');
}
async function poll(){
  if(state.polling)return;state.polling=true;
  try{
    const job=await request('/api/status');
    const wasRunning=state.jobRunning;state.jobRunning=job.running;
    $('#refresh').disabled=job.running||state.viewLoading;$('#add-group').disabled=job.running;$('#edit-group').disabled=job.running;
    $('#refresh').classList.toggle('refreshing',job.running);
    document.querySelectorAll('[data-voc-action="refresh"]').forEach(b=>b.disabled=job.running);
    if(!job.running&&wasRunning&&detailsContext?.type==='chart'){const ctx=detailsContext;loadChart(ctx).catch(e=>{if(currentDetails(ctx))detailMessage(e.message);});}
    $('#sync-box').hidden=!job.running;
    $('#sync-message').textContent=job.message;
    $('#sync-count').textContent=job.total?`${job.done} / ${job.total}`:'';
    const p=$('#sync-progress');p.max=job.total||1;if(job.total)p.value=job.done;else p.removeAttribute('value');
    if(!job.running&&state.jobVersion!==null&&job.version!==state.jobVersion){
      await loadData();
      if(job.error)error(job.message+'\n'+job.error);else{error('');toast(job.message);}
    }else if(!job.running&&state.jobVersion===null&&job.error)error(job.message+'\n'+job.error);
    state.jobVersion=job.version;
  }catch(exc){error('Нет связи с локальным приложением. Запустите start.cmd и перезагрузите страницу.');}
  finally{state.polling=false;}
}
async function navigateGoal(id){state.goal=String(id);state.page=0;state.sort=null;$('#search').value='';showSection('dashboard');try{await loadData();}catch(exc){error('Не удалось открыть цель: '+exc.message);}}
$('#groups').addEventListener('click',async event=>{
  const goal=event.target.closest('[data-goal]');
  if(goal){await navigateGoal(goal.dataset.goal);return;}
  const button=event.target.closest('[data-group]');if(!button)return;
  state.goal=null;localStorage.removeItem('klavo-goal');showSection('dashboard');
  state.group=button.dataset.group;state.page=0;state.sort=null;$('#search').value='';localStorage.setItem('klavo-group',state.group);
  try{await loadData();}catch(exc){error(exc.message);}
});
$('#search').addEventListener('input',()=>{state.page=0;renderTable();});
$('#filter').addEventListener('change',()=>{state.page=0;renderTable();});
$('#prev').onclick=()=>{state.page--;renderTable();};$('#next').onclick=()=>{state.page++;renderTable();};
$('#table-head').onclick=event=>{const button=event.target.closest('[data-sort]');if(!button)return;if(state.sort===button.dataset.sort)state.direction*=-1;else{state.sort=button.dataset.sort;state.direction=state.sort==='name'?1:-1;}state.page=0;renderTable();};
$('#refresh').onclick=async()=>{
  $('#refresh').disabled=true;error('');
  try{await request('/api/sync',state.goal?{goal_id:Number(state.goal)}:{group_id:state.group==='all'?null:Number(state.group)});await poll();}
  catch(exc){error(exc.message);$('#refresh').disabled=false;}
};
function openGroup(edit){
  state.editing=edit?currentGroup():null;state.deleteConfirm=false;
  $('#group-form').reset();$('#form-error').hidden=true;$('#delete-hint').hidden=true;$('#import-details').open=false;
  $('#dialog-title').textContent=edit?'Изменить группу':'Новая группа';
  $('#save-group').textContent=edit?'Сохранить':'Создать группу';$('#delete-group').hidden=!edit;
  if(edit){$('#group-name').value=state.editing.name;$('#group-source').value=state.editing.source_url;$('#group-vocs').value=state.data.rows.map(r=>String(r.id)).join('\n');}
  $('#group-dialog').showModal();$('#group-name').focus();
}
$('#add-group').onclick=()=>openGroup(false);$('#edit-group').onclick=()=>openGroup(true);
$('#close-dialog').onclick=$('#cancel-dialog').onclick=()=>$('#group-dialog').close();
$('#group-source').addEventListener('input',()=>{if(!state.editing)$('#import-source').checked=!!$('#group-source').value.trim();});
$('#group-form').addEventListener('submit',async event=>{
  event.preventDefault();$('#save-group').disabled=true;$('#delete-group').disabled=true;$('#form-error').hidden=true;
  const original=$('#save-group').textContent;$('#save-group').textContent='Сохраняем…';
  try{
    const result=await request('/api/groups/save',{id:state.editing?.id,name:$('#group-name').value,dictionaries:$('#group-vocs').value,source_url:$('#group-source').value,import_source:$('#import-source').checked});
    state.group=String(result.id);state.page=0;state.sort=null;localStorage.setItem('klavo-group',state.group);
    await loadData();$('#group-dialog').close();toast('Группа сохранена. Нажмите «Обновить», чтобы загрузить её статистику.');
  }catch(exc){$('#form-error').textContent=exc.message;$('#form-error').hidden=false;}
  finally{$('#save-group').disabled=false;$('#delete-group').disabled=false;$('#save-group').textContent=original;}
});
$('#delete-group').onclick=async()=>{
  if(!state.deleteConfirm){state.deleteConfirm=true;$('#delete-hint').hidden=false;return;}
  $('#delete-group').disabled=true;
  try{await request('/api/groups/delete',{id:state.editing.id});state.group='1';state.page=0;localStorage.setItem('klavo-group',state.group);await loadData();$('#group-dialog').close();toast('Группа удалена. Статистика словарей сохранена.');}
  catch(exc){$('#form-error').textContent=exc.message;$('#form-error').hidden=false;}
  finally{$('#delete-group').disabled=false;}
};
let pollTimer=null;
function startPolling(){if(pollTimer===null)pollTimer=setInterval(poll,1500);}
function showProfileSetup(){
  $('#profile-setup').hidden=false;$('#dashboard-view').hidden=true;$('#settings-view').hidden=true;
  $('#nav-dashboard').disabled=true;$('#nav-settings').disabled=true;
}
function setupProfiles(){
  for(const prefix of ['setup','settings']){
    const form=$('#'+prefix+'-profile-form');
    form.onsubmit=async e=>{
      e.preventDefault();const button=form.querySelector('button');button.disabled=true;error('');
      try{
        const result=await request('/api/profile/select',{value:$('#'+prefix+'-profile-id').value});
        state.profileId=result.profile.id;state.goal=null;state.goalData=null;state.group='all';state.committed=null;state.page=0;state.sort=null;state.jobVersion=null;
        localStorage.removeItem('klavo-goal');localStorage.setItem('klavo-group','all');$('#search').value='';
        await loadData();$('#profile-setup').hidden=true;$('#nav-dashboard').disabled=false;$('#nav-settings').disabled=false;showSection('dashboard');startPolling();toast('Профиль выбран. Нажмите «Обновить», чтобы загрузить свои результаты.');
      }catch(exc){error(exc.message);}
      finally{button.disabled=false;}
    };
  }
}
async function init(){setupTheme();setupGoals();setupDetails();setupProfiles();try{const bootstrap=await request('/api/bootstrap');state.token=bootstrap.token;if(!bootstrap.profile){showProfileSetup();return;}state.profileId=bootstrap.profile.id;await loadData();await poll();startPolling();setInterval(()=>{const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow'}).format(new Date());if(day!==window.klavoDay){const was=window.klavoDay;window.klavoDay=day;if(was)loadData().catch(e=>error(e.message));}},30000);}catch(exc){error(exc.message);}}
init();
