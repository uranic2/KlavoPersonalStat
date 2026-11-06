import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import core
import goals
import history
import profiles
import server
import vocabulary


class ProfileHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'stats.sqlite3';core.init_db(self.db);profiles.create(core.USER_ID,self.db)
        profiles.create(999,self.db)
        self.profile_refresh=patch('profiles.refresh_optional');self.profile_refresh.start();self.addCleanup(self.profile_refresh.stop)

    def goal(self,user=core.USER_ID,template=False,**kw):
        body=dict(name='Тест',period_type='rolling',rolling='month',items=[dict(id=812,mode='errors',speed=300,max_errors=1)])
        body.update(kw);return goals.save(body,self.db,user,template)

    def test_profile_isolation_for_goals_groups_aliases_templates_and_history(self):
        a=self.goal();b=self.goal(999);t=self.goal(template=True)
        vocabulary.save(dict(id=812,short_name='A'),self.db)
        vocabulary.save(dict(id=812,short_name='B'),self.db,999)
        group=core.save_group(dict(name='private',dictionaries='812'),self.db)
        with core.connect(self.db) as c:
            c.execute('INSERT INTO daily_stats VALUES(?,?,?,?,?,?,?)',(999,812,'2026-11-03',900,800,2,core.now()))
            goals.cover(c,812,'daily','2026-11-03','2026-11-03',core.now(),999)
        self.assertNotIn(group,[g['id'] for g in core.dashboard(path=self.db,user_id=999)['groups']])
        for fn in [lambda:goals.dashboard(a,self.db,user_id=999),lambda:goals.delete(a,self.db,999),lambda:goals.definition(t,self.db,999,True),lambda:core.delete_group(group,self.db,999)]:
            with self.assertRaises(ValueError):fn()
        self.assertEqual(goals.dashboard(a,self.db)['rows'][0]['short_name'],'A')
        self.assertEqual(goals.dashboard(b,self.db,user_id=999)['rows'][0]['short_name'],'B')
        self.assertIsNone(history.chart(812,'2026-11-03','2026-11-03',self.db)['rows'][0]['max_speed'])
        self.assertEqual(history.chart(812,'2026-11-03','2026-11-03',self.db,999)['rows'][0]['max_speed'],900)
        self.assertEqual(goals.catalog(self.db,999)['templates'],[])

    def test_migration_preserves_existing_owners_and_is_repeatable(self):
        old=Path(self.temp.name)/'old.sqlite3'
        with patch('profiles.migrate'):core.init_db(old)
        vocabulary_name='Старое имя'
        with core.connect(old) as c:
            c.execute('INSERT INTO app_voc_aliases VALUES(?,?)',(812,vocabulary_name))
            c.execute('INSERT OR REPLACE INTO daily_stats VALUES(?,?,?,?,?,?,?)',(999,812,'2026-11-03',999,800,1,core.now()))
        profiles.migrate(old);profiles.migrate(old)
        self.assertEqual(profiles.get(999,old)['id'],999)
        self.assertEqual(len(list(old.parent.glob('backups/before-profiles-*.sqlite3'))),2) # one for each DB in this fixture
        with core.connect(old) as c:
            self.assertEqual(c.execute('SELECT user_id FROM daily_stats WHERE max_speed=999').fetchone()[0],999)
            self.assertEqual(c.execute('SELECT short_name FROM app_voc_aliases WHERE user_id=? AND voc_id=812',(core.USER_ID,)).fetchone()[0],vocabulary_name)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_templates_create_independent_goals_and_fixed_dates_are_required(self):
        t=self.goal(template=True)
        d=goals.definition(t,self.db,template=True);d.pop('id')
        a=goals.save(d,self.db);b=goals.save(d,self.db)
        goals.save(d|{'id':a,'items':[dict(id=812,mode='speed',speed=999)]},self.db)
        goals.delete(t,self.db,template=True)
        self.assertEqual(goals.definition(b,self.db)['items'][0]['speed'],300)
        fixed=self.goal(template=True,period_type='fixed',date_from='2020-01-01',date_to='2020-01-02')
        d=goals.definition(fixed,self.db,template=True);d.pop('id')
        self.assertIsNone(d['date_from'])
        with self.assertRaises(ValueError):goals.save(d,self.db)

    def test_single_sync_requests_only_one_vocabulary_and_commits_atomically(self):
        sec=int(dt.datetime(2026,11,3,tzinfo=core.MSK).timestamp())
        replies=[dict(ok=1,gametypes={'voc-812':{},'voc-853':{}}),dict(ok=1,gametype={'name':'Test'},info={'best_speed':400,'num_races':2}),dict(ok=1,list=[dict(date={'sec':sec},max_speed=400,avg_speed=350,cnt=2)])]
        with patch('core.api',side_effect=replies) as api:
            history.sync_vocs([812],'2026-11-03','2026-11-03',path=self.db,user_id=999)
        self.assertTrue(all(c.kwargs.get('userId')==999 for c in api.call_args_list))
        self.assertFalse(any(c.kwargs.get('gametype')=='voc-853' for c in api.call_args_list))
        with core.connect(self.db) as c:
            before=[tuple(r) for r in c.execute('SELECT * FROM daily_stats WHERE user_id=999')]
            self.assertEqual(c.execute('SELECT user_id FROM app_runs ORDER BY id DESC').fetchone()[0],999)
        with patch('core.api',side_effect=[replies[0],RuntimeError('offline')]):
            with self.assertRaises(RuntimeError):history.sync_vocs([812],'2026-11-03','2026-11-03',path=self.db,user_id=999)
        with core.connect(self.db) as c:self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM daily_stats WHERE user_id=999')])

    def test_chart_distinguishes_zero_races_unknown_days_and_future(self):
        with core.connect(self.db) as c:goals.cover(c,812,'daily','2026-11-01','2026-11-01',core.now(),999)
        d=history.chart(812,'2026-11-01','2026-11-03',self.db,999,today=dt.date(2026,11,2))
        self.assertEqual([r['races'] for r in d['rows']],[0,None,None]);self.assertFalse(d['complete'])
        with patch('core.api') as api:
            history.sync_vocs([812],'2027-01-01','2027-01-02',path=self.db,today=dt.date(2026,11,3));api.assert_not_called()

    def test_word_counts_unicode_occurrences_duplicates_and_invalid_evidence(self):
        text="Ёж, ёж! еЖ; по-русски l'amour"
        races=[dict(race_key='1',text=text,positions=[0,1,4,8,12,22]),dict(race_key='1',text=text,positions=[0]),dict(race_key='2',text='ЁЖ',positions=[0]),dict(race_key='3',text='ошибка',positions=[999])]
        ranked,processed,skipped=history.word_counts(races)
        self.assertEqual(ranked[0],('ёж',3));self.assertEqual(processed,2);self.assertEqual(skipped,1)
        self.assertIn(('еж',1),ranked);self.assertIn(('по-русски',1),ranked);self.assertIn(("l'amour",1),ranked)
        ranked,_,_=history.word_counts([dict(race_key='unicode',text='е\u0308ж ЁЖ',positions=[1,4])])
        self.assertEqual(ranked,[('ёж',2)])

    def test_record_badge_inclusive_boundaries_unknown_date_and_unmet_errors(self):
        gid=self.goal(period_type='fixed',date_from='2026-11-01',date_to='2026-11-03')
        for date,expected in [('2026-11-01',True),('2026-11-03',True),('2026-10-31',False),(None,False)]:
            with core.connect(self.db) as c:
                c.execute('INSERT OR REPLACE INTO app_current VALUES(?,?,?,?,?,?,?,?)',(core.USER_ID,812,400,date,1,None,None,core.now()))
            row=goals.dashboard(gid,self.db,dt.date(2026,11,3))['rows'][0]
            self.assertEqual(row['record_in_period'],expected)
            self.assertEqual(row['achievement_speed'],400 if expected else None)
            self.assertNotEqual(row['status'],'done')

    def test_background_update_captures_profile_instead_of_later_default(self):
        started=threading.Event();finish=threading.Event();seen=[]
        def worker(*args,**kw):started.set();finish.wait(2);seen.append(kw['user_id'])
        with patch('core.DB',self.db),patch('history.sync_vocs',side_effect=worker),patch('server.ACTIVE_USER',999):
            server.start_sync(None,user_id=999,voc_id=812)
            self.assertTrue(started.wait(2));server.ACTIVE_USER=core.USER_ID;finish.set()
            self.assertTrue(server.LOCK.acquire(timeout=3));server.LOCK.release()
        self.assertEqual(seen,[999]);self.assertEqual(server.STATE['user_id'],999)

    def test_word_analysis_gating_does_not_report_zero_errors(self):
        with patch('core.fetch',return_value='{"err":"not pro"}'):
            d=history.analyze(812,'2026-11-03','2026-11-03',path=self.db,user_id=999)
        self.assertEqual(d['state'],'unavailable');self.assertFalse(d['analysis_complete']);self.assertIn('Premium',d['message']);self.assertEqual(d['words'],[])
        for n in [0,101,1.5,True]:
            with self.assertRaises(ValueError):history.analyze(812,'2026-11-03','2026-11-03',n,self.db)

    def test_complete_and_partial_word_evidence_are_profile_scoped(self):
        with core.connect(self.db) as c:
            c.execute('INSERT INTO app_word_evidence VALUES(?,?,?,?,?,?)',(999,812,'r1','2026-11-03T10:00:00+03:00','Тест тест','[0, 1, 5]'))
            goals.cover(c,812,'words','2026-11-03','2026-11-03',core.now(),999)
        with patch('history.probe') as probe:d=history.analyze(812,'2026-11-03','2026-11-03',path=self.db,user_id=999);probe.assert_not_called()
        self.assertTrue(d['analysis_complete']);self.assertEqual(d['words'],[{'word':'тест','count':2}])
        with patch('history.probe',return_value='Нет позиций'):
            other=history.analyze(812,'2026-11-03','2026-11-03',path=self.db)
        self.assertEqual(other['words'],[])

    def test_name_change_and_failure_preserve_profile_identity(self):
        with patch('core.fetch',return_value=json.dumps({'user':{'id':999,'login':'<Имя>'}})):
            self.assertEqual(profiles.refresh(999,self.db)['name'],'<Имя>')
        with patch('core.fetch',side_effect=RuntimeError('offline')):
            self.profile_refresh.stop()
            self.assertEqual(profiles.refresh_optional(999,self.db)['name'],'<Имя>')

    def test_http_profile_export_and_cross_profile_goal_access(self):
        goal=self.goal();other=self.goal(999)
        with patch('core.DB',self.db):
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{http.server_port}'
            try:
                with self.assertRaises(HTTPError):urlopen(base+f'/api/goal?id={goal}&profile=999')
                data=json.load(urlopen(base+f'/api/goal?id={other}&profile=999'));self.assertEqual(data['goal']['user_id'],999)
                csv=urlopen(base+f'/api/export?goal={other}&profile=999').read().decode('utf-8-sig');self.assertIn('Требуемая скорость',csv)
                body=json.dumps({'id':goal,'profile':999}).encode()
                with self.assertRaises(HTTPError):urlopen(Request(base+'/api/goals/delete',data=body,headers={'X-Klavo-Token':server.TOKEN,'Content-Type':'application/json'}))
            finally:http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main()
