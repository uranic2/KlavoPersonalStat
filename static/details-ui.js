'use strict';
let detailsContext=null,detailsGeneration=0;
function profileUrl(url){return state.profileId?url+(url.includes('?')?'&':'?')+'profile='+state.profileId:url;}
function rowActions(r){
  return `<div class="row-actions">${[['refresh','Обновить'],['chart','График'],['errors','Ошибки']].map(([key,label])=>`<button class="button secondary" data-voc-action="${key}" data-voc-id="${r.id}" aria-label="${label}: ${esc(displayName(r))}, словарь ${r.id}" ${key==='refresh'?'title="Обновить результаты этого словаря с Клавогонок"':''} ${key==='refresh'&&state.jobRunning?'disabled':''}>${label}</button>`).join('')}</div>`;
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
  const body={voc_id:id,...(state.goal?{goal_id:Number(state.goal)}:{})};
  if(custom){delete body.goal_id;body.date_from=custom.from;body.date_to=custom.to;}
  await request('/api/sync',body);await poll();
}
async function openVocabulary(id,type){
  const r=(state.goalData?.rows||state.data.rows).find(r=>r.id===id);if(!r)return;
  if(type==='refresh'){try{await refreshVocabulary(id);}catch(e){error(e.message);}return;}
  const period=state.goalData||state.data;
  const ctx=detailsContext={id,type,profile:state.profileId,generation:++detailsGeneration,request:0,threshold:state.goalData?r.speed:null};
  $('#details-title').textContent=type==='chart'?'Прогресс по словарю':'Слова с ошибками';$('#details-voc').textContent=displayName(r)+' · №'+id;
  $('#details-from').value=period.period_from;$('#details-to').value=period.period_to;$('#details-limit').value=10;
  $('#details-limit-field').hidden=type!=='errors';$('#details-limit').required=type==='errors';$('#details-submit').textContent=type==='chart'?'Показать':'Проанализировать';$('#details-submit').disabled=false;$('#details-load').hidden=true;$('#details-content').innerHTML='';detailMessage('');$('#details-dialog').showModal();
  if(type==='chart'){detailMessage('Читаем сохранённую историю…');try{await loadChart(ctx);}catch(e){if(currentDetails(ctx))detailMessage(e.message);}}
}
function setupDetails(){
  document.addEventListener('click',e=>{const b=e.target.closest('[data-voc-action]');if(b)openVocabulary(Number(b.dataset.vocId),b.dataset.vocAction);});
  $('#details-close').onclick=()=>$('#details-dialog').close();
  $('#details-dialog').addEventListener('close',()=>{detailsContext=null;++detailsGeneration;});
  $('#details-form').onsubmit=async e=>{
    e.preventDefault();const ctx=detailsContext;if(!ctx||ctx.busy)return;
    if($('#details-from').value>$('#details-to').value){detailMessage('Дата начала не должна быть позже даты окончания.');return;}
    ctx.busy=true;$('#details-submit').disabled=true;$('#details-content').innerHTML='';detailMessage(ctx.type==='chart'?'Читаем сохранённую историю…':'Загружаем доступную историю и проверяем возможность анализа…');
    try{
      if(ctx.type==='chart')await loadChart(ctx);
      else{
        const data=await request('/api/errors',{voc_id:ctx.id,date_from:$('#details-from').value,date_to:$('#details-to').value,limit:Number($('#details-limit').value)});
        if(!currentDetails(ctx))return;
        detailMessage(data.message);
        $('#details-content').innerHTML=`<p class="hint">${fmtDate(data.period_from)} — ${fmtDate(data.period_to)} · Проанализировано заездов: ${data.processed} · Пропущено: ${data.skipped} · Всего: ${data.total??'неизвестно'} · ${data.analysis_complete?'Полный анализ':'Полнота не подтверждена'}</p>`+(data.words.length?'<div class="table-wrap"><table><thead><tr><th>Слово</th><th>Вхождений с ошибкой</th></tr></thead><tbody>'+data.words.map(w=>`<tr><td>${esc(w.word)}</td><td>${w.count}</td></tr>`).join('')+'</tbody></table></div>':'');
      }
    }catch(e){if(currentDetails(ctx))detailMessage(e.message);}
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
