import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import core
import profiles
import goals
import vocabulary


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.profile_refresh=patch('profiles.refresh_optional');self.profile_refresh.start();self.addCleanup(self.profile_refresh.stop)
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'stats.sqlite3';core.init_db(self.db);profiles.create(core.USER_ID,self.db)

    def tearDown(self):self.temp.cleanup()

    def test_backup_repeat_migration_preserves_data(self):
        vocabulary.save({'id':853,'short_name':'Правая'},self.db)
        core.init_db(self.db)
        backups=list((self.db.parent/'backups').glob('before-short-names-*.sqlite3'));self.assertEqual(len(backups),1)
        c=sqlite3.connect(backups[0]);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='app_voc_aliases'").fetchone());c.close()
        self.assertEqual(next(v for v in goals.catalog(self.db)['vocs'] if v['id']==853)['short_name'],'Правая')

    def test_shared_by_id_and_original_name_unchanged(self):
        original=next(v for v in goals.catalog(self.db)['vocs'] if v['id']==853)['name']
        vocabulary.save({'id':853,'short_name':'  Правая <рука> "тест"  '},self.db)
        a=goals.save(dict(name='A',period_type='rolling',rolling='month',items=[dict(id=853,mode='speed',speed=300)]),self.db)
        b=goals.save(dict(name='B',period_type='rolling',rolling='day',items=[dict(id=853,mode='speed',speed=350)]),self.db)
        for gid in [a,b]:
            row=goals.dashboard(gid,self.db)['rows'][0];self.assertEqual(row['short_name'],'Правая <рука> "тест"');self.assertEqual(row['name'],original)
        row=next(v for v in core.dashboard(1,self.db)['rows'] if v['id']==853);self.assertEqual(row['short_name'],'Правая <рука> "тест"')

    def test_clear_and_validation(self):
        vocabulary.save({'id':853,'short_name':'A'},self.db)
        vocabulary.save({'id':812,'short_name':'A'},self.db)
        vocabulary.save({'id':853,'short_name':'   '},self.db)
        self.assertEqual(next(v for v in goals.catalog(self.db)['vocs'] if v['id']==853)['short_name'],'')
        for body in [{'id':853,'short_name':'x'*101},{'id':999999999,'short_name':'x'},{'id':853,'short_name':None}]:
            with self.assertRaises(ValueError):vocabulary.save(body,self.db)

    def test_imports_goals_and_refresh_preserve_alias(self):
        vocabulary.save({'id':812,'short_name':'Левая'},self.db)
        group=core.save_group({'name':'Test','dictionaries':'812 100002'},self.db)
        goal=goals.save(dict(name='Test',period_type='rolling',rolling='month',items=[dict(id=812,mode='speed',speed=300),dict(id=100003,mode='speed',speed=300)]),self.db)
        replies=[{'ok':1,'gametypes':{'voc-812':{'name':'New name'}}},{'ok':1,'gametype':{'name':'New name'},'info':{'best_speed':308,'num_races':5,'updated':core.now()}},{'ok':1,'list':[]}]
        with patch('core.api',side_effect=replies),patch('core.fetch',return_value='<title>New Dictionary</title>'):core.sync(group,path=self.db)
        row=next(v for v in core.dashboard(group,self.db)['rows'] if v['id']==812);self.assertEqual((row['name'],row['short_name']),('New name','Левая'))
        self.assertEqual(len(goals.dashboard(goal,self.db)['rows']),2)
        self.assertEqual(next(v for v in goals.catalog(self.db)['vocs'] if v['id']==100002)['short_name'],'')


if __name__=='__main__':unittest.main()
