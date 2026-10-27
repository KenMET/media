import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from media_mcp.adapters.jackett import Jackett
from media_mcp.application.acquire import MediaService, rejection_reason
from test_acquire import MemoryRecords

IDENTITY = {'title_id': 'movie:157336', 'kind': 'movie', 'title': '星际穿越',
            'original_title': 'Interstellar', 'date': '2014-11-04'}


def release(name, **extra):
    return {'name': name, 'download_url': 'private', 'resolution': 1080,
            'indexer_id': 'fixture', 'categories': [2000], **extra}


class ReleaseSearchTests(unittest.TestCase):
    def test_public_episode_search_falls_back_to_title_without_changing_scope(self):
        identity = {'title_id':'tv:1','tmdb_id':1,'kind':'tv','title':'测试剧集',
                    'original_title':'テスト','english_title':'Example Show'}
        tmdb = Mock(); tmdb.detail.return_value = identity
        tmdb.get.return_value = {'episodes':[{'episode_number':1,'name':'Pilot'}]}
        indexer = Mock()
        def search(query,kind):
            rows = [release('Example.Show.01.1080p',categories=[5000])] if query == 'Example Show' else []
            return {'releases':rows,'diagnostics':[{'site':'public','status':'ok','raw_count':len(rows)}]}
        indexer.search.side_effect = search
        result = MediaService(MemoryRecords(),tmdb,indexer).search_releases('tv:1',season=1,episodes=[1])
        self.assertEqual(result['scope']['episodes'],[1])
        self.assertEqual(result['scope']['season'],1)
        self.assertEqual(len(result['releases']),1)
        self.assertEqual([call.args[0] for call in indexer.search.call_args_list],
                         ['テスト S01E01','测试剧集 S01E01','Example Show S01E01','テスト','测试剧集','Example Show'])

    def test_search_budget_stops_additional_site_requests(self):
        tmdb = Mock(); tmdb.detail.return_value = IDENTITY
        indexer = Mock()
        with patch('media_mcp.application.acquire.time.monotonic',side_effect=[0,31]):
            result = MediaService(MemoryRecords(),tmdb,indexer).search_releases('movie:157336')
        indexer.search.assert_not_called()
        self.assertEqual(result['search_status'],'failed')
        self.assertEqual(result['diagnostics'][0]['sites'][0]['status'],'budget_exhausted')

    def test_tmdb_english_alias_uses_same_identity_and_translation_failure_is_optional(self):
        from media_mcp.adapters.tmdb import TMDB
        adapter = TMDB(remote=False)
        base = {'id':1,'name':'测试剧集','original_name':'テスト','original_language':'ja'}
        adapter.get = Mock(side_effect=[base,{'id':1,'name':'Example Show'}])
        self.assertEqual(adapter.detail('tv:1')['english_title'],'Example Show')
        self.assertEqual(adapter.get.call_args.kwargs,{'language':'en-US'})
        adapter.get = Mock(side_effect=[base,RuntimeError('tmdb_unavailable')])
        result = adapter.detail('tv:1')
        self.assertEqual(result['title'],'测试剧集')
        self.assertNotIn('english_title',result)

    def test_claim_filter(self):
        for name in ('Interstellar.2014.1080p', '星际穿越（2014）1080p', 'INTERSTELLAR_2014_1080p'):
            self.assertIsNone(rejection_reason(release(name), IDENTITY))
        for candidate, reason in (
            (release('Frankenstein.2025.1080p'), 'title_mismatch'),
            (release('Interstellar.2023.MP3', categories=[3000]), 'category_mismatch'),
            (release('Interstellar.2023.1080p'), 'year_mismatch'),
            (release('[Yun] Interstellar Journey [1080p]'), 'year_unconfirmed'),
            (release('NotInterstellar.2014'), 'title_mismatch')):
            self.assertEqual(rejection_reason(candidate, IDENTITY), reason)
        self.assertIsNone(rejection_reason(release('Example.S02.2026', categories=[5000]),
            {'kind':'tv', 'title':'Example', 'date':'2020-01-01'}))

    def test_title_numbers_are_not_release_years(self):
        identity={'kind':'movie', 'title':'Blade Runner 2049', 'date':'2017-01-01'}
        self.assertEqual(rejection_reason(release('Blade.Runner.2049.1080p'), identity), 'year_unconfirmed')
        self.assertIsNone(rejection_reason(release('Blade.Runner.2049.2017.1080p'), identity))
        self.assertEqual(rejection_reason(release('Blade.Runner.2049.2018.1080p'), identity), 'year_mismatch')

    def test_multilingual_filter_dedup_and_private_diagnostics(self):
        tmdb=Mock(); tmdb.detail.return_value=IDENTITY
        indexer=Mock()
        indexer.search.return_value={'releases':[
            release('Interstellar.2014.1080p'), release('Other.2025.1080p'),
            release('Interstellar.2023.MP3', categories=[3000])],
            'diagnostics':[{'site':'fixture', 'status':'ok', 'raw_count':3},
                           {'site':'slow', 'status':'jackett_timeout', 'raw_count':0}]}
        records=MemoryRecords()
        result=MediaService(records,tmdb,indexer).search_releases('movie:157336')
        self.assertEqual([c.args[0] for c in indexer.search.call_args_list], ['Interstellar', '星际穿越'])
        self.assertEqual(len(result['releases']),1)
        self.assertEqual(len(records.rows),1)
        self.assertEqual(result['search_status'],'partial')
        self.assertEqual(result['diagnostics'][0]['sites'][0]['filtered_count'],2)
        self.assertEqual(result['diagnostics'][1]['sites'][0]['duplicate_count'],1)
        self.assertNotIn('private',str(result))

    def test_failed_search_is_not_successful_empty_search(self):
        tmdb=Mock(); tmdb.detail.return_value=IDENTITY
        indexer=Mock(); indexer.search.return_value={'releases':[], 'diagnostics':[
            {'site':'fixture','status':'jackett_timeout','raw_count':0}]}
        result=MediaService(MemoryRecords(),tmdb,indexer).search_releases('movie:157336')
        self.assertEqual(result['search_status'],'failed')
        self.assertEqual(result['releases'],[])

    def test_sites_isolated_category_and_timeout_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'ServerConfig.json'; config.write_text('{"APIKey":"secret"}')
            sites=Path(directory)/'Indexers'; sites.mkdir()
            for site in ('bad','good'):(sites/(site+'.json')).write_text('{}')
            (sites/'ignored.json.bak').write_text('{}')
            response=Mock(); response.content=b'<rss><channel><item><title>Interstellar.2014</title><link>private</link></item></channel></rss>'
            response.iter_content.return_value=[response.content]
            session=Mock(); session.get.side_effect=[requests.Timeout('secret URL'),response]
            with patch.dict(os.environ, {'JACKETT_CONFIG_FILE':str(config),'JACKETT_API_KEY':''}):
                result=Jackett(session).search('Interstellar',kind='movie')
            self.assertEqual(len(result['releases']),1)
            self.assertEqual(result['diagnostics'][0]['status'],'jackett_timeout')
            self.assertNotIn('secret',str(result))
            self.assertEqual(session.get.call_count,2)
            for call in session.get.call_args_list:
                self.assertEqual(call.kwargs['params']['cat'],2000)
                self.assertLessEqual(call.kwargs['timeout'],5)
                self.assertNotIn('/all/',call.args[0])

    def test_invalid_feed_is_not_a_successful_empty_result(self):
        for payload in (b'<html>Login required</html>', b'<error code="100"/>',
                        b'<!DOCTYPE rss [<!ENTITY x "secret">]><rss>&x;</rss>'):
            session=Mock(); session.get.return_value.iter_content.return_value=[payload]
            with patch.dict(os.environ, {'JACKETT_API_KEY':'secret'}):
                with self.assertRaises(RuntimeError):
                    Jackett(session)._search_site('Example','fixture','movie',5)

    def test_feed_size_limit_is_enforced_while_streaming(self):
        session=Mock(); response=session.get.return_value
        response.iter_content.return_value=iter([b'x'*(4*1024*1024), b'x', b'unread'])
        with patch.dict(os.environ, {'JACKETT_API_KEY':'secret'}):
            with self.assertRaisesRegex(RuntimeError,'jackett_search_failed'):
                Jackett(session)._search_site('Example','fixture','movie',5)
        response.close.assert_called_once()
        self.assertTrue(session.get.call_args.kwargs['stream'])
        self.assertEqual(next(response.iter_content.return_value), b'unread')

    def test_no_sites_and_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'ServerConfig.json'; config.write_text('{"APIKey":"secret"}')
            with patch.dict(os.environ, {'JACKETT_CONFIG_FILE':str(config),'JACKETT_API_KEY':''}):
                adapter=Jackett(Mock())
                self.assertEqual(adapter.search('Example')['diagnostics'][0]['status'],'no_configured_sites')
                sites=Path(directory)/'Indexers'; sites.mkdir(); (sites/'one.json').write_text('{}')
                with patch('media_mcp.adapters.jackett.time.monotonic',side_effect=[0,21]):
                    self.assertEqual(adapter.search('Example')['diagnostics'][0]['status'],'budget_exhausted')
                adapter.session.get.assert_not_called()
