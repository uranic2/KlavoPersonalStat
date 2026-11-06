"""Independent training goals and evidence-based evaluation."""
import calendar
import datetime as dt
import json
import math
from pathlib import Path
import sqlite3

import core

PERIODS={'day':'День','week':'Неделя','month':'Месяц','quarter':'Три месяца','half':'Полгода','year':'Год'}
STATUSES={'done':'Достигнуто','pending':'Не достигнуто','empty':'Нет заездов','unloaded':'Не загружено','partial':'Данные неполные','unverifiable':'Не удалось проверить','unconfigured':'Не настроено','future':'Период не начался'}


def bounds(goal,today=None):
    today=today or dt.datetime.now(core.MSK).date()
    if goal['period_type']=='fixed':return goal['date_from'],goal['date_to']
    kind=goal['rolling']
    if kind in ('day','week'):
        return (today-dt.timedelta(days=6 if kind=='week' else 0)).isoformat(),today.isoformat()
    months={'month':1,'quarter':3,'half':6,'year':12}[kind]
    number=today.year*12+today.month-1-months
    year,month=divmod(number,12);month+=1
    return today.replace(year=year,month=month,day=min(today.day,calendar.monthrange(year,month)[1])).isoformat(),today.isoformat()


def migrate(path=None):
    target=Path(path or core.DB)
    with core.connect(target) as conn:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE name='app_goals'").fetchone()
        if exists:return
        # SQLite's backup API includes committed WAL pages in one coherent snapshot.
        folder=target.parent/'backups';folder.mkdir(exist_ok=True)
        backup=folder/('before-goals-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        destination=sqlite3.connect(backup)
        try:conn.backup(destination)
        finally:destination.close()
        conn.executescript('''
        CREATE TABLE app_goals(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,period_type TEXT NOT NULL,rolling TEXT,date_from TEXT,date_to TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE app_goal_vocs(goal_id INTEGER REFERENCES app_goals(id) ON DELETE CASCADE,voc_id INTEGER REFERENCES app_vocs(id),position INTEGER,mode TEXT NOT NULL,speed REAL,max_errors INTEGER,PRIMARY KEY(goal_id,voc_id));
        CREATE TABLE app_coverage(user_id INTEGER,voc_id INTEGER,kind TEXT,date_from TEXT,date_to TEXT,fetched_at TEXT,PRIMARY KEY(user_id,voc_id,kind,date_from,date_to));
        CREATE TABLE app_races(user_id INTEGER,voc_id INTEGER,race_key TEXT,at TEXT,speed REAL,errors INTEGER,source TEXT,PRIMARY KEY(user_id,voc_id,race_key));
        CREATE INDEX app_races_range ON app_races(user_id,voc_id,at);
        CREATE TABLE app_capabilities(user_id INTEGER,voc_id INTEGER,error TEXT,fetched_at TEXT,PRIMARY KEY(user_id,voc_id));
        ''')
        # v1 app_current was committed only after a successful monthly collection.
        for row in conn.execute('SELECT voc_id,fetched_at FROM app_current WHERE user_id=? AND fetched_at IS NOT NULL',(core.USER_ID,)).fetchall():
            start,end=core.period(dt.date.fromisoformat(row['fetched_at'][:10]))
            cover(conn,row['voc_id'],'daily',start,end,row['fetched_at'])
        for row in conn.execute("SELECT voc_id,payload FROM app_raw WHERE kind='details'").fetchall():
            evidence(conn,row['voc_id'],json.loads(row['payload']))


def cover(conn,voc,kind,start,end,fetched,user_id=core.USER_ID):
    conn.execute('INSERT OR REPLACE INTO app_coverage VALUES(?,?,?,?,?,?)',(user_id,voc,kind,start,end,fetched))


def evidence(conn,voc,details,user_id=core.USER_ID):
    posts=list(details.get('journal') or [])
    if details.get('best_speed_post'):posts.append(details['best_speed_post'])
    for post in posts:
        msg=post.get('message',{})
        if msg.get('record_id') is None or not post.get('date') or msg.get('speed') is None:continue
        errors=msg.get('errors')
        if not isinstance(errors,int) or isinstance(errors,bool) or errors<0:errors=None
        at=dt.datetime.fromtimestamp(post['date']['sec'],core.MSK).isoformat()
        conn.execute('INSERT OR REPLACE INTO app_races VALUES(?,?,?,?,?,?,?)',(user_id,voc,str(msg['record_id']),at,msg['speed'],errors,'record'))


def list_goals(conn,user_id=core.USER_ID,template=False):
    table,members=("app_templates","app_template_vocs") if template else ("app_goals","app_goal_vocs")
    return [dict(row) for row in conn.execute(f'SELECT g.*,COUNT(m.voc_id) total FROM {table} g LEFT JOIN {members} m ON m.goal_id=g.id WHERE g.user_id=? GROUP BY g.id ORDER BY g.id',(user_id,))]


def catalog(path=None,user_id=core.USER_ID):
    with core.connect(path) as conn:
        data={'goals':list_goals(conn,user_id),'templates':list_goals(conn,user_id,True),
              'vocs':[dict(r) for r in conn.execute("SELECT v.*,COALESCE(a.short_name,'') short_name FROM app_vocs v LEFT JOIN app_voc_aliases a ON a.voc_id=v.id AND a.user_id=? ORDER BY COALESCE(a.short_name,v.name)",(user_id,))],
              'members':[dict(r) for r in conn.execute('SELECT m.* FROM app_members m JOIN app_groups g ON g.id=m.group_id WHERE g.builtin=1 OR g.user_id=? ORDER BY group_id,position',(user_id,))]}
    for g in data['goals']:
        d=dashboard(g['id'],path,user_id=user_id);g.update(percent=d['percent'],done=d['counts']['done'])
    return data


def definition(identifier,path=None,user_id=core.USER_ID,template=False):
    table,members=("app_templates","app_template_vocs") if template else ("app_goals","app_goal_vocs")
    with core.connect(path) as c:
        row=c.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=?',(identifier,user_id)).fetchone()
        if not row:raise ValueError('Шаблон не найден.' if template else 'Цель не найдена.')
        return dict(row)|{'items':[dict(r)|{'id':r['voc_id']} for r in c.execute(f'SELECT * FROM {members} WHERE goal_id=? ORDER BY position',(identifier,))]}


def save(body,path=None,user_id=core.USER_ID,template=False):
    table,members=("app_templates","app_template_vocs") if template else ("app_goals","app_goal_vocs")
    name=str(body.get('name','')).strip()
    if not name or len(name)>100:raise ValueError('Введите название цели (до 100 символов).')
    kind=body.get('period_type');rolling=body.get('rolling');start=end=None
    if kind=='fixed' and template:
        rolling=None
    elif kind=='fixed':
        try:start=dt.date.fromisoformat(body.get('date_from','')).isoformat();end=dt.date.fromisoformat(body.get('date_to','')).isoformat()
        except (TypeError,ValueError):raise ValueError('Укажите обе даты периода.')
        if start>end:raise ValueError('Дата начала не должна быть позже даты окончания.')
        rolling=None
    elif kind=='rolling':
        if rolling not in PERIODS:raise ValueError('Выберите скользящий период.')
    else:raise ValueError('Выберите способ задания периода.')
    items=body.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=3000:raise ValueError('Добавьте от 1 до 3000 словарей.')
    unique={}
    for item in items:
        voc=core.voc_id(item.get('id',''))
        if not voc:raise ValueError('Неверный ID словаря.')
        if voc in unique:continue
        mode=item.get('mode','speed')
        if mode not in ('speed','errors'):raise ValueError('Неверный режим требования.')
        speed=item.get('speed');errors=item.get('max_errors')
        if speed in ('',None):speed=None
        else:
            if isinstance(speed,bool):raise ValueError('Укажите положительную скорость.')
            try:speed=float(speed)
            except (ValueError,TypeError):raise ValueError('Скорость должна быть числом.')
            if not math.isfinite(speed) or speed<=0:raise ValueError('Скорость должна быть больше нуля.')
        if errors in ('',None):errors=None
        else:
            if isinstance(errors,bool):raise ValueError('Допуск ошибок должен быть целым числом от нуля.')
            try:
                parsed=float(errors)
                if not math.isfinite(parsed) or parsed<0 or not parsed.is_integer():raise ValueError()
                errors=int(parsed)
            except (ValueError,TypeError):raise ValueError('Допуск ошибок должен быть целым числом от нуля.')
        unique[voc]=(mode,speed,errors)
    with core.connect(path) as conn:
        goal_id=body.get('id')
        if goal_id is not None:
            if not conn.execute(f'SELECT 1 FROM {table} WHERE id=? AND user_id=?',(goal_id,user_id)).fetchone():raise ValueError('Цель не найдена.')
            conn.execute(f'UPDATE {table} SET name=?,period_type=?,rolling=?,date_from=?,date_to=?,updated_at=? WHERE id=?',(name,kind,rolling,start,end,core.now(),goal_id))
        else:goal_id=conn.execute(f'INSERT INTO {table}(name,period_type,rolling,date_from,date_to,created_at,updated_at,user_id) VALUES(?,?,?,?,?,?,?,?)',(name,kind,rolling,start,end,core.now(),core.now(),user_id)).lastrowid
        conn.execute(f'DELETE FROM {members} WHERE goal_id=?',(goal_id,))
        for i,(voc,(mode,speed,errors)) in enumerate(unique.items()):
            conn.execute('INSERT OR IGNORE INTO app_vocs VALUES(?,?)',(voc,f'Словарь {voc}'))
            conn.execute(f'INSERT INTO {members} VALUES(?,?,?,?,?,?)',(goal_id,voc,i,mode,speed,errors))
    return goal_id


def delete(identifier,path=None,user_id=core.USER_ID,template=False):
    table="app_templates" if template else "app_goals"
    with core.connect(path) as conn:
        if not conn.execute(f'DELETE FROM {table} WHERE id=? AND user_id=?',(identifier,user_id)).rowcount:raise ValueError('Цель не найдена.')


def coverage(intervals,start,end):
    """Union inclusive dates, including explicit empty responses."""
    whole=[r for r in intervals if r['date_from']<=start and r['date_to']>=end]
    if whole:return True,max(r['fetched_at'] for r in whole)
    cursor=start;used=[]
    for row in sorted(intervals,key=lambda r:r['date_from']):
        if row['date_to']<cursor or row['date_from']>end:continue
        if row['date_from']>cursor:return False,min(used) if used else None
        used.append(row['fetched_at'])
        if row['date_to']>=end:return True,min(used)
        cursor=(dt.date.fromisoformat(row['date_to'])+dt.timedelta(days=1)).isoformat()
    return False,min(used) if used else None


def dashboard(identifier,path=None,today=None,user_id=core.USER_ID):
    today=today or dt.datetime.now(core.MSK).date();today_s=today.isoformat()
    with core.connect(path) as conn:
        goal=conn.execute('SELECT * FROM app_goals WHERE id=? AND user_id=?',(identifier,user_id)).fetchone()
        if not goal:raise ValueError('Цель не найдена.')
        goal=dict(goal);start,end=bounds(goal,today);effective_end=min(end,today_s)
        phase='future' if start>today_s else 'finished' if end<today_s else 'active'
        rows=[dict(r) for r in conn.execute("SELECT v.id,v.name,COALESCE(a.short_name,'') short_name,m.mode,m.speed,m.max_errors FROM app_goal_vocs m JOIN app_vocs v ON v.id=m.voc_id LEFT JOIN app_voc_aliases a ON a.voc_id=v.id AND a.user_id=? WHERE m.goal_id=? ORDER BY m.position",(user_id,identifier))]
        for r in rows:
            voc=r['id'];r.update(month_max=None,month_date=None,month_races=0,best_speed=None,best_errors=None,best_at=None,fetched_at=None,complete=False,reason='')
            # Goal refreshes also save details, but do not replace app_current's
            # group snapshot. Read the latest record without changing that snapshot.
            current=conn.execute('SELECT record,record_date FROM app_current WHERE user_id=? AND voc_id=?',(user_id,voc)).fetchone()
            r.update(record=current['record'] if current else None,record_date=current['record_date'] if current else None)
            raw=conn.execute("SELECT payload FROM app_raw x JOIN app_runs run ON run.id=x.run_id WHERE x.voc_id=? AND x.kind='details' AND run.user_id=? ORDER BY run_id DESC LIMIT 1",(voc,user_id)).fetchone()
            if raw:
                details=json.loads(raw['payload']);info=details.get('info',{});post=details.get('best_speed_post')
                if 'best_speed' in info:
                    record=info['best_speed']
                    record_date=core.day(post.get('date')) if record is not None and post and post.get('message',{}).get('speed')==record else None
                    r.update(record=record,record_date=record_date)
            r['best_source']=None
            dates=[dict(x) for x in conn.execute('SELECT * FROM app_coverage WHERE user_id=? AND voc_id=? AND date_to>=? AND date_from<=?',(user_id,voc,start,effective_end))] if phase!='future' else []
            daily=[x for x in dates if x['kind']=='daily'];complete,fetched=coverage(daily,start,effective_end) if phase!='future' else (False,None)
            r['complete']=complete;r['fetched_at']=fetched or max([x['fetched_at'] for x in dates],default=None)
            days=conn.execute('SELECT * FROM daily_stats WHERE user_id=? AND voc_id=? AND day>=? AND day<=? ORDER BY max_speed DESC,day',(user_id,voc,start,effective_end)).fetchall() if phase!='future' else []
            if days:r.update(month_max=days[0]['max_speed'],month_date=days[0]['day'],month_races=sum(d['races'] for d in days))
            races=conn.execute('SELECT * FROM app_races WHERE user_id=? AND voc_id=? AND substr(at,1,10)>=? AND substr(at,1,10)<=? ORDER BY speed DESC,at,race_key',(user_id,voc,start,effective_end)).fetchall() if phase!='future' else []
            eligible=[x for x in races if r['mode']=='speed' or (r['max_errors'] is not None and x['errors'] is not None and x['errors']<=r['max_errors'])]
            if r['mode']=='speed' and days:r.update(best_speed=days[0]['max_speed'],best_at=days[0]['day'],best_source='daily')
            if eligible:
                best=eligible[0]
                # Prefer a known race on the same day; an earlier aggregate day
                # wins a speed tie without borrowing errors from a later race.
                if r['best_speed'] is None or best['speed']>r['best_speed'] or (best['speed']==r['best_speed'] and best['at'][:10]<=r['best_at'][:10]):
                    r.update(best_speed=best['speed'],best_errors=best['errors'],best_at=best['at'],best_source='race')
            if races and (r['month_max'] is None or races[0]['speed']>r['month_max']):r.update(month_max=races[0]['speed'],month_date=races[0]['at'][:10])
            race_complete,_=coverage([x for x in dates if x['kind']=='races'],start,effective_end)
            r['achievement_complete']=race_complete or (r['mode']=='speed' and complete)
            configured=r['speed'] is not None and (r['mode']=='speed' or r['max_errors'] is not None)
            if not configured:status='unconfigured'
            elif phase=='future':status='future'
            elif r['best_speed'] is not None and r['best_speed']>=r['speed']:status='done'
            elif not dates and not days and not races:status='unloaded'
            elif not complete:status='partial'
            elif not days and not races:status='empty'
            elif r['mode']=='errors' and not race_complete:
                status='unverifiable'
                capability=conn.execute('SELECT error FROM app_capabilities WHERE user_id=? AND voc_id=?',(user_id,voc)).fetchone()
                r['reason']=('Для загрузки отдельных заездов сайт требует Premium.' if capability['error']=='not pro' else capability['error']) if capability and capability['error'] else 'В сохранённых данных нет полной истории заездов для проверки ошибок. Нажмите «Обновить».'
            else:status='pending'
            matched={x['race_key'] for x in eligible if configured and x['speed']>=r['speed']}
            r['achievement_count']=len(matched) if matched or (race_complete and status!='done') else None
            r['achievement_count_complete']=race_complete
            r['status']=status;r['status_label']=STATUSES[status]
            if status=='done' and not r['achievement_complete']:r['reason']='Достижение подтверждено дневным максимумом; остальная история неполна.' if r['best_source']=='daily' else 'Достижение подтверждено одним заездом; остальная история неполна.'
            r['record_in_period']=bool(r['record'] is not None and r['record_date'] and start<=r['record_date']<=effective_end)
            # Display the period maximum independently of goal qualification.
            candidates=[]
            if days and days[0]['max_speed'] is not None:
                candidates.append((days[0]['max_speed'],days[0]['day'],None,'daily',''))
            if races:
                candidates.extend((x['speed'],x['at'],x['errors'],'race',x['race_key']) for x in races if x['speed'] is not None)
            if r['record_in_period']:
                candidates.append((r['record'],r['record_date'],None,'record',''))
            maximum=min(candidates,key=lambda x:(-x[0],x[1][:10],0 if x[3]=='race' else 1,x[1],x[4])) if candidates else (None,None,None,None,'')
            r.update(achievement_speed=maximum[0],achievement_at=maximum[1],achievement_errors=maximum[2],achievement_source=maximum[3],period_complete=complete or race_complete)
        counts={key:sum(r['status']==key for r in rows) for key in STATUSES}
    return {'goal':goal,'rows':rows,'period_from':start,'period_to':end,'phase':phase,'counts':counts,'percent':round(counts['done']/len(rows)*100,1) if rows else 0,'statuses':STATUSES}


def chunks(start,end,size=90):
    cursor=dt.date.fromisoformat(start);last=dt.date.fromisoformat(end)
    while cursor<=last:
        stop=min(last,cursor+dt.timedelta(days=size-1));yield cursor.isoformat(),stop.isoformat();cursor=stop+dt.timedelta(days=1)


def sync(identifier,progress=lambda **kw:None,path=None,today=None,user_id=core.USER_ID):
    import history
    data=dashboard(identifier,path,today,user_id)
    return history.sync_vocs([r['id'] for r in data['rows']],data['period_from'],data['period_to'],progress,path,user_id,today,
                             errors=any(r['mode']=='errors' for r in data['rows']))
