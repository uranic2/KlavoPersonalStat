import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import core
import profiles
import goals


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.profile_refresh=patch('profiles.refresh_optional');self.profile_refresh.start();self.addCleanup(self.profile_refresh.stop)
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'db.sqlite3';core.init_db(self.db);profiles.create(core.USER_ID,self.db)
        self.today=dt.date(2026,11,3)

    def tearDown(self):self.temp.cleanup()

    def goal(self,mode='speed',speed=400,errors=None,**kw):
        body=dict(name='Моя цель',period_type='fixed',date_from='2026-11-01',date_to='2026-11-03',items=[dict(id=100001,mode=mode,speed=speed,max_errors=errors)])
        body.update(kw);return goals.save(body,self.db)

    def data(self,gid):return goals.dashboard(gid,self.db,self.today)

    def daily(self,speed=400,complete=True):
        with core.connect(self.db) as c:
            c.execute('INSERT OR REPLACE INTO daily_stats VALUES(?,?,?,?,?,?,?)',(core.USER_ID,100001,'2026-11-02',speed,speed,1,'2026-11-03T10:00:00+03:00'))
            if complete:goals.cover(c,100001,'daily','2026-11-01','2026-11-03','2026-11-03T10:00:00+03:00')

    def race(self,key,speed,errors,at='2026-11-02T12:00:00+03:00'):
        with core.connect(self.db) as c:c.execute('INSERT INTO app_races VALUES(?,?,?,?,?,?,?)',(core.USER_ID,100001,str(key),at,speed,errors,'test'))

    def test_achievement_counts_use_individual_eligible_races_in_period(self):
        gid=self.goal('errors',400,1)
        self.daily(500)
        self.race(1,400,0,'2026-11-01T00:00:00+03:00')
        self.race(2,450,1,'2026-11-03T23:59:59+03:00')
        self.race(3,500,2)
        self.race(4,500,None)
        self.race(5,399,0)
        self.race(6,500,0,'2026-10-31T23:59:59+03:00')
        self.race(7,500,0,'2026-11-04T00:00:00+03:00')
        row=self.data(gid)['rows'][0]
        self.assertEqual(row['achievement_count'],2)
        self.assertFalse(row['achievement_count_complete'])
        # Repeated ingestion of the same key replaces evidence, never adds a race.
        with core.connect(self.db) as c:
            c.execute('INSERT OR REPLACE INTO app_races VALUES(?,?,?,?,?,?,?)',(core.USER_ID,100001,'2','2026-11-03T23:59:59+03:00',450,1,'test'))
            goals.cover(c,100001,'races','2026-11-01','2026-11-03',core.now())
        row=self.data(gid)['rows'][0]
        self.assertEqual(row['achievement_count'],2)
        self.assertTrue(row['achievement_count_complete'])

    def test_daily_maximum_does_not_invent_achievement_count(self):
        gid=self.goal();self.daily(450)
        self.assertIsNone(self.data(gid)['rows'][0]['achievement_count'])
        with core.connect(self.db) as c:
            goals.cover(c,100001,'races','2026-11-01','2026-11-03',core.now())
        # Even inconsistent aggregate/race snapshots must never say 'achieved 0 times'.
        self.assertIsNone(self.data(gid)['rows'][0]['achievement_count'])
        with core.connect(self.db) as c:c.execute("DELETE FROM app_coverage WHERE kind='races'")
        self.race(1,400,None)
        self.assertEqual(self.data(gid)['rows'][0]['achievement_count'],1)
        self.assertFalse(self.data(gid)['rows'][0]['achievement_count_complete'])

    def test_boundaries(self):
        for date,key,expected in [(dt.date(2026,3,31),'month','2026-02-28'),(dt.date(2024,3,31),'month','2024-02-29'),(dt.date(2026,1,3),'week','2025-12-28'),(dt.date(2024,2,29),'year','2023-02-28'),(dt.date(2026,11,3),'day','2026-11-03'),(dt.date(2026,11,3),'quarter','2026-08-03'),(dt.date(2026,11,3),'half','2026-05-03')]:
            self.assertEqual(goals.bounds(dict(period_type='rolling',rolling=key),date)[0],expected)

    def test_migration_backup_and_idempotence(self):
        backups=list((self.db.parent/'backups').glob('before-goals-*.sqlite3'));self.assertEqual(len(backups),1)
        c=sqlite3.connect(backups[0]);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');c.close()
        core.init_db(self.db);self.assertEqual(len(list((self.db.parent/'backups').glob('before-goals-*.sqlite3'))),1)

    def test_speed_threshold_and_outside_record(self):
        gid=self.goal();self.race(1,999,0,'2026-10-31T23:59:59+03:00');self.daily(400)
        self.assertEqual(self.data(gid)['rows'][0]['status'],'done')
        self.daily(399);self.assertEqual(self.data(gid)['rows'][0]['status'],'pending')

    def test_errors_must_belong_to_same_race(self):
        gid=self.goal('errors',400,1);self.daily(500);self.race(1,500,5);self.race(2,390,0)
        self.assertEqual(self.data(gid)['rows'][0]['status'],'unverifiable')
        self.race(3,400,1);r=self.data(gid)['rows'][0];self.assertEqual((r['status'],r['best_speed'],r['best_errors']),('done',400,1))

    def test_zero_errors_and_missing_errors_distinct(self):
        gid=self.goal('errors',400,0);self.daily(500);self.race(1,500,None)
        self.assertEqual(self.data(gid)['rows'][0]['status'],'unverifiable')
        self.race(2,400,0);self.assertEqual(self.data(gid)['rows'][0]['status'],'done')
        missing=self.goal('errors',400,None);self.assertEqual(self.data(missing)['rows'][0]['status'],'unconfigured')

    def test_partial_evidence_can_confirm_but_cannot_disprove(self):
        gid=self.goal('errors',400,1);self.daily(500,False);self.race(1,399,0)
        self.assertEqual(self.data(gid)['rows'][0]['status'],'partial')
        self.race(2,400,0);self.assertEqual(self.data(gid)['rows'][0]['status'],'done');self.assertFalse(self.data(gid)['rows'][0]['complete'])

    def test_empty_unloaded_and_future(self):
        gid=self.goal();self.assertEqual(self.data(gid)['rows'][0]['status'],'unloaded')
        with core.connect(self.db) as c:goals.cover(c,100001,'daily','2026-11-01','2026-11-03',core.now())
        self.assertEqual(self.data(gid)['rows'][0]['status'],'empty')
        future=self.goal(date_from='2027-01-01',date_to='2027-01-01');self.assertEqual(self.data(future)['rows'][0]['status'],'future')
        with patch('core.api') as api:goals.sync(future,path=self.db,today=self.today);api.assert_not_called()

    def test_fixed_does_not_slide_rolling_does(self):
        fixed=self.goal();rolling=self.goal(period_type='rolling',rolling='day');self.daily(400)
        self.assertEqual(goals.dashboard(fixed,self.db,dt.date(2027,1,1))['rows'][0]['status'],'done')
        self.assertNotEqual(goals.dashboard(rolling,self.db,dt.date(2026,11,4))['rows'][0]['status'],'done')

    def test_goal_independent_of_group_and_other_goals(self):
        group=core.save_group({'name':'Группа','dictionaries':'100001'},self.db)
        a=self.goal();b=self.goal(speed=500);core.delete_group(group,self.db)
        self.assertEqual(self.data(a)['rows'][0]['id'],100001);goals.delete(a,self.db);self.assertEqual(len(self.data(b)['rows']),1)

    def test_deduplicate_preserves_first_requirement_and_denominator(self):
        gid=self.goal(items=[dict(id=100001,mode='speed',speed=400),dict(id=100001,mode='speed',speed=100),dict(id=100002,mode='speed',speed=None)])
        self.daily(400);d=self.data(gid);self.assertEqual(len(d['rows']),2);self.assertEqual(d['percent'],50);self.assertEqual(d['rows'][0]['speed'],400)

    def test_validation(self):
        for values in [dict(name=''),dict(items=[]),dict(date_from='2026-11-04'),dict(date_to='bad'),dict(items=[dict(id=1,mode='speed',speed=-1)]),dict(items=[dict(id=1,mode='errors',speed=1,max_errors=1.5)]),dict(items=[dict(id=1,mode='speed',speed='NaN')])]:
            with self.assertRaises(ValueError):self.goal(**values)

    def test_union_coverage_detects_gaps(self):
        rows=[dict(date_from='2026-11-01',date_to='2026-11-01',fetched_at='a'),dict(date_from='2026-11-02',date_to='2026-11-03',fetched_at='b')]
        self.assertTrue(goals.coverage(rows,'2026-11-01','2026-11-03')[0]);rows[1]['date_from']='2026-11-03';self.assertFalse(goals.coverage(rows,'2026-11-01','2026-11-03')[0])

    def test_updated_subperiod_uses_latest_refresh_time(self):
        rows=[dict(date_from='2026-10-03',date_to='2026-11-03',fetched_at='2026-11-03T10:00:00'),dict(date_from='2026-11-01',date_to='2026-11-02',fetched_at='2026-11-03T12:00:00')]
        self.assertEqual(goals.coverage(rows,'2026-11-01','2026-11-02'),(True,'2026-11-03T12:00:00'))

    def responses(self):
        sec=int(dt.datetime(2026,11,2,tzinfo=core.MSK).timestamp())
        return [{'ok':1,'gametypes':{'voc-100001':{'name':'Test'}}},{'ok':1,'gametype':{'name':'Test'}},{'ok':1,'list':[dict(date={'sec':sec},max_speed=450,avg_speed=400,cnt=2)]}]

    def test_goal_sync_replaces_data_without_duplicates_and_preserves_on_error(self):
        gid=self.goal()
        for _ in range(2):
            with patch('core.api',side_effect=self.responses()):goals.sync(gid,path=self.db,today=self.today)
        self.assertEqual(self.data(gid)['rows'][0]['month_races'],2)
        with core.connect(self.db) as conn:
            before=[tuple(r) for r in conn.execute('SELECT * FROM daily_stats')]
            coverage=[tuple(r) for r in conn.execute('SELECT * FROM app_coverage')]
        with patch('core.api',side_effect=[self.responses()[0],RuntimeError('offline')]):
            with self.assertRaises(RuntimeError):goals.sync(gid,path=self.db,today=self.today)
        with core.connect(self.db) as conn:
            self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT * FROM daily_stats')])
            self.assertEqual(coverage,[tuple(r) for r in conn.execute('SELECT * FROM app_coverage')])

    def test_chunks_have_no_gaps_or_overlap(self):
        spans=list(goals.chunks('2026-01-01','2026-12-31'))
        self.assertEqual(spans[0][0],'2026-01-01');self.assertEqual(spans[-1][1],'2026-12-31')
        for i,(start,end) in enumerate(spans):
            self.assertLessEqual((dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days,89)
            if i:self.assertEqual(dt.date.fromisoformat(start)-dt.date.fromisoformat(spans[i-1][1]),dt.timedelta(days=1))

    def test_race_ties_and_inclusive_end_date(self):
        gid=self.goal('errors',400,3);self.daily(400);self.race(1,400,2);self.race(2,400,1,'2026-11-03T23:59:59+03:00');self.race(3,999,0,'2026-11-04T00:00:00+03:00')
        row=self.data(gid)['rows'][0];self.assertEqual(row['best_errors'],2);self.assertTrue(row['best_at'].startswith('2026-11-02'))

    def test_record_is_independent_of_period_and_has_only_matching_date(self):
        gid=self.goal();self.daily(400)
        with core.connect(self.db) as c:
            c.execute('INSERT INTO app_current VALUES(?,?,?,?,?,?,?,?)',(core.USER_ID,100001,900,'2026-10-01',1,None,None,core.now()))
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['record'],row['record_date'],row['achievement_speed']),(900,'2026-10-01',400))
        sec=int(dt.datetime(2026,10,2,tzinfo=core.MSK).timestamp())
        details={'info':{'best_speed':950},'best_speed_post':{'date':{'sec':sec},'message':{'speed':949}}}
        with core.connect(self.db) as c:
            run=c.execute("INSERT INTO app_runs(state) VALUES('done')").lastrowid
            c.execute('INSERT INTO app_raw VALUES(?,?,?,?)',(run,100001,'details',json.dumps(details)))
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['record'],row['record_date']),(950,None))
        details['best_speed_post']['message']['speed']=950
        with core.connect(self.db) as c:c.execute('UPDATE app_raw SET payload=? WHERE run_id=?',(json.dumps(details),run))
        self.assertEqual(self.data(gid)['rows'][0]['record_date'],'2026-10-02')

    def test_daily_evidence_does_not_borrow_errors_from_later_equal_race(self):
        gid=self.goal();self.daily(450,False);self.race(1,450,0,'2026-11-03T10:00:00+03:00')
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_speed'],row['achievement_at'],row['achievement_errors'],row['achievement_source']),(450,'2026-11-02',None,'daily'))
        self.assertIn('дневным максимумом',row['reason'])
        self.race(2,450,3,'2026-11-02T15:00:00+03:00')
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_errors'],row['achievement_source']),(3,'race'))

    def test_period_maximum_is_independent_of_goal_qualification(self):
        gid=self.goal('errors',400,1);self.daily(500);self.race(1,500,2);self.race(2,399,0)
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_speed'],row['achievement_errors']),(500,2))
        self.assertEqual(row['best_speed'],399);self.assertNotEqual(row['status'],'done')
        self.race(3,400,1,'2026-11-01T00:00:00+03:00')
        self.race(4,450,1);self.race(5,450,0,'2026-11-03T10:00:00+03:00')
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_speed'],row['achievement_errors'],row['achievement_at']),(500,2,'2026-11-02T12:00:00+03:00'))
        self.assertEqual(row['best_speed'],450);self.assertEqual(row['status'],'done')
        self.assertEqual(row['achievement_count'],3)

    def test_period_maximum_below_speed_requirement_and_without_error_details(self):
        gid=self.goal('errors',600,0);self.daily(500)
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_speed'],row['achievement_source'],row['achievement_errors']),(500,'daily',None))
        self.assertNotEqual(row['status'],'done');self.assertTrue(row['period_complete'])
        self.assertIsNone(row['best_speed'])
        self.race(1,550,5)
        row=self.data(gid)['rows'][0]
        self.assertEqual((row['achievement_speed'],row['achievement_source']),(550,'race'))
        self.assertNotEqual(row['status'],'done')

    def test_achievement_disappears_when_rolling_day_changes(self):
        gid=self.goal(period_type='rolling',rolling='day');self.race(1,400,None,'2026-11-03T10:00:00+03:00')
        row=self.data(gid)['rows'][0]
        self.assertEqual(row['achievement_speed'],400);self.assertIsNone(row['achievement_errors'])
        later=goals.dashboard(gid,self.db,dt.date(2026,11,4))
        self.assertEqual(later['counts']['done'],0);self.assertIsNone(later['rows'][0]['achievement_speed'])

    def test_complete_days_do_not_claim_complete_error_evidence(self):
        gid=self.goal('errors',400,0);self.daily(500);self.race(1,400,0)
        row=self.data(gid)['rows'][0]
        self.assertTrue(row['complete']);self.assertFalse(row['achievement_complete']);self.assertEqual(row['status'],'done')
        with core.connect(self.db) as c:goals.cover(c,100001,'races','2026-11-01','2026-11-03',core.now())
        row=self.data(gid)['rows'][0]
        self.assertTrue(row['achievement_complete']);self.assertEqual(row['reason'],'')


if __name__=='__main__':unittest.main()
