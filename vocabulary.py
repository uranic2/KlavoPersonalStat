"""User-owned dictionary labels, independent of imported dictionary metadata."""
import datetime as dt
from pathlib import Path
import sqlite3

import core


def migrate(path=None):
    target=Path(path or core.DB)
    with core.connect(target) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='app_voc_aliases'").fetchone():return
        folder=target.parent/'backups';folder.mkdir(exist_ok=True)
        backup=sqlite3.connect(folder/('before-short-names-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3'))
        try:conn.backup(backup)
        finally:backup.close()
        conn.execute('''CREATE TABLE app_voc_aliases(voc_id INTEGER PRIMARY KEY REFERENCES app_vocs(id),short_name TEXT NOT NULL CHECK(length(short_name) BETWEEN 1 AND 100))''')


def save(body,path=None,user_id=core.USER_ID):
    identifier=core.voc_id(body.get('id',''))
    name=body.get('short_name','')
    if not identifier or not isinstance(name,str):raise ValueError('Укажите словарь и текст краткого имени.')
    name=name.strip()
    if len(name)>100:raise ValueError('Краткое имя должно содержать не более 100 символов.')
    with core.connect(path) as conn:
        if not conn.execute('SELECT 1 FROM app_vocs WHERE id=?',(identifier,)).fetchone():raise ValueError('Словарь не найден.')
        if name:conn.execute('INSERT INTO app_voc_aliases VALUES(?,?,?) ON CONFLICT(user_id,voc_id) DO UPDATE SET short_name=excluded.short_name',(user_id,identifier,name))
        else:conn.execute('DELETE FROM app_voc_aliases WHERE user_id=? AND voc_id=?',(user_id,identifier))
    return {'id':identifier,'short_name':name}
