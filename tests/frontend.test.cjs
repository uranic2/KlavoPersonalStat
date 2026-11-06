// Exercise the actual application loader with controlled, out-of-order responses.
// Uses only Node's standard library; no browser globals are modified during UI QA.
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

function fixture(render=false){
  const nodes=new Map(),storage=new Map();
  const node=key=>{if(!nodes.has(key))nodes.set(key,{hidden:false,value:'',textContent:'',handlers:{},classList:{toggle(){}},setAttribute(){},removeAttribute(){},parentElement:{setAttribute(){}},addEventListener(name,fn){this.handlers[name]=fn;}});return nodes.get(key);};
  const ctx=vm.createContext({URL,URLSearchParams,Intl,Date,setTimeout,clearTimeout,document:{documentElement:{dataset:{}},querySelector:node,querySelectorAll:()=>[]},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},window:{}});
  const run=s=>vm.runInContext(s,ctx);
  for(const file of ['goals-ui.js','details-ui.js','app.js']){
    let code=fs.readFileSync(path.join(__dirname,'../static',file),'utf8');
    if(file==='app.js')code=code.replace(/\ninit\(\);\s*$/,'\n');
    run(code);
  }
  if(!render)run(`configureTable=()=>{};renderTable=()=>{};`);
  run(`renderNavigation=()=>{};renderSettings=()=>{};renderHeader=()=>{window.displayed=state.goalData?.goal.name||'group';};request=url=>mockRequest(url);`);
  const snapshot=()=>JSON.parse(run(`JSON.stringify({goal:state.goal,group:state.group,goalData:state.goalData,token:state.token,displayed:window.displayed,loading:state.viewLoading})`));
  return {ctx,run,node,storage,snapshot};
}
function payload(url,id){
  if(url.startsWith('/api/data'))return {token:'token-'+id,groups:[],rows:[]};
  if(url==='/api/catalog')return {goals:[],vocs:[],members:[]};
  return {goal:{id,name:'goal-'+id},rows:[{id}]};
}
function defer(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}

test('navigation: late responses cannot overwrite a newer goal or token',async()=>{
  const f=fixture(),calls=[];f.ctx.mockRequest=url=>{const d=defer();calls.push({url,...d});return d.promise;};
  f.run("state.goal='1'");const old=f.run('loadData()');
  f.run("state.goal='3'");const current=f.run('loadData()');
  calls.slice(3).forEach(c=>c.resolve(payload(c.url,3)));await current;
  calls.slice(0,3).forEach(c=>c.resolve(payload(c.url,1)));await old;
  assert.equal(f.snapshot().goalData.goal.id,3);assert.equal(f.snapshot().displayed,'goal-3');assert.equal(f.snapshot().token,'token-3');assert.equal(f.snapshot().loading,false);
});

test('navigation: late failure does not replace the latest successful screen',async()=>{
  const f=fixture(),calls=[];f.ctx.mockRequest=url=>{const d=defer();calls.push({url,...d});return d.promise;};
  f.run("state.goal='1'");const old=f.run('loadData()');
  f.run("state.goal='3'");const current=f.run('loadData()');
  calls.slice(3).forEach(c=>c.resolve(payload(c.url,3)));await current;
  calls[0].reject(new Error('old request failed'));calls.slice(1,3).forEach(c=>c.resolve(payload(c.url,1)));await old;
  assert.equal(f.snapshot().displayed,'goal-3');assert.equal(f.node('#error-box').hidden,true);
});

test('navigation: loading failure keeps the previous coherent selection and shows an error',async()=>{
  const f=fixture();f.ctx.mockRequest=async url=>payload(url,1);f.run("state.goal='1'");await f.run('loadData()');
  f.ctx.mockRequest=async()=>{throw new Error('offline');};f.run("state.goal='3'");await assert.rejects(f.run('loadData()'),/offline/);
  assert.equal(f.snapshot().goal,'1');assert.equal(f.snapshot().goalData.goal.id,1);assert.match(f.node('#error-box').textContent,/offline/);assert.equal(f.snapshot().loading,false);
});

test('navigation: real sidebar handler selects a goal from settings and stores it',async()=>{
  const f=fixture();f.ctx.mockRequest=async url=>payload(url,3);f.run("state.section='settings'");
  await f.node('#groups').handlers.click({target:{closest:selector=>selector==='[data-goal]'?{dataset:{goal:'3'}}:null}});
  assert.equal(f.run('state.section'),'dashboard');assert.equal(f.snapshot().displayed,'goal-3');assert.equal(f.storage.get('klavo-goal'),'3');
});

test('training link carries the exact requested parameters and encoded submit value',()=>{
  const f=fixture(),href=f.run('trainingUrl(853)'),url=new URL(href);
  assert.equal(url.origin,'https://klavogonki.ru');assert.equal(url.pathname,'/create/');
  assert.deepEqual(Object.fromEntries(url.searchParams),{gametype:'voc',voc:'853',type:'practice',level_from:'1',level_to:'8',timeout:'5',submit:'Начать'});
  assert.ok(!href.includes('Начать'));assert.ok(!url.searchParams.get('submit').endsWith('/'));
});

test('short names fall back to the original and remain searchable and escaped',()=>{
  const f=fixture();assert.equal(f.run(`displayName({id:1,name:'Original',short_name:'Краткое'})`),'Краткое');assert.equal(f.run(`displayName({name:'Original',short_name:''})`),'Original');
  for(const q of ['original','краткое','853'])assert.equal(f.run(`matchesVocabulary({id:853,name:'Original',short_name:'Краткое'},${JSON.stringify(q)})`),true);
  assert.equal(f.run(`esc('<img src=x onerror="test">')`),'&lt;img src=x onerror=&quot;test&quot;&gt;');
});

test('goal tables share rows while achieved list ignores filters and pagination',()=>{
  const f=fixture(true);
  f.run(`state.data={rows:[]};state.goal='1';state.goalData={rows:[
    {id:1,name:'Full',short_name:'<Alias>',mode:'speed',speed:400,status:'done',status_label:'Достигнуто',record:900,record_date:'2026-10-01',achievement_speed:450,achievement_at:'2026-11-02',achievement_errors:null,achievement_source:'daily',complete:false},
    {id:2,name:'Pending',mode:'speed',speed:500,status:'pending',status_label:'Не достигнуто',record:null,achievement_speed:null},
    {id:3,name:'Second',mode:'errors',speed:400,max_errors:0,status:'done',status_label:'Достигнуто',record:500,achievement_speed:400,achievement_at:'2026-11-02T23:30:00Z',achievement_errors:0,achievement_source:'race',complete:true}
  ]};configureTable();state.pageSize=1;`);
  f.node('#filter').value='all';f.run('renderTable()');
  const main=f.node('#rows').innerHTML,done=f.node('#achieved-rows').innerHTML;
  assert.equal((f.node('#table-head').innerHTML.match(/<th /g)||[]).length,7);
  assert.doesNotMatch(f.node('#table-head').innerHTML,/month_max|best_speed|best_at/);
  assert.ok(done.includes(main));assert.equal(f.node('#achieved-count').textContent,2);
  assert.match(main,/900 зн\/мин/);assert.doesNotMatch(main,/01\.10\.2026/);assert.match(main,/Ошибки неизвестны/);assert.match(main,/Дневной максимум/);assert.match(main,/Лучший среди загруженных данных/);
  assert.match(main,/&lt;Alias&gt;/);assert.match(main,/title="Full"/);assert.match(main,/target="_blank" rel="noopener"/);
  assert.match(done,/03\.11\.2026 · 0 ош\./); // Moscow date crosses midnight.
  f.node('#search').value='Pending';f.node('#filter').value='pending';f.run('renderTable()');
  assert.match(f.node('#rows').innerHTML,/Pending/);assert.equal(f.node('#achieved-rows').innerHTML,done);
  f.run(`state.goal='2';state.goalData={rows:[]};configureTable();renderTable();`);
  assert.equal(f.node('#achieved-count').textContent,0);assert.equal(f.node('#achieved-empty').hidden,false);assert.equal(f.node('#achieved-table').hidden,true);
  f.run('state.goalData=null;configureTable();');assert.equal(f.node('#achieved-section').hidden,true);
});

test('goal numeric sorting keeps missing records and achievements last in both directions',()=>{
  const f=fixture(true);f.node('#filter').value='all';
  f.run(`state.data={};state.goalData={rows:[
    {id:1,name:'Missing',mode:'speed',record:null,achievement_speed:null},
    {id:2,name:'Low',mode:'speed',record:99,achievement_speed:99},
    {id:3,name:'High',mode:'speed',record:1000,achievement_speed:1000}
  ]};`);
  for(const key of ['record','achievement_speed'])for(const direction of [1,-1]){
    f.run(`state.sort='${key}';state.direction=${direction};renderTable();`);
    const ids=[...f.node('#rows').innerHTML.matchAll(/<small>№(\d+)<\/small>/g)].map(m=>Number(m[1]));
    assert.deepEqual(ids,direction===1?[2,3,1]:[3,2,1]);
  }
});

test('closed dictionary dialog ignores late chart responses',async()=>{
  const f=fixture(),d=defer();f.ctx.mockRequest=()=>d.promise;
  f.node('#details-dialog').open=true;f.node('#details-content').innerHTML='unchanged';
  f.run(`detailsContext={id:812,type:'chart',profile:null,generation:0,request:0};`);
  const pending=f.run('loadChart(detailsContext)');f.run('detailsContext=null;++detailsGeneration;');
  d.resolve({rows:[]});await pending;assert.equal(f.node('#details-content').innerHTML,'unchanged');
});

test('chart gaps stay disconnected and single points remain visible',()=>{
  const f=fixture();const svg=f.run(`chartSVG([{day:'2026-11-01',max_speed:400},{day:'2026-11-02',max_speed:null},{day:'2026-11-03',max_speed:500}],['max_speed'],450)`);
  assert.match(svg,/d="M[^L]*M/);assert.equal((svg.match(/<circle /g)||[]).length,2);assert.match(svg,/Требование: 450/);
});

test('fixed template hides mandatory dates until an independent goal is created',()=>{
  const f=fixture();f.node('#period-type').value='fixed';
  f.run(`editorKind='template';updatePeriodFields();`);assert.equal(f.node('#goal-from').required,false);assert.equal(f.node('#from-field').hidden,true);
  f.run(`editorKind='goal';updatePeriodFields();`);assert.equal(f.node('#goal-from').required,true);assert.equal(f.node('#from-field').hidden,false);
});

test('theme selection applies immediately and saves a supported preference',()=>{
  const f=fixture();assert.equal(f.run('document.documentElement.dataset.theme'),'dark');
  f.run('setupTheme()');f.node('#theme-select').value='light';f.node('#theme-select').onchange();
  assert.equal(f.run('document.documentElement.dataset.theme'),'light');assert.equal(f.storage.get('klavo-theme'),'light');
  f.node('#theme-select').value='dark';f.node('#theme-select').onchange();
  assert.equal(f.run('document.documentElement.dataset.theme'),'dark');assert.equal(f.storage.get('klavo-theme'),'dark');
});

test('race column distinguishes confirmed zero, partial counts and missing history',()=>{
  const f=fixture();
  assert.equal(f.run('goalRaceCount({month_races:0,complete:true})'),0);
  assert.equal(f.run('goalRaceCount({month_races:0,complete:false})'),null);
  assert.equal(f.run('goalRaceCount({month_races:26,complete:false})'),26);
  const row=f.run(`goalRow({id:1,name:'Test',status:'partial',status_label:'Данные неполные',mode:'speed',month_races:26,complete:false})`);
  assert.match(row,/<td class="number race-count">26<\/td>/);
  assert.equal((row.match(/<td[ >]/g)||[]).length,7);
});

test('column preferences apply to both tables and reset hidden sorting',()=>{
  const f=fixture(true);f.run(`state.goalData={rows:[{id:1,name:'Test',status:'done',status_label:'Достигнуто',record_date:'2026-10-01'}]};state.data={};`);f.node('#filter').value='all';
  f.run(`setGoalColumn('record_date',true)`);
  assert.match(f.node('#rows').innerHTML,/01\.10\.2026/);assert.match(f.node('#achieved-rows').innerHTML,/01\.10\.2026/);
  assert.equal((f.node('#table-head').innerHTML.match(/<th /g)||[]).length,8);
  f.run(`state.sort='record_date';setGoalColumn('record_date',false);setGoalColumn('name',false)`);
  assert.equal(f.run('state.sort'),null);assert.equal(f.storage.get('klavo-goal-hidden-columns'),'["record_date"]');
  assert.equal(f.run(`visibleGoalColumns().some(([key])=>key==='name')`),true);
  assert.doesNotMatch(f.node('#rows').innerHTML,/01\.10\.2026/);
  f.run(`setGoalColumn('actions',false)`);assert.doesNotMatch(f.node('#achieved-rows').innerHTML,/row-actions/);
});
test('status counts decline correctly and aggregate-only evidence has no invented count',()=>{
  const f=fixture();for(const [n,label] of [[1,'1 раз'],[2,'2 раза'],[5,'5 раз'],[11,'11 раз'],[12,'12 раз'],[21,'21 раз'],[22,'22 раза'],[111,'111 раз']])assert.equal(f.run(`achievementStatus({status:'done',achievement_count:${n}})`),'Достигнуто '+label);
  const html=f.run(`goalRow({id:1,name:'Test',status:'done',status_label:'Достигнуто',record_in_period:true,achievement_count:2,achievement_count_complete:false,reason:'История неполна'})`);
  assert.match(html,/Количество по доступной истории/);assert.match(html,/data-tooltip="Личный рекорд в периоде"/);assert.doesNotMatch(html,/История неполна/);
  assert.equal(f.run(`achievementStatus({status:'done',status_label:'Достигнуто',achievement_count:null})`),'Достигнуто');
});
test('record dates sort chronologically with unknown dates last',()=>{
  const f=fixture(true);f.node('#filter').value='all';f.run(`state.data={};state.goalData={rows:[{id:1,name:'Missing'},{id:2,name:'Earlier',record_date:'2025-12-31'},{id:3,name:'Later',record_date:'2026-01-01'}]};state.sort='record_date';`);
  for(const direction of [1,-1]){f.run(`state.direction=${direction};renderTable()`);assert.deepEqual([...f.node('#rows').innerHTML.matchAll(/<small>№(\d+)<\/small>/g)].map(m=>Number(m[1])),direction===1?[2,3,1]:[3,2,1]);}
});
test('sync requests cannot be started twice while the first request is pending',async()=>{
  const f=fixture(),d=defer();let calls=0;f.ctx.mockRequest=()=>{calls++;return d.promise;};f.run('poll=async()=>{state.jobRunning=false;}');
  const first=f.run('refreshVocabulary(1)');await f.run('refreshVocabulary(1)');assert.equal(calls,1);d.resolve({});await first;assert.equal(f.run('refreshPending'),false);
});

test('failed sync releases the pending guard and allows retry',async()=>{
  const f=fixture();f.ctx.mockRequest=async()=>{throw new Error('offline');};
  await assert.rejects(f.run('refreshVocabulary(1)'),/offline/);assert.equal(f.run('refreshPending'),false);
  f.run(`state.goal='3';request=async(url,data)=>{window.syncBody=data;};poll=async()=>{state.jobRunning=false;}`);
  await f.run('refreshVocabulary(853)');assert.deepEqual(JSON.parse(f.run('JSON.stringify(window.syncBody)')),{voc_id:853,goal_id:3});
});

test('period maximum remains visible for unmet goals without record qualification text',()=>{
  const f=fixture();
  const html=f.run(`goalRow({id:1,name:'Test',mode:'errors',speed:600,max_errors:0,status:'pending',status_label:'Не достигнуто',achievement_speed:550,achievement_at:'2026-11-02',achievement_errors:5,achievement_source:'race',record_in_period:true,period_complete:true,achievement_complete:false})`);
  assert.match(html,/<b>550 зн\/мин<\/b>/);assert.match(html,/5 ош\./);
  assert.match(html,/Не достигнуто/);assert.match(html,/Личный рекорд в периоде/);
  assert.doesNotMatch(html,/Требования цели этим рекордом не подтверждены|Лучший среди загруженных данных/);
});

test('completed sync keeps the original operation message visible as plain text after navigation',async()=>{
  const f=fixture();
  const message='Загружены данные для «<img src=x>» (№812) за 01.11.2026.';
  f.run(`state.jobVersion=0;state.jobRunning=true;state.goal='another-goal';loadData=async()=>{};`);
  f.ctx.mockRequest=async()=>({running:false,message,done:1,total:1,error:null,version:1});
  await f.run('poll()');
  assert.equal(f.node('#sync-box').hidden,false);
  assert.equal(f.node('#sync-message').textContent,message);
  assert.equal(f.node('#sync-message').innerHTML,undefined);
  assert.equal(f.node('#toast').hidden,false);assert.equal(f.node('#toast').textContent,message);
  assert.equal(f.node('#sync-progress').hidden,true);assert.equal(f.node('#sync-count').hidden,true);
  assert.equal(f.node('#refresh').disabled,false);
  await f.run('poll()');assert.equal(f.node('#sync-message').textContent,message);
  f.run('clearTimeout(toastTimer)');
});

test('sync progress retains its counter and failures never show the success panel',async()=>{
  const f=fixture();f.run('state.jobVersion=0;loadData=async()=>{};');
  f.ctx.mockRequest=async()=>({running:true,message:'Загрузка…',done:2,total:3,error:null,version:0});
  await f.run('poll()');
  assert.equal(f.node('#sync-progress').hidden,false);assert.equal(f.node('#sync-progress').value,2);
  assert.equal(f.node('#sync-count').hidden,false);assert.equal(f.node('#sync-count').textContent,'2 / 3');
  f.ctx.mockRequest=async()=>({running:false,message:'Обновление не завершено. Предыдущие данные сохранены.',error:'offline',version:1});
  await f.run('poll()');
  assert.equal(f.node('#sync-box').hidden,true);
  assert.match(f.node('#error-box').textContent,/Предыдущие данные сохранены/);
});
