'use strict';
let editorKind='goal',editorItems=new Map(),editingGoal=null,goalDeleteConfirm=false,tableMode=null,tableGoal=null;
const goalStatusLabels={done:'Достигнуто',pending:'Не достигнуто',empty:'Нет заездов',unloaded:'Не загружено',partial:'Данные неполные',unverifiable:'Не удалось проверить',unconfigured:'Не настроено',future:'Период не начался'};
const rollingLabels={day:'День',week:'Неделя',month:'Месяц',quarter:'Три месяца',half:'Полгода',year:'Год'};
const goalColumns=[['name','Словарь'],['speed','Требование'],['month_races','Заездов'],['record','Рекорд'],['record_date','Дата личного рекорда'],['achievement_speed','Достижение'],['status_label','Статус'],['actions','Действия']];
let hiddenGoalColumns=new Set(['record_date']);
try{const saved=JSON.parse(localStorage.getItem('klavo-goal-hidden-columns'));if(Array.isArray(saved))hiddenGoalColumns=new Set(saved.filter(k=>k!=='name'&&goalColumns.some(([key])=>key===k)));}catch(exc){}
function visibleGoalColumns(){return goalColumns.filter(([key])=>!hiddenGoalColumns.has(key));}
function renderGoalColumns(refreshOptions=true){
  $('#table-head').innerHTML='<tr>'+visibleGoalColumns().map(([key,label])=>key==='actions'?'<th scope="col" class="actions-heading">Действия</th>':`<th scope="col"><button data-sort="${key}">${label} <span>↕</span></button></th>`).join('')+'</tr>';
  if(refreshOptions)$('#column-options').innerHTML=goalColumns.map(([key,label])=>`<label><input type="checkbox" data-goal-column="${key}" ${hiddenGoalColumns.has(key)?'':'checked'} ${key==='name'?'disabled':''}>${label}</label>`).join('');
}
function setGoalColumn(key,visible){
  if(key==='name'||!goalColumns.some(([k])=>k===key))return;
  if(visible)hiddenGoalColumns.delete(key);else hiddenGoalColumns.add(key);
  if(hiddenGoalColumns.has(state.sort))state.sort=null;
  try{localStorage.setItem('klavo-goal-hidden-columns',JSON.stringify([...hiddenGoalColumns]));}catch(exc){}
  renderGoalColumns(false);renderGoalTable();
}
function achievementStatus(r){
  if(r.status!=='done'||r.achievement_count==null)return r.status_label;
  const n=r.achievement_count,last=n%10,hundred=n%100;
  return `Достигнуто ${n} ${last>=2&&last<=4&&(hundred<12||hundred>14)?'раза':'раз'}`;
}
function showSection(section){
  state.section=section;$('#dashboard-view').hidden=section!=='dashboard';$('#settings-view').hidden=section!=='settings';
  $('#nav-dashboard').classList.toggle('active',section==='dashboard');$('#nav-settings').classList.toggle('active',section==='settings');
  $('#add-group').hidden=section!=='settings'||state.settingsTab!=='groups';
  if(section==='settings')renderSettings();
}
function configureTable(){
  const mode=state.goalData?'goal':'group';
  $('#achieved-section').hidden=mode!=='goal';
  $('#column-settings').hidden=mode!=='goal';
  if(tableMode===mode){if(mode==='goal'&&tableGoal!==state.goal){$('#filter').value='all';state.page=0;state.sort=null;tableGoal=state.goal;}return;}tableMode=mode;tableGoal=state.goal;state.sort=null;state.page=0;
  const columns=mode==='goal'?goalColumns:[['name','Словарь'],['record','Рекорд'],['record_date','Дата рекорда'],['month_max','Максимум за месяц'],['month_date','Дата за месяц'],['actions','Действия']];
  $('#table-head').innerHTML='<tr>'+columns.map(([key,label])=>key==='actions'?'<th scope="col" class="actions-heading">Действия</th>':`<th scope="col"><button data-sort="${key}">${label} <span>↕</span></button></th>`).join('')+'</tr>';
  if(mode==='goal')renderGoalColumns();
  $('#filter').innerHTML=mode==='goal'?'<option value="all">Все статусы</option>'+Object.entries(goalStatusLabels).map(([k,v])=>`<option value="${k}">${v}</option>`).join(''):'<option value="played">С результатами</option><option value="all">Все словари</option><option value="active">С заездами за месяц</option><option value="unplayed">Без результатов</option>';
  $('#table-title').textContent=mode==='goal'?'Выполнение цели (по словарям)':'Результаты по словарям';
  $('#legend').textContent=mode==='goal'?'Светло-зелёным выделены достигнутые требования. Скорость и ошибки проверяются по одному заезду.':'Зелёным выделен максимум за месяц. Метка «Рекорд» — рекорд установлен в периоде.';
  $('#calculation-help').hidden=mode==='goal';
  $('#empty p').textContent=mode==='goal'?'Измените фильтр или настройте состав цели.':'Измените фильтр или добавьте словари в свою группу.';
  document.querySelectorAll('.card-label').forEach((el,i)=>el.textContent=(mode==='goal'?['В цели','Достигнуто','Заездов за период','Требуют внимания']:['В подборке','Есть результаты','Активность за месяц','Практика за месяц'])[i]);
  document.querySelectorAll('.card>span:last-child').forEach((el,i)=>el.textContent=(mode==='goal'?['словарей всего','словарей выполнено','по загруженным данным','неполные данные / настройка']:['словарей','словарей с рекордом','словарей в работе','завершённых заездов'])[i]);
}
function renderGoalHeader(){
  const d=state.goalData;$('#group-title').textContent=d.goal.name;document.title=d.goal.name+' · KlavoPersonalStat';
  const phase={future:'Ещё не начался',active:'Идёт',finished:'Завершён'}[d.phase];
  $('#group-subtitle').textContent=`${fmtDate(d.period_from)} — ${fmtDate(d.period_to)} · ${phase}`;
  $('#edit-group').hidden=true;$('#refresh').title='Обновить результаты с Клавогонок';$('#edit-current-goal').hidden=false;
  $('#export').href=profileUrl('/api/export?goal='+d.goal.id);
  $('#count-total').textContent=d.rows.length;$('#count-played').textContent=d.counts.done;$('#count-active').textContent=d.rows.reduce((sum,r)=>sum+r.month_races,0).toLocaleString('ru');
  $('#count-races').textContent=d.rows.filter(r=>['unconfigured','partial','unverifiable','unloaded'].includes(r.status)).length;
  $('#goal-progress').hidden=false;$('#goal-progress-bar').value=d.percent;
  $('#goal-summary').innerHTML=`<strong>${d.counts.done} из ${d.rows.length} · ${d.percent}% выполнено</strong><small>Нет заездов: ${d.counts.empty} · Не загружено: ${d.counts.unloaded} · Неполные данные: ${d.counts.partial} · Не удалось проверить: ${d.counts.unverifiable} · Не настроено: ${d.counts.unconfigured}</small>`;
  const dates=d.rows.map(r=>r.fetched_at).filter(Boolean).sort();
  $('#freshness').textContent=dates.length?'По данным на '+new Date(dates[0]).toLocaleString('ru',{timeZone:'Europe/Moscow'}):'История за период ещё не загружена.';
  if(d.phase==='future')$('#freshness').textContent='Период начнётся '+fmtDate(d.period_from)+'. Будущие заезды не запрашиваются.';
}
function goalResultDate(value){
  if(!value)return '—';
  if(value.length===10)return fmtDate(value);
  return new Date(value).toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'});
}
function goalRaceCount(r){
  if(r.month_races==null||r.status==='future')return null;
  return r.complete||r.month_races>0||r.fetched_at?r.month_races:null;
}
function goalRow(r){
  const races=goalRaceCount(r);
  const racesCell=races==null?'—':races.toLocaleString('ru');

  const complete=r.period_complete??r.complete;
  const achievement=r.achievement_speed==null?'—':`<b>${r.achievement_speed} зн/мин</b><small>${goalResultDate(r.achievement_at)} · ${r.achievement_errors==null?'Ошибки неизвестны':r.achievement_errors+' ош.'}</small>${r.achievement_source==='daily'?'<small>Дневной максимум</small>':''}${!complete?'<small>Лучший среди загруженных данных</small>':''}`;
  const record=r.record_in_period?'<span class="goal-record-badge tooltip" tabindex="0" aria-label="Личный рекорд в периоде" data-tooltip="Личный рекорд в периоде">★</span>':'';
  const countHint=r.status==='done'&&r.achievement_count!=null&&!r.achievement_count_complete?'Количество по доступной истории':'';
  const reason=r.status==='done'?'':r.reason;
  const cells={
    name:`<a href="${trainingUrl(r.id)}" title="${esc(r.name)}" target="_blank" rel="noopener">${esc(displayName(r))}</a><small>№${r.id}</small>`,
    speed:`<b>${r.speed==null?'—':r.speed+' зн/мин'}</b><small>${r.mode==='errors'?'Ошибок ≤ '+(r.max_errors??'—'):'Только скорость'}</small>`,
    month_races:racesCell,
    record:r.record==null?'—':`<b>${r.record} зн/мин</b>`,
    record_date:goalResultDate(r.record_date),
    achievement_speed:achievement+record,
    status_label:`<span class="status-badge status-${r.status} ${countHint?'tooltip':''}" ${countHint?`tabindex="0" data-tooltip="${countHint}" aria-label="${esc(achievementStatus(r))}. ${countHint}"`:''}>${esc(achievementStatus(r))}</span>${reason?`<small class="status-reason">${esc(reason)}</small>`:''}`,
    actions:rowActions(r)
  };
  const classes={month_races:'number race-count',record:'number',achievement_speed:'number achievement-value'};
  return `<tr class="${r.status==='done'?'achieved':''}">`+visibleGoalColumns().map(([key])=>`<td${classes[key]?` class="${classes[key]}"`:''}>${cells[key]}</td>`).join('')+'</tr>';

}
function renderAchievedTable(){
  const rows=state.goalData.rows.filter(r=>r.status==='done');
  $('#achieved-count').textContent=rows.length;
  $('#achieved-head').innerHTML='<tr>'+visibleGoalColumns().map(([,label])=>`<th scope="col">${label}</th>`).join('')+'</tr>';
  $('#achieved-rows').innerHTML=rows.map(goalRow).join('');
  $('#achieved-empty').hidden=!!rows.length;
  $('#achieved-table').hidden=!rows.length;
}
function renderGoalTable(){
  if(vocabularyMenuTarget)closeVocabularyMenu();
  const d=state.goalData,q=$('#search').value.trim().toLocaleLowerCase('ru'),f=$('#filter').value;
  const rows=d.rows.filter(r=>matchesVocabulary(r,q)&&(f==='all'||r.status===f));
  if(state.sort)rows.sort((a,b)=>{const x=state.sort==='name'?displayName(a):state.sort==='month_races'?goalRaceCount(a):a[state.sort],y=state.sort==='name'?displayName(b):state.sort==='month_races'?goalRaceCount(b):b[state.sort];if(x==null)return y==null?0:1;if(y==null)return -1;return state.direction*(typeof x==='number'?x-y:String(x).localeCompare(String(y),'ru'));});
  state.page=Math.min(state.page,Math.max(0,Math.ceil(rows.length/state.pageSize)-1));const from=state.page*state.pageSize;
  $('#rows').innerHTML=rows.slice(from,from+state.pageSize).map(goalRow).join('');
  renderAchievedTable();
  $('#empty').hidden=!!rows.length;$('#shown-count').textContent=rows.length;$('#page-info').textContent=rows.length?`${from+1}–${Math.min(from+state.pageSize,rows.length)} из ${rows.length} словарей`:'0 словарей';
  $('#prev').disabled=!state.page;$('#next').disabled=from+state.pageSize>=rows.length;
  document.querySelectorAll('th').forEach(th=>th.removeAttribute('aria-sort'));
  if(state.sort)document.querySelector(`[data-sort="${state.sort}"]`)?.parentElement.setAttribute('aria-sort',state.direction===1?'ascending':'descending');
}
function renderSettings(){
  if(!state.catalog)return;
  $('#settings-goals').className='button '+(state.settingsTab==='goals'?'primary':'secondary');$('#settings-groups').className='button '+(state.settingsTab==='groups'?'primary':'secondary');
  $('#add-group').hidden=state.section!=='settings'||state.settingsTab!=='groups';
  $('#settings-templates').className='button '+(state.settingsTab==='templates'?'primary':'secondary');
  $('#settings-vocabulary').className='button '+(state.settingsTab==='vocabulary'?'primary':'secondary');
  if(state.settingsTab==='templates'){renderTemplates();return;}
  if(state.settingsTab==='vocabulary'){renderVocabularySettings();return;}
  if(state.settingsTab==='goals'){
    $('#settings-content').innerHTML='<div class="settings-heading"><h2>Текущие цели</h2><button class="button primary" id="new-goal">＋ Создать цель</button><button class="button secondary" id="from-template">Из шаблона</button></div>'+(state.catalog.goals.length?state.catalog.goals.map(g=>`<article class="settings-card"><div><h3>${esc(g.name)}</h3><p>${g.total} словарей · ${g.done??0} достигнуто · ${g.percent??0}% · ${g.period_type==='rolling'?rollingLabels[g.rolling]:fmtDate(g.date_from)+' — '+fmtDate(g.date_to)}</p></div><div class="card-actions"><button class="button secondary" data-show-goal="${g.id}">Открыть</button><button class="button secondary" data-edit-goal="${g.id}">Изменить</button><button class="button secondary" data-save-template="${g.id}">Сохранить как шаблон</button></div></article>`).join(''):'<div class="empty"><strong>Задайте первую цель</strong><p>Выберите словари, период и результаты, к которым стремитесь.</p></div>');
  }else{
    $('#settings-content').innerHTML='<div class="settings-heading"><h2>Группы словарей</h2><button class="button primary" id="new-settings-group">＋ Добавить группу</button></div>'+state.data.groups.map(g=>`<article class="settings-card"><div><h3>${esc(g.name)}</h3><p>${g.total} словарей · ${g.builtin?'Встроенная группа':'Своя группа'}${g.source_url?` · <a href="${esc(g.source_url)}" target="_blank" rel="noopener">Источник ↗</a>`:''}</p></div>${!g.builtin?`<button class="button secondary" data-edit-settings-group="${g.id}">Изменить</button>`:''}</article>`).join('');
  }
}
function goalError(message){$('#goal-form-error').textContent=message;$('#goal-form-error').hidden=!message;}
function updatePeriodFields(){const fixed=$('#period-type').value==='fixed';$('#rolling-field').hidden=fixed;$('#from-field').hidden=!fixed;$('#to-field').hidden=!fixed;$('#goal-from').required=fixed&&editorKind==='goal';$('#goal-to').required=fixed&&editorKind==='goal';$('#from-field').hidden=!fixed||editorKind==='template';$('#to-field').hidden=!fixed||editorKind==='template';}
function drawEditorItems(){
  const known=new Map(state.catalog.vocs.map(v=>[v.id,displayName(v)]));
  $('#goal-items').innerHTML=[...editorItems.values()].map(r=>`<tr data-id="${r.id}"><td>${esc(known.get(r.id)||'Словарь '+r.id)}<small>№${r.id}</small></td><td><select data-field="mode" aria-label="Режим словаря ${r.id}"><option value="speed" ${r.mode==='speed'?'selected':''}>Только скорость</option><option value="errors" ${r.mode==='errors'?'selected':''}>Скорость и ошибки</option></select></td><td><input data-field="speed" aria-label="Скорость словаря ${r.id}" type="number" min="0.01" step="any" value="${esc(r.speed??'')}" placeholder="Не задана"></td><td><input data-field="max_errors" aria-label="Допуск ошибок словаря ${r.id}" type="number" min="0" step="1" value="${esc(r.max_errors??'')}" ${r.mode==='speed'?'disabled':''} placeholder="Не задан"></td><td><button type="button" class="icon-button" data-remove-voc="${r.id}" aria-label="Убрать словарь ${r.id}">×</button></td></tr>`).join('');
  $('#goal-item-count').textContent='Словарей в цели: '+editorItems.size;
}
function addEditorIds(ids){ids.forEach(id=>{if(!editorItems.has(id))editorItems.set(id,{id,mode:'speed',speed:null,max_errors:null});});drawEditorItems();goalError('');}
function renderTemplates(){
  $('#settings-content').innerHTML='<div class="settings-heading"><h2>Шаблоны целей</h2><button class="button primary" id="new-template">＋ Создать шаблон</button></div>'+(state.catalog.templates?.length?state.catalog.templates.map(t=>`<article class="settings-card"><div><h3>${esc(t.name)}</h3><p>${t.total} словарей · ${t.period_type==='rolling'?rollingLabels[t.rolling]:'Фиксированные даты при создании цели'}</p></div><div class="card-actions"><button class="button primary" data-use-template="${t.id}">Создать цель</button><button class="button secondary" data-edit-template="${t.id}">Изменить</button></div></article>`).join(''):'<div class="empty"><strong>Шаблонов пока нет</strong><p>Создайте шаблон или сохраните настройки существующей цели как шаблон.</p></div>');
}
async function openGoal(identifier=null,kind='goal',source=null){
  try{
    editorKind=kind;editingGoal=identifier;editorItems=new Map();goalDeleteConfirm=false;$('#goal-form').reset();goalError('');$('#goal-delete-hint').hidden=true;
    $('#goal-dialog-title').textContent=identifier?(kind==='template'?'Изменить шаблон':'Изменить цель'):(kind==='template'?'Новый шаблон':'Новая цель');$('#goal-delete').hidden=!identifier;$('#goal-delete').textContent=kind==='template'?'Удалить шаблон':'Удалить цель';$('#goal-save').textContent=kind==='template'?'Сохранить шаблон':'Сохранить цель';
    $('#goal-delete-hint').textContent='Нажмите кнопку удаления ещё раз для подтверждения. Остальные цели, словари и статистика сохранятся.';
    $('#goal-add-group').innerHTML=state.data.groups.map(g=>`<option value="${g.id}">${esc(g.name)} (${g.total})</option>`).join('');$('#goal-catalog-results').innerHTML='';
    if(identifier||source){
      const route=source?.type||(kind==='template'?'template':'goal'),id=source?.id||identifier;
      const d=await request('/api/'+route+'?id='+id),g=d.goal||d,items=d.rows||d.items;
      $('#goal-name').value=g.name;$('#period-type').value=g.period_type;$('#goal-rolling').value=g.rolling||'month';$('#goal-from').value=source?.type==='template'?'':g.date_from||'';$('#goal-to').value=source?.type==='template'?'':g.date_to||'';
      items.forEach(r=>editorItems.set(r.id,{id:r.id,mode:r.mode,speed:r.speed,max_errors:r.max_errors}));
    }
    $('#bulk-errors').disabled=true;updatePeriodFields();drawEditorItems();$('#goal-dialog').showModal();$('#goal-name').focus();
  }catch(exc){error(exc.message);}
}

function setupGoals(){
  $('#column-options').addEventListener('change',e=>{if(e.target.dataset.goalColumn)setGoalColumn(e.target.dataset.goalColumn,e.target.checked);});
  $('#nav-dashboard').onclick=()=>showSection('dashboard');$('#nav-settings').onclick=()=>showSection('settings');
  $('#edit-current-goal').onclick=()=>openGoal(Number(state.goal));
  $('#settings-templates').onclick=()=>{state.settingsTab='templates';renderSettings();};
  $('#settings-goals').onclick=()=>{state.settingsTab='goals';renderSettings();};$('#settings-groups').onclick=()=>{state.settingsTab='groups';renderSettings();};
  $('#settings-vocabulary').onclick=()=>{state.settingsTab='vocabulary';renderSettings();};
  $('#settings-content').addEventListener('input',event=>{
    if(event.target.id==='vocabulary-search'){labelState.search=event.target.value;labelState.page=0;renderVocabularyList();}
    if(event.target.dataset.aliasInput)labelState.drafts.set(Number(event.target.dataset.aliasInput),event.target.value);
  });
  $('#settings-content').onclick=async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.aliasSave)return saveVocabulary(Number(b.dataset.aliasSave),false);
    if(b.dataset.aliasClear)return saveVocabulary(Number(b.dataset.aliasClear),true);
    if(b.id==='vocabulary-prev'){labelState.page--;return renderVocabularyList();}
    if(b.id==='vocabulary-next'){labelState.page++;return renderVocabularyList();}
    if(b.id==='new-template')return openGoal(null,'template');
    if(b.id==='from-template'){state.settingsTab='templates';return renderSettings();}
    if(b.dataset.editTemplate)return openGoal(Number(b.dataset.editTemplate),'template');
    if(b.dataset.useTemplate)return openGoal(null,'goal',{type:'template',id:Number(b.dataset.useTemplate)});
    if(b.dataset.saveTemplate)return openGoal(null,'template',{type:'goal',id:Number(b.dataset.saveTemplate)});
    if(b.id==='new-goal')return openGoal();if(b.id==='new-settings-group')return openGroup(false);
    if(b.dataset.editGoal)return openGoal(Number(b.dataset.editGoal));
    if(b.dataset.showGoal)await navigateGoal(b.dataset.showGoal);
    if(b.dataset.editSettingsGroup){try{state.group=b.dataset.editSettingsGroup;await loadData();openGroup(true);}catch(exc){error(exc.message);}}
  };
  $('#goal-close').onclick=$('#goal-cancel').onclick=()=>$('#goal-dialog').close();$('#period-type').onchange=updatePeriodFields;
  $('#bulk-mode').onchange=()=>$('#bulk-errors').disabled=$('#bulk-mode').value==='speed';
  $('#goal-copy-group').onclick=()=>addEditorIds(state.catalog.members.filter(m=>String(m.group_id)===$('#goal-add-group').value).map(m=>m.voc_id));
  $('#goal-add-manual').onclick=()=>{
    const tokens=$('#goal-add-vocs').value.trim().split(/[\s,;]+/).filter(Boolean),ids=[];
    for(const token of tokens){let match=token.match(/^\d{1,9}$/)||token.match(/^https?:\/\/klavogonki\.ru\/vocs\/(\d+)(?:\/|$)/);let id=match?Number(match[1]||match[0]):0;if(!Number.isSafeInteger(id)||id<=0)return goalError('Укажите номера или ссылки на словари klavogonki.ru.');ids.push(id);}
    addEditorIds(ids);$('#goal-add-vocs').value='';
  };
  $('#goal-catalog-search').oninput=()=>{const q=$('#goal-catalog-search').value.trim().toLowerCase();$('#goal-catalog-results').innerHTML=q?state.catalog.vocs.filter(v=>matchesVocabulary(v,q)).slice(0,15).map(v=>`<button type="button" class="catalog-result" data-add-voc="${v.id}" title="${esc(v.name)}">${esc(displayName(v))} <small>№${v.id} · ${editorItems.has(v.id)?'Добавлен':'＋'}</small></button>`).join(''):'';};
  $('#goal-catalog-results').onclick=e=>{const b=e.target.closest('[data-add-voc]');if(b){addEditorIds([Number(b.dataset.addVoc)]);$('#goal-catalog-search').oninput();}};
  $('#goal-items').oninput=e=>{const row=e.target.closest('tr'),field=e.target.dataset.field;if(!row||!field)return;const item=editorItems.get(Number(row.dataset.id));item[field]=e.target.value===''?null:e.target.value;};
  $('#goal-items').onchange=e=>{if(e.target.dataset.field==='mode')drawEditorItems();};
  $('#goal-items').onclick=e=>{const b=e.target.closest('[data-remove-voc]');if(b){editorItems.delete(Number(b.dataset.removeVoc));drawEditorItems();}};
  $('#goal-apply').onclick=()=>{const speed=$('#bulk-speed').value,errors=$('#bulk-errors').value,mode=$('#bulk-mode').value;if(!(Number(speed)>0)||!Number.isFinite(Number(speed)))return goalError('Укажите положительную общую скорость.');if(mode==='errors'&&(errors===''||!Number.isInteger(Number(errors))||Number(errors)<0))return goalError('Укажите целый допуск ошибок от нуля.');editorItems.forEach(r=>{r.mode=mode;r.speed=Number(speed);if(mode==='errors')r.max_errors=Number(errors);});goalError('');drawEditorItems();};
  $('#goal-form').onsubmit=async e=>{
    e.preventDefault();$('#goal-save').disabled=true;goalError('');
    try{const result=await request(editorKind==='template'?'/api/templates/save':'/api/goals/save',{id:editingGoal,name:$('#goal-name').value,period_type:$('#period-type').value,rolling:$('#goal-rolling').value,date_from:$('#goal-from').value,date_to:$('#goal-to').value,items:[...editorItems.values()]});if(editorKind==='template'){state.settingsTab='templates';await loadData();$('#goal-dialog').close();showSection('settings');toast('Шаблон сохранён.');return;}state.goal=String(result.id);localStorage.setItem('klavo-goal',state.goal);state.page=0;await loadData();$('#goal-dialog').close();showSection('dashboard');toast('Цель сохранена. Оценка пересчитана по сохранённым данным.');}
    catch(exc){goalError(exc.message);}finally{$('#goal-save').disabled=false;}
  };
  $('#goal-delete').onclick=async()=>{if(!goalDeleteConfirm){goalDeleteConfirm=true;$('#goal-delete-hint').hidden=false;return;}try{await request(editorKind==='template'?'/api/templates/delete':'/api/goals/delete',{id:editingGoal});if(editorKind==='goal'&&String(editingGoal)===state.goal){state.goal=null;localStorage.removeItem('klavo-goal');}await loadData();$('#goal-dialog').close();toast(editorKind==='template'?'Шаблон удалён. Цели и статистика сохранены.':'Цель удалена. Статистика сохранена.');}catch(exc){goalError(exc.message);}};
}

const labelState={search:'',page:0,drafts:new Map(),saving:new Set()};
function renderVocabularySettings(){
  $('#settings-content').innerHTML=`<div class="settings-heading"><h2>Краткие имена словарей</h2></div><p class="hint">Одно имя для словаря во всех группах и целях. Полное название с сайта сохраняется.</p><label class="field">Поиск словаря<input id="vocabulary-search" type="search" placeholder="Краткое имя, полное название или ID" value="${esc(labelState.search)}"></label><div id="vocabulary-list"></div>`;
  renderVocabularyList();
}
function renderVocabularyList(){
  const q=labelState.search.trim().toLocaleLowerCase('ru');
  const rows=state.catalog.vocs.filter(v=>matchesVocabulary(v,q)).sort((a,b)=>displayName(a).localeCompare(displayName(b),'ru'));
  labelState.page=Math.max(0,Math.min(labelState.page,Math.ceil(rows.length/40)-1));const from=labelState.page*40;
  $('#vocabulary-list').innerHTML=rows.slice(from,from+40).map(v=>{
    const value=labelState.drafts.has(v.id)?labelState.drafts.get(v.id):v.short_name||'';const busy=labelState.saving.has(v.id)?'disabled':'';
    return `<article class="settings-card vocabulary-card"><div class="vocabulary-name"><a href="https://klavogonki.ru/vocs/${v.id}/" target="_blank" rel="noopener">${esc(v.name)}</a><small>№${v.id}</small></div><label class="alias-label">Краткое имя<input aria-label="Краткое имя словаря ${v.id}" data-alias-input="${v.id}" value="${esc(value)}" placeholder="Полное название по умолчанию" ${busy}></label><div class="card-actions"><button class="button secondary" data-alias-save="${v.id}" ${busy}>Сохранить</button><button class="button secondary" data-alias-clear="${v.id}" ${busy}>Очистить</button></div></article>`;
  }).join('')+(rows.length?'':'<div class="empty">Словари не найдены</div>')+`<div class="table-footer"><span>${rows.length?`${from+1}–${Math.min(from+40,rows.length)} из ${rows.length}`:'0 словарей'}</span><div><button class="page-button" id="vocabulary-prev" aria-label="Предыдущие словари" ${!labelState.page?'disabled':''}>←</button><button class="page-button" id="vocabulary-next" aria-label="Следующие словари" ${from+40>=rows.length?'disabled':''}>→</button></div></div>`;
}
async function saveVocabulary(id,clear){
  const row=state.catalog.vocs.find(v=>v.id===id);
  const value=clear?'':labelState.drafts.has(id)?labelState.drafts.get(id):row.short_name||'';
  if([...value.trim()].length>100){error('Краткое имя должно содержать не более 100 символов.');return;}
  labelState.saving.add(id);renderVocabularyList();
  try{await request('/api/vocabulary/save',{id,short_name:value});labelState.drafts.delete(id);await loadData();toast(clear?'Краткое имя очищено. Используется полное название.':'Краткое имя сохранено.');}
  catch(exc){error(exc.message);}finally{labelState.saving.delete(id);if(state.settingsTab==='vocabulary')renderVocabularyList();}
}
