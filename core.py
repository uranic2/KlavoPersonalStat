"""Local Klavogonki statistics, SQLite storage and forum dictionary imports."""
import calendar
from contextlib import contextmanager
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'stats.sqlite3'
USER_ID = 823572
MSK = dt.timezone(dt.timedelta(hours=3))
BASE = 'https://klavogonki.ru'


def period(today=None):
    today = today or dt.datetime.now(MSK).date()
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    start = today.replace(year=year, month=month, day=min(today.day, calendar.monthrange(year, month)[1]))
    return start.isoformat(), today.isoformat()


def day(value):
    return dt.datetime.fromtimestamp(value['sec'], MSK).date().isoformat() if value else None


def now():
    return dt.datetime.now(MSK).isoformat(timespec='seconds')


@contextmanager
def connect(path=None):
    conn = sqlite3.connect(path or DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'KlavoPersonalStat/1.0 (personal statistics)'}), timeout=25) as response:
                text = response.read().decode('utf-8')
                if 'Access from foreign IP' in text:
                    raise RuntimeError('Клавогонки ограничили доступ с текущего IP-адреса.')
                return text
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def api(endpoint, **params):
    time.sleep(.3)
    result = json.loads(fetch(BASE + '/api/profile/' + endpoint + '?' + urlencode(params)))
    if result.get('err') or result.get('ok') != 1:
        raise RuntimeError(f'Клавогонки: {result.get("err", "неожиданный ответ API")}')
    return result


def topic_url(value):
    parsed = urlparse(value.strip())
    match = re.fullmatch(r'/forum/[a-z]+/(\d+)/(?:page1/)?', parsed.path)
    if parsed.scheme not in ('https', 'http') or parsed.hostname != 'klavogonki.ru' or not match:
        raise ValueError('Нужна ссылка на тему форума klavogonki.ru, например /forum/academy/297/.')
    return BASE + re.sub(r'page1/$', '', parsed.path)


def voc_id(value):
    value = str(value).strip()
    if re.fullmatch(r'\d{1,9}', value) and int(value) > 0:
        return int(value)
    parsed = urlparse(value)
    if parsed.hostname != 'klavogonki.ru' or parsed.scheme not in ('https', 'http'):
        return None
    match = re.match(r'^/vocs/(\d+)(?:/|$)', parsed.path)
    if match:
        return int(match[1])
    if parsed.path == '/create/':
        query = parse_qs(parsed.query)
        if query.get('gametype') == ['voc'] and query.get('voc', [''])[0].isdigit():
            return int(query['voc'][0])
    return None


class ForumParser(HTMLParser):
    """Read the rendered text of post #1, excluding its BBCode editor copy.

    Generic 'Рекорды' / 'Обычный' links inherit the exercise name before them.
    This matters for Koschei's index, where most anchors are game links.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.finished = False
        self.depth = 0
        self.lines = []
        self.line = []
        self.anchor = None

    def newline(self):
        if self.line:
            self.lines.append(self.line)
            self.line = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.active:
            if not self.finished and tag == 'div' and 'text' in attrs.get('class', '').split():
                self.active, self.depth = True, 1
            return
        if tag == 'div':
            self.depth += 1
        if tag in ('br', 'li', 'p', 'div', 'hr'):
            self.newline()
        if tag == 'a':
            self.anchor = {'href': attrs.get('href', ''), 'text': ''}

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == 'a' and self.anchor is not None:
            self.line.append(self.anchor)
            self.anchor = None
        if tag in ('li', 'p', 'div'):
            self.newline()
        if tag == 'div':
            self.depth -= 1
            if self.depth == 0:
                self.active, self.finished = False, True

    def handle_data(self, text):
        if not self.active:
            return
        if self.anchor is not None:
            self.anchor['text'] += text
        else:
            self.line.append(text)


def parse_forum(source):
    first = re.search(r'<a name="post1"></a>(.*?)(?=<a name="post2"></a>|$)', source, re.S)
    if not first:
        raise ValueError('Не найдено первое сообщение темы. Возможно, сайт изменил формат.')
    parser = ForumParser()
    parser.feed(first[1])
    parser.newline()
    result = {}
    for line in parser.lines:
        prefix = ''
        for part in line:
            if isinstance(part, str):
                prefix += part
                continue
            link = part['href']
            if link.startswith('/'):
                link = BASE + link
            identifier = voc_id(link)
            text = re.sub(r'\s+', ' ', part['text']).strip()
            if identifier:
                generic = bool(re.search(r'^(Обычный|Открытый|Квалификация|Рекорды|Рейтинг|Играть|\d+ сек)', text, re.I))
                label = re.sub(r'^\s*(?:\[\*\])?(?:\d+\s*[-–.]\s*)?', '', prefix).strip(' -–:,(')
                # For generic links retain the line's heading before the first game link.
                if identifier not in result:
                    result[identifier] = {'id': identifier, 'name': (label if generic and label else text) or f'Словарь {identifier}'}
            # Do not append generic game-link text to subsequent labels in the same line.
            if not identifier:
                prefix += text
    if not result:
        raise ValueError('В первом сообщении нет ссылок на словари.')
    return list(result.values())


def init_db(path=None):
    target = Path(path or DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect(target) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS app_groups(id INTEGER PRIMARY KEY, name TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', builtin INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS app_vocs(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_members(group_id INTEGER REFERENCES app_groups(id) ON DELETE CASCADE, voc_id INTEGER REFERENCES app_vocs(id), position INTEGER NOT NULL, PRIMARY KEY(group_id,voc_id));
        CREATE TABLE IF NOT EXISTS app_current(user_id INTEGER, voc_id INTEGER, record INTEGER, record_date TEXT, races INTEGER, avg_speed REAL, updated TEXT, fetched_at TEXT, PRIMARY KEY(user_id,voc_id));
        CREATE TABLE IF NOT EXISTS daily_stats(user_id INTEGER, voc_id INTEGER, day TEXT, max_speed INTEGER, avg_speed REAL, races INTEGER, fetched_at TEXT, PRIMARY KEY(user_id,voc_id,day));
        CREATE TABLE IF NOT EXISTS app_runs(id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, group_id INTEGER, state TEXT, error TEXT, dictionaries INTEGER);
        CREATE TABLE IF NOT EXISTS app_raw(run_id INTEGER REFERENCES app_runs(id), voc_id INTEGER, kind TEXT, payload TEXT, PRIMARY KEY(run_id,voc_id,kind));
        ''')
        if not conn.execute('SELECT 1 FROM app_groups LIMIT 1').fetchone():
            seeds = json.loads((ROOT / 'config' / 'builtin_groups.json').read_text(encoding='utf-8'))
            for i, seed in enumerate(seeds):
                gid = conn.execute('INSERT INTO app_groups(name,source_url,builtin,position) VALUES(?,?,1,?)', (seed['name'],seed['source_url'],i)).lastrowid
                write_members(conn,gid,seed['vocs'])
    import goals
    goals.migrate(target)
    import vocabulary
    vocabulary.migrate(target)
    import profiles
    profiles.migrate(target)


def write_members(conn,gid,vocs):
    conn.execute('DELETE FROM app_members WHERE group_id=?',(gid,))
    for i, item in enumerate(vocs):
        # An imported index may call the link merely "Источник" or "Рекорды".
        # Preserve an existing name; sync() alone replaces it with the API name.
        conn.execute('INSERT OR IGNORE INTO app_vocs VALUES(?,?)', (item['id'],item['name']))
        conn.execute('INSERT OR IGNORE INTO app_members VALUES(?,?,?)',(gid,item['id'],i))


def save_group(body, path=None, user_id=USER_ID):
    name = str(body.get('name','')).strip()
    if not name or len(name)>100:
        raise ValueError('Введите название группы (до 100 символов).')
    gid = body.get('id')
    source_url = str(body.get('source_url','')).strip()
    # The topic is imported only on explicit request; editing IDs does not re-add removed members.
    vocs = parse_forum(fetch(topic_url(source_url))) if body.get('import_source') and source_url else []
    if source_url:
        source_url = topic_url(source_url)
    text = str(body.get('dictionaries',''))
    tokens = re.split(r'[\s,;]+',text.strip()) if text.strip() else []
    with connect(path) as conn:
        known = {r['id']:r['name'] for r in conn.execute('SELECT * FROM app_vocs')}
        for token in tokens:
            identifier = voc_id(token)
            if not identifier:
                raise ValueError(f'Не удалось распознать словарь: {token[:100]}. Укажите ID или ссылку /vocs/ID/.')
            if not any(v['id']==identifier for v in vocs):
                vocs.append({'id':identifier,'name':known.get(identifier,f'Словарь {identifier}')})
        if not vocs:
            raise ValueError('Добавьте хотя бы один словарь или импортируйте список из темы.')
        if len(vocs)>3000:
            raise ValueError('В одной группе допускается до 3000 словарей.')
        if gid:
            group = conn.execute('SELECT * FROM app_groups WHERE id=? AND user_id=?',(gid,user_id)).fetchone()
            if not group or group['builtin']:
                raise ValueError('Эту группу нельзя редактировать.')
            conn.execute('UPDATE app_groups SET name=?,source_url=? WHERE id=?',(name,source_url,gid))
        else:
            gid=conn.execute('INSERT INTO app_groups(name,source_url,position,user_id) VALUES(?,?,(SELECT COALESCE(MAX(position),0)+1 FROM app_groups),?)',(name,source_url,user_id)).lastrowid
        write_members(conn,gid,vocs)
    return gid


def delete_group(gid,path=None,user_id=USER_ID):
    with connect(path) as conn:
        group = conn.execute('SELECT builtin FROM app_groups WHERE id=? AND user_id=?',(gid,user_id)).fetchone()
        if not group or group['builtin']:
            raise ValueError('Удалять можно только свои группы.')
        conn.execute('DELETE FROM app_groups WHERE id=?',(gid,))


def dashboard(group_id=None,path=None,user_id=USER_ID):
    start,end=period()
    with connect(path) as conn:
        groups=[dict(r) for r in conn.execute('''SELECT g.*,COUNT(m.voc_id) AS total,COUNT(CASE WHEN c.record IS NOT NULL THEN 1 END) AS played FROM app_groups g LEFT JOIN app_members m ON m.group_id=g.id LEFT JOIN app_current c ON c.voc_id=m.voc_id AND c.user_id=? WHERE g.builtin=1 OR g.user_id=? GROUP BY g.id ORDER BY g.position,g.id''',(user_id,user_id))]
        if group_id is not None and not any(g['id']==group_id for g in groups):
            raise ValueError('Группа не найдена.')
        query='''SELECT v.id,v.name,COALESCE(a.short_name,'') short_name,c.record,c.record_date,c.races,c.avg_speed,c.fetched_at FROM app_vocs v LEFT JOIN app_voc_aliases a ON a.voc_id=v.id AND a.user_id=? LEFT JOIN app_current c ON c.voc_id=v.id AND c.user_id=? WHERE EXISTS(SELECT 1 FROM app_members m JOIN app_groups g ON g.id=m.group_id WHERE m.voc_id=v.id AND (g.builtin=1 OR g.user_id=?)'''
        params=[user_id,user_id,user_id]
        if group_id is not None:
            query+=' AND m.group_id=?';params.append(group_id)
        query+=') ORDER BY (SELECT MIN(m2.position) FROM app_members m2 JOIN app_groups g2 ON g2.id=m2.group_id WHERE m2.voc_id=v.id AND (g2.builtin=1 OR g2.user_id=?)'+(' AND m2.group_id=?' if group_id is not None else '')+'),v.id'
        params.append(user_id)
        if group_id is not None:params.append(group_id)
        rows=[dict(r) for r in conn.execute(query,params)]
        daily={}
        for r in conn.execute('SELECT * FROM daily_stats WHERE user_id=? AND day>=? AND day<=? ORDER BY day',(user_id,start,end)):
            daily.setdefault(r['voc_id'],[]).append(r)
        for row in rows:
            days=daily.get(row['id'],[])
            best=min(days,key=lambda d:(-d['max_speed'],d['day'])) if days else None
            row.update(month_max=best['max_speed'] if best else None,month_date=best['day'] if best else None,month_races=sum(d['races'] for d in days))
        last=conn.execute("SELECT finished_at FROM app_runs WHERE state='done' AND user_id=? ORDER BY id DESC LIMIT 1",(user_id,)).fetchone()
    import profiles
    return dict(profile=profiles.get(user_id,path),user_id=user_id,period_from=start,period_to=end,groups=groups,rows=rows,last_sync=last['finished_at'] if last else None)


def sync(group_id=None,progress=lambda **kw:None,path=None,user_id=USER_ID):
    import history
    data=dashboard(group_id,path,user_id)
    return history.sync_vocs([r['id'] for r in data['rows']],data['period_from'],data['period_to'],progress,path,user_id)
