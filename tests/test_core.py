import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core
import profiles


def timestamp(date):
    return {'sec':int(dt.datetime.fromisoformat(date).replace(tzinfo=core.MSK).timestamp())}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.profile_refresh=patch('profiles.refresh_optional');self.profile_refresh.start();self.addCleanup(self.profile_refresh.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'stats.sqlite3'
        core.init_db(self.db);profiles.create(core.USER_ID,self.db)

    def tearDown(self):
        self.temp.cleanup()

    def group(self,ids='812 853'):
        return core.save_group({'name':'Тестовая группа','dictionaries':ids},self.db)

    def test_month_boundaries(self):
        self.assertEqual(core.period(dt.date(2026,3,31)),('2026-02-28','2026-03-31'))
        self.assertEqual(core.period(dt.date(2024,3,31)),('2024-02-29','2024-03-31'))
        self.assertEqual(core.period(dt.date(2026,1,3)),('2025-12-03','2026-01-03'))

    def test_forum_uses_first_post_rendered_text_and_game_links(self):
        source='''<a name="post1"></a><div class="text">1 - Б.НК.1 - <a href="/create/?gametype=voc&amp;voc=176053">Обычный, 10 сек</a>, <a href="/vocs/176053/top/week/">Рекорды</a><br><a href="/vocs/812/">Моя сильная левая рука</a></div><textarea><a href="/vocs/999/">Редактор</a></textarea><a name="post2"></a><div class="text"><a href="/vocs/123/">Комментарий</a></div>'''
        self.assertEqual(core.parse_forum(source),[{'id':176053,'name':'Б.НК.1'},{'id':812,'name':'Моя сильная левая рука'}])

    def test_custom_group_deduplicates_and_persists(self):
        gid=self.group('812 https://klavogonki.ru/vocs/812/ 853')
        data=core.dashboard(gid,self.db)
        self.assertEqual({r['id'] for r in data['rows']},{812,853})
        core.save_group({'id':gid,'name':'Переименована','dictionaries':'812'},self.db)
        self.assertEqual(len(core.dashboard(gid,self.db)['rows']),1)
        self.assertEqual(next(g for g in core.dashboard(path=self.db)['groups'] if g['id']==gid)['name'],'Переименована')
        core.delete_group(gid,self.db)
        self.assertFalse(any(g['id']==gid for g in core.dashboard(path=self.db)['groups']))
        with core.connect(self.db) as conn:
            self.assertIsNotNone(conn.execute('SELECT 1 FROM app_vocs WHERE id=812').fetchone())

    def test_invalid_group_and_source_do_not_change_data(self):
        before=core.dashboard(path=self.db)['groups']
        for body in [{'name':'','dictionaries':'812'},{'name':'x','dictionaries':'https://evil.example/vocs/812/'},{'name':'x','dictionaries':''}]:
            with self.assertRaises(ValueError):core.save_group(body,self.db)
        for url in ['http://127.0.0.1/forum/academy/123/','https://klavogonki.ru.evil.example/forum/academy/123/']:
            with self.assertRaises(ValueError):core.topic_url(url)
        self.assertEqual(before,core.dashboard(path=self.db)['groups'])
        with self.assertRaises(ValueError):core.delete_group(1,self.db)

    def test_group_source_import_unions_manual_ids(self):
        original=next(r['name'] for r in core.dashboard(1,self.db)['rows'] if r['id']==812)
        source='<a name="post1"></a><div class="text"><a href="/vocs/812/">Левая</a></div><a name="post2"></a>'
        with patch('core.fetch',return_value=source):
            gid=core.save_group({'name':'Импорт','source_url':'https://klavogonki.ru/forum/academy/297/','import_source':True,'dictionaries':'812 853'},self.db)
        self.assertEqual({r['id'] for r in core.dashboard(gid,self.db)['rows']},{812,853})
        self.assertEqual(next(r['name'] for r in core.dashboard(gid,self.db)['rows'] if r['id']==812),original)

    def responses(self):
        return [
            {'ok':1,'gametypes':{'voc-812':{'name':'Левая'}}},
            {'ok':1,'gametype':{'name':'Левая'},'info':{'best_speed':308,'num_races':5,'avg_speed':270,'updated':'2026-11-03 12:00:00'},'best_speed_post':{'message':{'speed':308},'date':timestamp('2026-10-26T15:58:12')}},
            {'ok':1,'list':[{'date':timestamp('2026-10-26T00:00:00'),'max_speed':308,'avg_speed':280,'cnt':3},{'date':timestamp('2026-11-02T00:00:00'),'max_speed':308,'avg_speed':290,'cnt':2}]}
        ]

    def test_sync_uses_record_post_and_daily_maxima_without_duplicates(self):
        gid=self.group('812 853')
        with patch('core.api',side_effect=self.responses()),patch('core.period',return_value=('2026-10-03','2026-11-03')):
            core.sync(gid,path=self.db)
            result=core.dashboard(gid,self.db)
        row=next(r for r in result['rows'] if r['id']==812)
        self.assertEqual((row['record'],row['record_date'],row['month_max'],row['month_date'],row['month_races']),(308,'2026-10-26',308,'2026-10-26',5))
        unplayed=next(r for r in result['rows'] if r['id']==853)
        self.assertIsNone(unplayed['record'])
        self.assertIsNotNone(unplayed['fetched_at'])
        with patch('core.api',side_effect=self.responses()),patch('core.period',return_value=('2026-10-03','2026-11-03')):
            core.sync(gid,path=self.db)
            self.assertEqual(next(r for r in core.dashboard(gid,self.db)['rows'] if r['id']==812)['month_races'],5)

    def test_failed_sync_preserves_previous_statistics(self):
        gid=self.group('812')
        with patch('core.api',side_effect=self.responses()),patch('core.period',return_value=('2026-10-03','2026-11-03')):
            core.sync(gid,path=self.db)
        with core.connect(self.db) as conn:
            before=[tuple(r) for r in conn.execute('SELECT * FROM app_current')]
            days=[tuple(r) for r in conn.execute('SELECT * FROM daily_stats')]
        with patch('core.api',side_effect=[self.responses()[0],RuntimeError('Network offline')]):
            with self.assertRaises(RuntimeError):core.sync(gid,path=self.db)
        with core.connect(self.db) as conn:
            self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT * FROM app_current')])
            self.assertEqual(days,[tuple(r) for r in conn.execute('SELECT * FROM daily_stats')])
            self.assertEqual(conn.execute('SELECT state FROM app_runs ORDER BY id DESC LIMIT 1').fetchone()[0],'error')

    def test_all_groups_deduplicate_dictionary_memberships(self):
        self.group('812 853')
        rows=core.dashboard(path=self.db)['rows']
        self.assertEqual(len(rows),len({r['id'] for r in rows}))


if __name__=='__main__':unittest.main()
