import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen

import core
import profiles
import server


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'data'/'stats.sqlite3'

    def test_fresh_install_has_no_personal_data_or_automatic_legacy_import(self):
        root=Path(self.temp.name)/'source';(root/'config').mkdir(parents=True);(root/'legacy').mkdir()
        seed=[dict(name='Public catalog',source_url='',vocs=[dict(id=812,name='Dictionary')])]
        (root/'config'/'builtin_groups.json').write_text(json.dumps(seed),encoding='utf-8')
        (root/'legacy'/'stats.json').write_text(json.dumps({'rows':[dict(id=812,record=999,record_date='2026-01-01',races=123)],'fetched_at':core.now()}),encoding='utf-8')
        with patch('core.ROOT',root):core.init_db(self.db)
        for _ in range(2):
            with core.connect(self.db) as c:
                for table in ('app_profiles','app_goals','app_templates','app_current','daily_stats','app_coverage','app_races','app_raw','app_voc_aliases','app_runs'):
                    self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertIsNone(profiles.active(self.db));core.init_db(self.db)

    def test_profile_can_be_selected_by_id_or_url_and_persists_without_network(self):
        core.init_db(self.db)
        with patch('core.fetch') as fetch:
            selected=profiles.select('https://klavogonki.ru/u/#/123456/stats/',self.db);fetch.assert_not_called()
        self.assertEqual(selected['id'],123456);self.assertEqual(profiles.active(self.db),123456)
        self.assertEqual(json.loads((self.db.parent/'settings.json').read_text())['profile_id'],123456)
        profiles.select('999',self.db);self.assertEqual(profiles.active(self.db),999)
        for invalid in ('','0','-1','1.5','https://evil.example/u/#/123/stats/','https://klavogonki.ru.evil.example/u/#/123/stats/'):
            with self.assertRaises(ValueError):profiles.select(invalid,self.db)
        self.assertEqual(profiles.active(self.db),999)

    def test_empty_install_serves_welcome_page_and_profile_setup_api(self):
        core.init_db(self.db)
        with patch('core.DB',self.db),patch('server.ACTIVE_USER',None):
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{http.server_port}'
            try:
                html=urlopen(base+'/').read().decode();self.assertIn('setup-profile-form',html)
                data=json.load(urlopen(base+'/api/bootstrap'));self.assertIsNone(data['profile'])
                req=Request(base+'/api/profile/select',data=json.dumps({'value':'123456'}).encode(),headers={'X-Klavo-Token':data['token'],'Content-Type':'application/json'})
                self.assertEqual(json.load(urlopen(req))['profile']['id'],123456)
                dashboard=json.load(urlopen(base+'/api/data'))
                self.assertEqual(dashboard['profile']['id'],123456)
                self.assertTrue(all(r['record'] is None and r['month_races']==0 for r in dashboard['rows']))
                self.assertEqual(json.load(urlopen(base+'/api/catalog'))['goals'],[])
            finally:http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main()
