"""Profile registry and repeatable migration of personal data ownership."""
import datetime as dt
import json
import os
import re
import tempfile
from urllib.parse import urlparse
from pathlib import Path
import sqlite3

import core


def migrate(path=None):
    target=Path(path or core.DB)
    with core.connect(target) as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='app_profiles'").fetchone():return
        folder=target.parent/'backups';folder.mkdir(exist_ok=True)
        backup=sqlite3.connect(folder/('before-profiles-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
        try:c.backup(backup)
        finally:backup.close()
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE app_profiles(id INTEGER PRIMARY KEY,name TEXT,updated_at TEXT)')
        ids=set()
        if any(c.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in ('app_goals','app_runs','app_voc_aliases')) or c.execute('SELECT 1 FROM app_groups WHERE builtin=0 LIMIT 1').fetchone():
            ids.add(core.USER_ID)
        for table in ('app_current','daily_stats','app_coverage','app_races','app_capabilities'):
            ids.update(r[0] for r in c.execute(f'SELECT DISTINCT user_id FROM {table}') if r[0] is not None)
        c.executemany('INSERT INTO app_profiles(id) VALUES(?)',[(i,) for i in sorted(ids)])
        c.execute('ALTER TABLE app_groups ADD COLUMN user_id INTEGER')
        c.execute('UPDATE app_groups SET user_id=? WHERE builtin=0',(core.USER_ID,))
        for operation in ('INSERT','UPDATE'):
            c.execute(f"CREATE TRIGGER app_groups_profile_{operation.lower()} BEFORE {operation} ON app_groups WHEN NEW.builtin=0 AND NOT EXISTS(SELECT 1 FROM app_profiles WHERE id=NEW.user_id) BEGIN SELECT RAISE(ABORT,'Unknown profile'); END")
        for table in ('app_goals','app_runs'):
            c.execute(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT {core.USER_ID}')
            for operation in ('INSERT','UPDATE'):
                c.execute(f"CREATE TRIGGER {table}_profile_{operation.lower()} BEFORE {operation} ON {table} WHEN NOT EXISTS(SELECT 1 FROM app_profiles WHERE id=NEW.user_id) BEGIN SELECT RAISE(ABORT,'Unknown profile'); END")
        c.execute('ALTER TABLE app_voc_aliases RENAME TO app_voc_aliases_legacy')
        c.execute('CREATE TABLE app_voc_aliases(user_id INTEGER REFERENCES app_profiles(id),voc_id INTEGER REFERENCES app_vocs(id),short_name TEXT NOT NULL CHECK(length(short_name) BETWEEN 1 AND 100),PRIMARY KEY(user_id,voc_id))')
        c.execute('INSERT INTO app_voc_aliases SELECT ?,voc_id,short_name FROM app_voc_aliases_legacy',(core.USER_ID,))
        c.execute('DROP TABLE app_voc_aliases_legacy')
        c.execute('CREATE TABLE app_templates(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,period_type TEXT NOT NULL,rolling TEXT,date_from TEXT,date_to TEXT,created_at TEXT,updated_at TEXT,user_id INTEGER NOT NULL REFERENCES app_profiles(id))')
        c.execute('CREATE TABLE app_template_vocs(goal_id INTEGER REFERENCES app_templates(id) ON DELETE CASCADE,voc_id INTEGER REFERENCES app_vocs(id),position INTEGER,mode TEXT NOT NULL,speed REAL,max_errors INTEGER,PRIMARY KEY(goal_id,voc_id))')
        c.execute('CREATE TABLE app_word_evidence(user_id INTEGER REFERENCES app_profiles(id),voc_id INTEGER REFERENCES app_vocs(id),race_key TEXT,at TEXT,text TEXT NOT NULL,positions TEXT NOT NULL,PRIMARY KEY(user_id,voc_id,race_key))')
        c.execute('CREATE INDEX app_profile_goals ON app_goals(user_id)')
        c.execute('CREATE INDEX app_profile_runs ON app_runs(user_id,id)')


def get(user_id,path=None):
    with core.connect(path) as c:
        row=c.execute('SELECT * FROM app_profiles WHERE id=?',(user_id,)).fetchone()
        if not row:raise ValueError('Профиль не найден.')
        return dict(row)


def create(user_id,path=None):
    if isinstance(user_id,bool) or not isinstance(user_id,int) or user_id<=0:raise ValueError('Неверный ID профиля.')
    with core.connect(path) as c:c.execute('INSERT OR IGNORE INTO app_profiles(id) VALUES(?)',(user_id,))
    return get(user_id,path)


def refresh(user_id,path=None):
    """Verified /api/profile/get-summary response has user.id and user.login."""
    get(user_id,path)
    data=json.loads(core.fetch(core.BASE+'/api/profile/get-summary?'+core.urlencode({'id':user_id})))
    user=data.get('user',{})
    if user.get('id')!=user_id or not isinstance(user.get('login'),str) or not user['login'].strip():
        raise ValueError('Клавогонки не вернули имя указанного профиля.')
    with core.connect(path) as c:c.execute('UPDATE app_profiles SET name=?,updated_at=? WHERE id=?',(user['login'].strip(),core.now(),user_id))
    return get(user_id,path)


def refresh_optional(user_id,path=None):
    try:return refresh(user_id,path)
    except Exception:return get(user_id,path)


def profile_id(value):
    text=str(value).strip()
    if re.fullmatch(r'[0-9]{1,9}',text) and int(text)>0:return int(text)
    parsed=urlparse(text)
    if parsed.scheme in ('http','https') and parsed.hostname=='klavogonki.ru':
        match=re.fullmatch(r'/([0-9]{1,9})(?:/[^?]*)?',parsed.fragment) if parsed.path in ('/u/','/u') else None
        if match and int(match[1])>0:return int(match[1])
    raise ValueError('Укажите числовой ID или ссылку вида https://klavogonki.ru/u/#/123456/stats/.')


def active(path=None):
    settings=Path(path or core.DB).parent/'settings.json'
    if settings.exists():
        try:return get(profile_id(json.loads(settings.read_text(encoding='utf-8'))['profile_id']),path)['id']
        except (ValueError,KeyError,TypeError):return None
    # Preserve the choice for an existing single-user installation. A fresh
    # database has no profiles or personal rows and always needs an explicit ID.
    with core.connect(path) as c:
        rows=c.execute('SELECT p.id FROM app_profiles p WHERE EXISTS(SELECT 1 FROM app_current s WHERE s.user_id=p.id) OR EXISTS(SELECT 1 FROM app_goals g WHERE g.user_id=p.id) OR EXISTS(SELECT 1 FROM app_groups g WHERE g.builtin=0 AND g.user_id=p.id)').fetchall()
    return rows[0][0] if len(rows)==1 else None


def select(value,path=None):
    identifier=profile_id(value)
    create(identifier,path)
    settings=Path(path or core.DB).parent/'settings.json'
    # Replace one complete settings file; interrupted writes leave the old one.
    fd,temp=tempfile.mkstemp(prefix='settings-',suffix='.tmp',dir=settings.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump({'profile_id':identifier},f)
        os.replace(temp,settings)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return get(identifier,path)
