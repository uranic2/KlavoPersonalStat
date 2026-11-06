'use strict';
let detailsContext=null,detailsGeneration=0;
function profileUrl(url){return state.profileId?url+(url.includes('?')?'&':'?')+'profile='+state.profileId:url;}
let vocabularyMenuTarget=null,refreshPending=false;
function rowActions(r){
  if(!state.goalData)return `<div class="row-actions">${[['refresh','Обновить'],['chart','График']].map(([key,label])=>`<button class="button secondary" data-voc-action="${key}" data-voc-id="${r.id}" aria-label="${label}: ${esc(displayName(r))}, словарь ${r.id}" ${key==='refresh'&&(state.jobRunning||refreshPending)?'disabled':''}>${label}</button>`).join('')}</div>`;
  const label=esc(displayName(r))+', словарь '+r.id;
  return `<div class="row-actions compact-actions"><a class="button secondary" href="${trainingUrl(r.id)}" target="_blank" rel="noopener" title="Тренировать" aria-label="Тренировать: ${label}">▶</a><button class="button secondary ${state.jobRunning||refreshPending?'refreshing':''}" data-voc-action="refresh" data-voc-id="${r.id}" aria-busy="${state.jobRunning||refreshPending}" title="Загрузить данные" aria-label="Загрузить данные: ${label}" ${state.jobRunning||refreshPending?'disabled':''}><svg class="import-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M12 3v12m-5-5 5 5 5-5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></svg></button><button class="button secondary" data-voc-action="more" data-voc-id="${r.id}" title="Ещё" aria-label="Ещё: ${label}" aria-haspopup="true" aria-expanded="false">⋯</button></div>`;
}
function closeVocabularyMenu(){
  $('#vocabulary-menu').hidePopover();
  vocabularyMenuTarget?.setAttribute('aria-expanded','false');vocabularyMenuTarget=null;
}
function openVocabularyMenu(id,button){
  const menu=$('#vocabulary-menu');
  if(vocabularyMenuTarget===button){closeVocabularyMenu();return;}
  closeVocabularyMenu();vocabularyMenuTarget=button;
  const external=(label,url)=>`<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
  menu.innerHTML=`<button data-voc-action="requirement" data-voc-id="${id}">Настроить требование в цели</button>`+
    external('Страница словаря',`https://klavogonki.ru/vocs/${id}/`)+
    external('Открытая игра 10 сек',`https://klavogonki.ru/create/?submit=1&gametype=voc&voc=${id}&type=normal&level_from=1&level_to=9&timeout=10`)+
    external('Рекорды',`https://klavogonki.ru/vocs/${id}/top/week/`);
  menu.showPopover();button.setAttribute('aria-expanded','true');
  const rect=button.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(rect.right-menu.offsetWidth,window.innerWidth-menu.offsetWidth-8))+'px';
  menu.style.top=Math.max(8,Math.min(rect.bottom+6,window.innerHeight-menu.offsetHeight-8))+'px';
  menu.querySelector('button').focus();
}
function detailMessage(message){$('#details-message').textContent=message;}
function currentDetails(ctx){return detailsContext===ctx&&ctx.generation===detailsGeneration&&ctx.profile===state.profileId&&$('#details-dialog').open;}
function chartSVG(rows,keys,threshold=null){
  const w=800,h=240,left=64,right=24,top=20,bottom=40,plotW=w-left-right,plotH=h-top-bottom;
  const values=rows.flatMap(r=>keys.map(k=>r[k]).filter(v=>v!=null));if(threshold!=null)values.push(threshold);
  const max=Math.max(1,...values)*1.1,x=i=>left+(rows.length<2?plotW/2:i*plotW/(rows.length-1)),y=v=>h-bottom-v/max*plotH;
  let paths='';
  keys.forEach((key,index)=>{
    let points='',gap=true;
    rows.forEach((r,i)=>{if(r[key]==null){gap=true;return;}points+=(gap?'M':'L')+x(i).toFixed(1)+','+y(r[key]).toFixed(1)+' ';gap=false;});
    paths+=`<path class="chart-line chart-series-${index}" d="${points}"/>`;
    paths+=rows.map((r,i)=>r[key]==null?'':`<circle class="chart-dot-${index}" cx="${x(i)}" cy="${y(r[key])}" r="2.5"/>`).join('');
  });
  const ticks=[0,.5,1].map(t=>`<line class="chart-grid" x1="${left}" x2="${w-right}" y1="${y(t*max)}" y2="${y(t*max)}"/><text x="${left-8}" y="${y(t*max)+4}" text-anchor="end">${Math.round(t*max)}</text>`).join('');
  const dates=[...new Set([0,Math.floor((rows.length-1)/2),rows.length-1])].filter(i=>i>=0).map(i=>`<text x="${x(i)}" y="${h-12}" text-anchor="middle">${fmtDate(rows[i].day)}</text>`).join('');
  const line=threshold==null?'':`<line class="chart-threshold" x1="${left}" x2="${w-right}" y1="${y(threshold)}" y2="${y(threshold)}"/><text x="${left+6}" y="${y(threshold)-5}">Требование: ${threshold}</text>`;
  return `<svg class="progress-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${keys.includes('races')?'Количество заездов по дням':'Максимальная и средняя скорость по дням'}">${ticks}${dates}${paths}${line}</svg>`;
}
function renderChart(data,ctx){
  const freshness=data.fetched_at?'Обновлено '+new Date(data.fetched_at).toLocaleString('ru',{timeZone:'Europe/Moscow'}):'История ещё не загружена.';
  detailMessage(data.future?'Период ещё не начался.':(data.complete?'История за период загружена. ':'История неполна. ')+freshness);
  $('#details-load').hidden=data.complete||data.future;
  const any=data.rows.some(r=>r.max_speed!=null||r.races>0);
  $('#details-content').innerHTML=(any?'<h3>Скорость, зн/мин</h3><p class="chart-legend">● Максимальная · <span>● Средняя</span></p>'+chartSVG(data.rows,['max_speed','avg_speed'],ctx.threshold)+'<h3>Заезды по дням</h3>'+chartSVG(data.rows,['races']):'<p class="empty">'+(data.complete?'Заездов за период нет.':'Нет загруженных результатов за период.')+'</p>')+
    (ctx.threshold!=null?'<p class="hint">Линия требования показывает порог скорости. График не подтверждает ограничение по ошибкам.</p>':'')+
    '<details class="chart-data"><summary>Данные по дням</summary><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Максимум, зн/мин</th><th>Средняя, зн/мин</th><th>Заездов</th><th>Данные</th></tr></thead><tbody>'+data.rows.map(r=>`<tr><td>${fmtDate(r.day)}</td><td>${r.max_speed??'—'}</td><td>${r.avg_speed??'—'}</td><td>${r.races??'—'}</td><td>${r.known?'Загружено':'Нет данных'}</td></tr>`).join('')+'</tbody></table></div></details>';
}
async function loadChart(ctx){
  const generation=++ctx.request;
  const data=await request('/api/chart?voc='+ctx.id+'&from='+encodeURIComponent($('#details-from').value)+'&to='+encodeURIComponent($('#details-to').value));
  if(currentDetails(ctx)&&ctx.request===generation)renderChart(data,ctx);
}
async function refreshVocabulary(id,custom=null){
  if(refreshPending||state.jobRunning)return;
  refreshPending=true;updateRefreshButtons(true);
  const body={voc_id:id,...(state.goal?{goal_id:Number(state.goal)}:{})};
  if(custom){delete body.goal_id;body.date_from=custom.from;body.date_to=custom.to;}
  try{await request('/api/sync',body);state.jobRunning=true;await poll();}
  finally{refreshPending=false;updateRefreshButtons(state.jobRunning);}
}
async function openVocabulary(id,type){
  const r=(state.goalData?.rows||state.data.rows).find(r=>r.id===id);if(!r)return;
  if(type==='refresh'){try{await refreshVocabulary(id);}catch(e){error(e.message);}return;}
  if(type!=='chart')return;
  const period=state.goalData||state.data;
  const ctx=detailsContext={id,type,profile:state.profileId,generation:++detailsGeneration,request:0,threshold:state.goalData?r.speed:null};
  $('#details-title').textContent='Прогресс по словарю';$('#details-voc').textContent=displayName(r)+' · №'+id;
  $('#details-from').value=period.period_from;$('#details-to').value=period.period_to;
  $('#details-submit').textContent='Показать';$('#details-submit').disabled=false;$('#details-load').hidden=true;$('#details-content').innerHTML='';detailMessage('');$('#details-dialog').showModal();
  if(type==='chart'){detailMessage('Читаем сохранённую историю…');try{await loadChart(ctx);}catch(e){if(currentDetails(ctx))detailMessage(e.message);}}
}
function updateRefreshButtons(busy){
  document.querySelectorAll('[data-voc-action="refresh"]').forEach(b=>{b.disabled=busy;b.classList.toggle('refreshing',busy);b.setAttribute('aria-busy',String(busy));});
}
function setupDetails(){
  const menu=document.createElement('div');menu.id='vocabulary-menu';menu.className='table-popover vocabulary-menu';menu.setAttribute('popover','auto');menu.setAttribute('aria-label','Действия со словарём');document.body.append(menu);
  menu.addEventListener('toggle',e=>{if(e.newState==='closed'){vocabularyMenuTarget?.setAttribute('aria-expanded','false');vocabularyMenuTarget=null;}});
  menu.addEventListener('keydown',e=>{
    const items=[...menu.querySelectorAll('button,a')],index=items.indexOf(document.activeElement);
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();items[(index+(e.key==='ArrowDown'?1:items.length-1))%items.length].focus();}
    if(e.key==='Escape'){e.preventDefault();const target=vocabularyMenuTarget;closeVocabularyMenu();target?.focus();}
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-voc-action]');
    if(b){
      const id=Number(b.dataset.vocId),action=b.dataset.vocAction;
      if(action==='more'){openVocabularyMenu(id,b);return;}
      closeVocabularyMenu();
      if(action==='requirement'){
        const goal=Number(state.goal);if(!goal)return;
        await openGoal(goal);
        const input=$(`#goal-items tr[data-id="${id}"] [data-field="speed"]`);input?.focus();input?.scrollIntoView({block:'center'});return;
      }
      await openVocabulary(id,action);
    }else if(e.target.closest('#vocabulary-menu a'))closeVocabularyMenu();
  });
  $('#details-close').onclick=()=>$('#details-dialog').close();
  $('#details-dialog').addEventListener('close',()=>{detailsContext=null;++detailsGeneration;});
  $('#details-form').onsubmit=async e=>{
    e.preventDefault();const ctx=detailsContext;if(!ctx||ctx.busy)return;
    if($('#details-from').value>$('#details-to').value){detailMessage('Дата начала не должна быть позже даты окончания.');return;}
    ctx.busy=true;$('#details-submit').disabled=true;$('#details-content').innerHTML='';detailMessage('Читаем сохранённую историю…');
    try{await loadChart(ctx);}
    catch(e){if(currentDetails(ctx))detailMessage(e.message);}
    finally{ctx.busy=false;if(currentDetails(ctx))$('#details-submit').disabled=false;}
  };
  $('#details-load').onclick=async()=>{
    const ctx=detailsContext;if(!ctx)return;
    $('#details-load').disabled=true;
    try{await refreshVocabulary(ctx.id,{from:$('#details-from').value,to:$('#details-to').value});if(currentDetails(ctx))detailMessage('Загрузка запущена. Ход обновления показан на дашборде.');}
    catch(e){if(currentDetails(ctx))detailMessage(e.message);}
    finally{if(currentDetails(ctx))$('#details-load').disabled=false;}
  };
}
