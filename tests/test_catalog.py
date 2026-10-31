import json
import os
from pathlib import Path
import tempfile
import unittest
from email.utils import formatdate
from unittest.mock import MagicMock, Mock, patch

from media_mcp.platform.catalog import Catalog
from media_mcp.storage.client import DatabaseClient


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'MEDIA_DB_PATH':str(Path(self.temp.name)/'state/media.sqlite3')})
        env.start()
        self.addCleanup(env.stop)
        self.now = 10000
        self.tmdb, self.session = Mock(), MagicMock()
        self.catalog = Catalog(DatabaseClient(), self.tmdb, self.session, lambda:self.now)

    def test_pages_are_isolated_and_keep_stale_metadata(self):
        self.tmdb.get.side_effect = lambda path, page: {
            'results':[{'id':page, 'title':str(page)}], 'total_pages':3}
        first = self.catalog.discover(page='1')
        second = self.catalog.discover(page='2')
        self.assertEqual(first['items'][0]['title_id'], 'movie:1')
        self.assertEqual(second['items'][0]['title_id'], 'movie:2')
        self.assertTrue(second['has_next'])
        self.assertEqual(second['total_pages'], 3)
        self.assertEqual(self.catalog.discover(page=1), first)
        self.now += 10801
        self.tmdb.get.side_effect = RuntimeError('tmdb_unavailable')
        stale = self.catalog.discover(page=2)
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['items'], second['items'])
        self.assertEqual(stale['total_pages'], 3)
        unavailable = self.catalog.discover(page=3)
        self.assertEqual(unavailable['items'], [])
        self.assertFalse(unavailable['has_next'])

    def test_invalid_pages_do_not_call_provider(self):
        for page in (0, -1, 501, True, 1.5, '01', 'bad'):
            with self.subTest(page=page), self.assertRaises(ValueError):
                self.catalog.discover(page=page)
        self.tmdb.get.assert_not_called()

    def test_simkl_all_hundred_items_share_cache_across_pages(self):
        self.simkl_response([{'title':str(i), 'ids':{'simkl_id':i}}
                             for i in range(1, 101)])
        first = self.catalog.discover('simkl', page=1)
        last = self.catalog.discover('simkl', page=5)
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(last['items'][0]['rank'], 81)
        self.assertEqual(last['items'][-1]['rank'], 100)
        self.assertEqual(last['total_pages'], 5)
        self.assertFalse(last['has_next'])
        self.assertEqual(self.session.get.call_count, 1)

    def test_known_title_detail_cache_and_stale_fallback(self):
        self.tmdb.get.return_value={'id':123,'name':'Known','poster_path':'/known.jpg'}
        first=self.catalog.detail('tv:123')
        self.assertEqual(first['poster_url'],'https://image.tmdb.org/t/p/w342/known.jpg')
        self.assertEqual(self.catalog.detail('tv:123'),first)
        self.tmdb.get.assert_called_once_with('tv/123')
        self.now+=86401;self.tmdb.get.side_effect=RuntimeError('tmdb_unavailable')
        self.assertEqual(self.catalog.detail('tv:123'),first)
        self.assertEqual(self.catalog.detail('tv:123'),first)
        self.assertEqual(self.tmdb.get.call_count,2)

    def test_detail_rejects_other_identity(self):
        self.tmdb.get.return_value={'id':456,'name':'Other'}
        with self.assertRaisesRegex(ValueError,'provider_identity_mismatch'):
            self.catalog.detail('tv:123')

    def test_tmdb_cache_stale_fallback_and_failure_backoff(self):
        self.tmdb.get.return_value = {'results':[{'id':1, 'title':'Example', 'poster_path':'/a.jpg'}]}
        first = self.catalog.discover()
        self.assertEqual(first['items'][0]['rating_source'], 'TMDB')
        self.catalog.discover()
        self.assertEqual(self.tmdb.get.call_count, 1)
        self.now += 10801
        self.tmdb.get.side_effect = RuntimeError('tmdb_unavailable')
        stale = self.catalog.discover()
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['fetched_at'], first['fetched_at'])
        self.assertEqual(stale['items'], first['items'])
        self.catalog.discover()
        self.assertEqual(self.tmdb.get.call_count, 2)

    def test_douban_preserves_source_and_requires_identity_matching(self):
        response = self.session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({'subjects':[{
            'id':'12345','title':'Example','rate':'8.5',
            'cover':'https://img1.doubanio.com/view/photo/a.jpg'}]}).encode()]
        result = self.catalog.discover('douban')
        item = result['items'][0]
        self.assertEqual(item['rating_source'], 'Douban')
        self.assertIsNone(item['title_id'])
        self.assertTrue(item['requires_identity_match'])

    def test_blocked_douban_does_not_silently_substitute_tmdb(self):
        response = self.session.get.return_value.__enter__.return_value
        response.status_code = 418
        result = self.catalog.discover('douban')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['source'], 'douban')
        self.assertEqual(result['items'], [])
        self.tmdb.get.assert_not_called()

    def simkl_response(self, rows=None):
        response = self.session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {'Last-Modified':formatdate(self.now-60, usegmt=True)}
        response.iter_content.return_value = [json.dumps(rows if rows is not None else [{
            'title':'Actual source title', 'ids':{'simkl_id':123,'tmdb':'456'},
            'poster':'12/abc123', 'release_date':'10/25/2026',
            'ratings':{'simkl':{'rating':8.5}}}]).encode()]
        return response

    def test_simkl_identity_source_time_and_hourly_cache(self):
        self.simkl_response()
        first = self.catalog.discover('simkl', 'movie', 'day')
        item = first['items'][0]
        self.assertEqual((item['title_id'],item['rating_source'],item['rank']), ('movie:456','SIMKL',1))
        self.assertEqual(first['source_updated_at'], self.now-60)
        self.assertEqual(item['date'], '2026-10-25')
        self.assertIn('simkl.in/posters/12/abc123_m.webp',item['poster_url'])
        self.assertEqual(self.session.get.call_args.args[0],
            'https://data.simkl.in/discover/trending/movies/today_100.json')
        self.catalog.discover('simkl','movie','day')
        self.assertEqual(self.session.get.call_count,1)
        self.now += 3601
        self.session.get.return_value.__enter__.return_value.status_code = 503
        stale = self.catalog.discover('simkl','movie','day')
        self.assertEqual(stale['items'], first['items'])
        self.assertEqual(stale['source_updated_at'], first['source_updated_at'])
        self.assertEqual(stale['status'], 'stale')
        self.catalog.discover('simkl','movie','day')
        self.assertEqual(self.session.get.call_count,2)

    def test_simkl_rejects_old_future_missing_dates_and_oversized_response(self):
        for stamp in (self.now-172801, self.now+10000, None):
            with self.subTest(stamp=stamp):
                response = self.simkl_response()
                response.headers = {'Last-Modified':formatdate(stamp,usegmt=True)} if stamp else {}
                self.now += 301
                result = self.catalog.discover('simkl')
                self.assertEqual(result['status'],'unavailable')
                self.assertEqual(result['items'],[])
        response = self.simkl_response()
        response.iter_content.return_value = [b'x'*(2*1024*1024+1)]
        self.now += 301
        self.assertEqual(self.catalog.discover('simkl')['error_code'],'simkl_invalid_response')

    def test_simkl_missing_mapping_requires_selection_and_untrusted_urls_are_dropped(self):
        self.simkl_response([{'title':'Unmapped','ids':{'simkl_id':1,'tmdb':'../../bad'},
                              'poster':'//attacker/a','ratings':{'simkl':{'rating':100}}}])
        item = self.catalog.discover('simkl','tv')['items'][0]
        self.assertTrue(item['requires_identity_match'])
        self.assertIsNone(item['title_id'])
        self.assertIsNone(item['poster_url'])
        self.assertIsNone(item['rating'])

    def test_existing_catalog_cache_gets_non_destructive_metadata_migration(self):
        self.catalog.db.execute('DROP TABLE platform_catalog_cache')
        self.catalog.db.execute('''CREATE TABLE platform_catalog_cache (
            key TEXT PRIMARY KEY,payload TEXT NOT NULL,fetched_at REAL NOT NULL,
            attempted_at REAL NOT NULL DEFAULT 0,error_code TEXT)''')
        self.catalog.db.execute("INSERT INTO platform_catalog_cache VALUES('tmdb:movie:week','[]',1,1,NULL)")
        migrated = Catalog(self.catalog.db, self.tmdb, self.session, lambda:self.now)
        row = migrated.db.execute('SELECT * FROM platform_catalog_cache').mappings().first()
        self.assertEqual(row['fetched_at'],1)
        self.assertIsNone(row['source_updated_at'])
