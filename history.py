"""Shared profile-scoped collection, daily charts and honest word analysis."""
from collections import Counter
import datetime as dt
from html import unescape
import json
import re
import unicodedata

import core
import goals
import profiles


def dates(start,end,today=None):
    try:a=dt.date.fromisoformat(start);b=dt.date.fromisoformat(end)
    except (ValueError,TypeError):raise ValueError('Укажите обе даты периода.')
    if a>b:raise ValueError('Дата начала не должна быть позже даты окончания.')
    return a.isoformat(),b.isoformat(),min(b,today or dt.datetime.now(core.MSK).date()).isoformat()


def vocabulary(voc,user_id,path=None):
    profiles.get(user_id,path)
    with core.connect(path) as c:
        row=c.execute("SELECT v.*,COALESCE(a.short_name,'') short_name FROM app_vocs v LEFT JOIN app_voc_aliases a ON a.voc_id=v.id AND a.user_id=? WHERE v.id=?",(user_id,voc)).fetchone()
        if not row:raise ValueError('Словарь не найден.')
        return dict(row)


def probe(voc,start,end,user_id):
    # This is the site's verified detailed-statistics endpoint. No inferred
    # fields or pagination contracts are treated as word-error evidence.
    raw=json.loads(core.fetch(core.BASE+'/api/profile/get-stats-details-data?'+core.urlencode(dict(userId=user_id,gametype='voc-'+str(voc),fromDate=start,toDate=end,grouping='none'))))
    if raw.get('err')=='not pro':return 'Для подробной истории заездов сайт требует Premium. Анализ слов недоступен.'
    if raw.get('err'):return 'Клавогонки: '+str(raw['err'])
    return 'Доступный источник не предоставляет подтверждённых позиций ошибок в словах. Анализ всех заездов недоступен.'


def sync_vocs(identifiers,start,end,progress=lambda **kw:None,path=None,user_id=core.USER_ID,today=None,errors=False):
    profiles.get(user_id,path)
    start,end,effective=dates(start,end,today)
    ids=list(dict.fromkeys(identifiers))
    for voc in ids:vocabulary(voc,user_id,path)
    if start>effective:
        progress(message='Период ещё не начался. Будущие заезды не запрашиваются.',done=0,total=0);return
    with core.connect(path) as c:run=c.execute("INSERT INTO app_runs(started_at,state,user_id) VALUES(?,'running',?)",(core.now(),user_id)).lastrowid
    try:
        overview=core.api('get-stats-overview',userId=user_id);collected={};limitation=None
        for i,voc in enumerate(ids):
            progress(message=f'Словарь №{voc}: загрузка результатов…',done=i,total=len(ids))
            key='voc-'+str(voc)
            if key not in overview['gametypes']:collected[voc]=(None,[]);continue
            details=core.api('get-stats-details',userId=user_id,gametype=key);days=[]
            for a,b in goals.chunks(start,effective):
                days.extend(core.api('get-stats-details-data',userId=user_id,gametype=key,fromDate=a,toDate=b,grouping='day')['list'])
            collected[voc]=(details,days)
            if errors and limitation is None:limitation=probe(voc,effective,effective,user_id)
        names={}
        for voc,(details,_) in collected.items():
            if details is None and vocabulary(voc,user_id,path)['name'].startswith('Словарь '):
                page=core.fetch(core.BASE+f'/vocs/{voc}/')
                title=re.search(r'<title>(.*?)</title>',page,re.S|re.I)
                if title:names[voc]=unescape(title[1]).split(' - ')[0].strip()
        fetched=core.now()
        with core.connect(path) as c:
            c.execute('INSERT INTO app_raw VALUES(?,?,?,?)',(run,0,'overview',json.dumps(overview,ensure_ascii=False)))
            for voc,(details,days) in collected.items():
                c.execute('DELETE FROM daily_stats WHERE user_id=? AND voc_id=? AND day>=? AND day<=?',(user_id,voc,start,effective))
                for d in days:
                    date=core.day(d['date'])
                    if start<=date<=effective:c.execute('INSERT OR REPLACE INTO daily_stats VALUES(?,?,?,?,?,?,?)',(user_id,voc,date,d['max_speed'],d['avg_speed'],d['cnt'],fetched))
                goals.cover(c,voc,'daily',start,effective,fetched,user_id)
                if details:
                    c.execute('UPDATE app_vocs SET name=? WHERE id=?',(details['gametype']['name'],voc));goals.evidence(c,voc,details,user_id)
                    info=details.get('info',{});post=details.get('best_speed_post');record=info.get('best_speed')
                    record_date=core.day(post.get('date')) if record is not None and post and post.get('message',{}).get('speed')==record else None
                    if 'best_speed' in info:
                        c.execute('INSERT OR REPLACE INTO app_current VALUES(?,?,?,?,?,?,?,?)',(user_id,voc,record,record_date,info.get('num_races'),info.get('avg_speed'),info.get('updated'),fetched))
                    for kind,payload in [('details',details),('daily',{'list':days})]:c.execute('INSERT INTO app_raw VALUES(?,?,?,?)',(run,voc,kind,json.dumps(payload,ensure_ascii=False)))
                else:c.execute('INSERT OR REPLACE INTO app_current VALUES(?,?,?,?,?,?,?,?)',(user_id,voc,None,None,0,None,None,fetched))
                if limitation:c.execute('INSERT OR REPLACE INTO app_capabilities VALUES(?,?,?,?)',(user_id,voc,limitation,fetched))
            for voc,name in names.items():c.execute('UPDATE app_vocs SET name=? WHERE id=?',(name,voc))
            c.execute("UPDATE app_runs SET state='done',finished_at=?,dictionaries=? WHERE id=?",(fetched,len(ids),run))
        profiles.refresh_optional(user_id,path)
        progress(message=f'Обновлено словарей: {len(ids)}.',done=len(ids),total=len(ids))
    except Exception as exc:
        with core.connect(path) as c:c.execute("UPDATE app_runs SET state='error',finished_at=?,error=? WHERE id=?",(core.now(),str(exc),run))
        raise


def chart(voc,start,end,path=None,user_id=core.USER_ID,today=None):
    item=vocabulary(voc,user_id,path);start,end,effective=dates(start,end,today)
    with core.connect(path) as c:
        intervals=[dict(r) for r in c.execute("SELECT * FROM app_coverage WHERE user_id=? AND voc_id=? AND kind='daily' AND date_to>=? AND date_from<=?",(user_id,voc,start,effective))]
        stats={r['day']:dict(r) for r in c.execute('SELECT * FROM daily_stats WHERE user_id=? AND voc_id=? AND day>=? AND day<=?',(user_id,voc,start,effective))}
    complete,fetched=goals.coverage(intervals,start,effective) if start<=effective else (False,None)
    # Bound chart payload size without limiting the existing goal history.
    if (dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days>3660:raise ValueError('Для графика выберите не более десяти лет.')
    rows=[];cursor=dt.date.fromisoformat(start)
    while cursor.isoformat()<=end:
        day=cursor.isoformat();known=day<=effective and any(x['date_from']<=day<=x['date_to'] for x in intervals)
        row=stats.get(day)
        rows.append(dict(day=day,max_speed=row['max_speed'] if row else None,avg_speed=row['avg_speed'] if row else None,races=row['races'] if row else 0 if known else None,known=known or row is not None))
        cursor+=dt.timedelta(days=1)
    return dict(vocabulary=item,period_from=start,period_to=end,complete=complete,fetched_at=fetched,rows=rows,future=start>effective)


def word_tokens(text):
    def letter(char):return char.isalnum() or unicodedata.category(char).startswith('M')
    i=0
    while i<len(text):
        if not text[i].isalnum():i+=1;continue
        start=i;i+=1
        while i<len(text):
            if letter(text[i]):i+=1
            elif text[i] in "-'’" and i+1<len(text) and text[i+1].isalnum():i+=1
            else:break
        yield start,i,unicodedata.normalize('NFC',text[start:i]).casefold()


def word_counts(races):
    """Internal verified evidence: Unicode codepoint positions in original text.

    Hyphens and apostrophes inside a word stay part of the word; outer
    punctuation is excluded. One token occurrence counts at most once.
    """
    counts=Counter();seen=set();processed=skipped=0
    for race in races:
        if race['race_key'] in seen:continue
        seen.add(race['race_key']);text=race.get('text');positions=race.get('positions')
        if not isinstance(text,str) or not isinstance(positions,list) or any(type(p) is not int or p<0 or p>=len(text) for p in positions):skipped+=1;continue
        tokens=list(word_tokens(text));hit=set()
        for pos in positions:
            token=next((t for t in tokens if t[0]<=pos<t[1]),None)
            if token is not None:hit.add((token[0],token[2]))
        counts.update(word for _,word in hit);processed+=1
    alphabet='абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    def word_order(word):return tuple((1,alphabet.index(c)) if c in alphabet else (0,ord(c)) for c in word)
    return sorted(counts.items(),key=lambda x:(-x[1],word_order(x[0]))),processed,skipped


def analyze(voc,start,end,limit=10,path=None,user_id=core.USER_ID,today=None,progress=lambda **kw:None):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('Количество слов должно быть целым числом от 1 до 100.')
    data=chart(voc,start,end,path,user_id,today);start,end,effective=dates(start,end,today)
    data.update(words=[],processed=0,skipped=0,total=None,analysis_complete=False)
    if data['future']:return data|{'message':'Период ещё не начался.','state':'future'}
    progress(message='Проверяем доступность подробной истории…',done=0,total=0)
    with core.connect(path) as c:
        races=[dict(r) for r in c.execute('SELECT * FROM app_word_evidence WHERE user_id=? AND voc_id=? AND substr(at,1,10)>=? AND substr(at,1,10)<=? ORDER BY at,race_key',(user_id,voc,start,effective))]
        spans=[dict(r) for r in c.execute("SELECT * FROM app_coverage WHERE user_id=? AND voc_id=? AND kind='words'",(user_id,voc))]
    if data['complete']:data['total']=sum(r['races'] or 0 for r in data['rows'])
    if data['total']==0:return data|{'message':'Заездов не было.','state':'empty','analysis_complete':True}
    full,_=goals.coverage(spans,start,effective)
    for race in races:
        try:race['positions']=json.loads(race['positions'])
        except (ValueError,TypeError):race['positions']=None
    ranked,processed,skipped=word_counts(races)
    complete=full and not skipped and (data['total'] is None or processed==data['total'])
    limitation='' if complete else probe(voc,start,min(effective,start),user_id)
    with core.connect(path) as c:c.execute('INSERT OR REPLACE INTO app_capabilities VALUES(?,?,?,?)',(user_id,voc,limitation,core.now()))
    message=('В проанализированных заездах ошибок не найдено.' if not ranked else 'Анализ завершён.') if complete else 'По доступным данным. '+limitation
    return data|dict(words=[{'word':w,'count':n} for w,n in ranked[:limit]],processed=processed,skipped=max(skipped,(data['total']-processed) if data['total'] is not None else skipped),analysis_complete=complete,message=message,state='done' if complete else 'partial' if processed else 'unavailable')
