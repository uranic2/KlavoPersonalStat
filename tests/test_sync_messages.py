import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import goals
import history
import profiles
import vocabulary


class SyncMessageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'stats.sqlite3';core.init_db(self.db)
        profiles.create(999,self.db);profiles.create(1000,self.db)
        self.group=core.save_group(dict(name='Test',dictionaries='812 853'),self.db,999)
        with core.connect(self.db) as c:
            c.execute("UPDATE app_vocs SET name='First' WHERE id=812")
            c.execute("UPDATE app_vocs SET name='Second' WHERE id=853")
        self.messages=[]
        self.refresh=patch('profiles.refresh_optional');self.refresh.start();self.addCleanup(self.refresh.stop)

    def reply(self,endpoint,**params):
        if endpoint=='get-stats-overview':return dict(ok=1,gametypes={'voc-812':{},'voc-853':{}})
        if endpoint=='get-stats-details':return dict(ok=1,gametype={'name':'Loaded '+params['gametype']},info={})
        if endpoint=='get-stats-details-data':return dict(ok=1,list=[])
        raise AssertionError(endpoint)

    def progress(self,**kw):
        self.messages.append(kw)
        if kw['message'].startswith('Загружены данные'):
            with core.connect(self.db) as c:self.assertEqual(c.execute('SELECT state FROM app_runs ORDER BY id DESC').fetchone()[0],'done')

    def test_alias_profile_order_duplicates_and_actual_clipped_period(self):
        vocabulary.save(dict(id=812,short_name='<Мой & словарь>'),self.db,999)
        vocabulary.save(dict(id=812,short_name='Другой профиль'),self.db,1000)
        with patch('core.api',side_effect=self.reply) as api:
            history.sync_vocs([812,853,812],'2026-11-01','2026-12-01',self.progress,self.db,999,dt.date(2026,11,6))
        message=self.messages[-1]
        self.assertEqual(message['done'],2);self.assertEqual(message['total'],2)
        self.assertEqual(message['message'],'Загружены данные о результатах заездов для словарей: «<Мой & словарь>» (№812), «Loaded voc-853» (№853) за период с 01.11.2026 по 06.11.2026 включительно.')
        for call in api.call_args_list:
            self.assertEqual(call.kwargs['userId'],999)
            if 'toDate' in call.kwargs:self.assertEqual(call.kwargs['toDate'],'2026-11-06')

    def test_one_day_without_races_still_reports_dictionary(self):
        with patch('core.api',return_value=dict(ok=1,gametypes={})),patch('core.fetch') as fetch:
            history.sync_vocs([812],'2026-11-01','2026-11-01',self.progress,self.db,999)
        fetch.assert_not_called()
        self.assertEqual(self.messages[-1]['message'],'Загружены данные о результатах заездов для словаря «First» (№812) за 01.11.2026.')

    def test_empty_and_future_do_not_fetch_or_report_success(self):
        with patch('core.api') as api:
            history.sync_vocs([],'2026-11-01','2026-11-02',self.progress,self.db,999)
            history.sync_vocs([812],'2027-01-01','2027-01-02',self.progress,self.db,999,dt.date(2026,11,6))
        api.assert_not_called()
        self.assertEqual(self.messages[0]['message'],'Нет словарей для загрузки.')
        self.assertIn('Период ещё не начался',self.messages[-1]['message'])
        self.assertFalse(any(x['message'].startswith('Загружены данные') for x in self.messages))

    def test_failed_fetch_does_not_emit_success_or_replace_saved_results(self):
        with patch('core.api',side_effect=self.reply):
            history.sync_vocs([812],'2026-11-01','2026-11-03',self.progress,self.db,999)
        with core.connect(self.db) as c:before=[tuple(r) for r in c.execute('SELECT * FROM app_current')]
        self.messages.clear()
        with patch('core.api',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):history.sync_vocs([812],'2026-11-01','2026-11-03',self.progress,self.db,999)
        self.assertFalse(any(x['message'].startswith('Загружены данные') for x in self.messages))
        with core.connect(self.db) as c:self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM app_current')])

    def test_group_and_goal_use_their_own_dictionary_set_and_dates(self):
        with patch('core.api',side_effect=self.reply),patch('core.period',return_value=('2026-10-01','2026-10-02')):
            core.sync(self.group,self.progress,self.db,999)
        self.assertIn('№812',self.messages[-1]['message']);self.assertIn('№853',self.messages[-1]['message'])
        self.assertIn('с 01.10.2026 по 02.10.2026',self.messages[-1]['message'])
        goal=goals.save(dict(name='Goal',period_type='fixed',date_from='2026-11-01',date_to='2026-11-03',items=[dict(id=853,mode='speed',speed=300)]),self.db,999)
        with patch('core.api',side_effect=self.reply):goals.sync(goal,self.progress,self.db,dt.date(2026,11,6),999)
        self.assertNotIn('№812',self.messages[-1]['message']);self.assertIn('№853',self.messages[-1]['message'])
        self.assertIn('с 01.11.2026 по 03.11.2026',self.messages[-1]['message'])

    def test_unknown_name_and_long_list_are_not_truncated(self):
        items=[dict(id=1,name='Словарь 1'),dict(id=2,name=''),dict(id=3,name='Словарь №3')]
        items.extend(dict(id=i,name='Название'*30) for i in range(4,104))
        message=history.sync_message(items,'2026-11-01','2026-11-01')
        self.assertIn('Словарь №1, Словарь №2, Словарь №3',message)
        self.assertNotIn('Словарь №1 (№1)',message)
        self.assertIn('№103',message);self.assertEqual(message.count('Название'*30),100)
