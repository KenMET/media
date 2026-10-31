import unittest
import tempfile
import zipfile
import os
from io import BytesIO
from unittest.mock import patch

from media_mcp.adapters.subtitle.assrt import AssrtProvider, _default_cache_dir, _file_matches_episode, _query_variants
from media_mcp.subtitle.providers.base import DownloadedSubtitle, OnlineSubtitleCandidate, SubtitleSearchRequest


class _Response:
    def __init__(self, text=''):
        self.text = text

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError('unexpected HTTP request')
        return _Response(self.responses.pop(0))


class AssrtProviderTest(unittest.TestCase):
    def test_default_cache_dir_is_persistent_and_configurable(self):
        with patch.dict('os.environ', {'MEDIA_CACHE_DIR': os.path.join('cache', 'media')}, clear=True):
            self.assertEqual(_default_cache_dir(), os.path.join('cache', 'media', 'assrt'))
        with patch.dict('os.environ', {'PHANTOM_CACHE_DIR': os.path.join('cache', 'phantom')}, clear=True):
            self.assertEqual(_default_cache_dir(), os.path.join('cache', 'phantom', 'assrt'))
        with patch.dict('os.environ', {'ASSRT_CACHE_DIR': os.path.join('cache', 'assrt')}, clear=True):
            self.assertEqual(_default_cache_dir(), os.path.join('cache', 'assrt'))

    def test_query_variants_keep_short_cjk_title(self):
        request = SubtitleSearchRequest(
            media_type='tv',
            tmdb_id=26867,
            title='\u866b\u5e08',
            year=None,
            season=1,
            episode=6,
            languages=('zh-cn',),
        )

        self.assertEqual(_query_variants(request), ['\u866b\u5e08 S01 E06', '\u866b\u5e08'])

    def test_file_matches_episode_rejects_conflicting_sxe_before_loose_numbers(self):
        request = SubtitleSearchRequest(
            media_type='tv',
            tmdb_id=226529,
            title='Light Shop',
            year=2024,
            season=1,
            episode=5,
            languages=('zh-cn',),
        )

        self.assertFalse(
            _file_matches_episode(
                'Light.Shop.S01E08.1080p.DSNP.WEB-DL.DDP5.1.Atmos.H.264-ARiC.srt',
                request,
            )
        )

    def test_file_matches_episode_accepts_unpadded_explicit_markers(self):
        request = SubtitleSearchRequest(
            media_type='tv',
            tmdb_id=226529,
            title='Light Shop',
            year=2024,
            season=1,
            episode=1,
            languages=('zh-cn',),
        )

        self.assertTrue(_file_matches_episode('Light.Shop.S1E1.zh-CN.srt', request))
        self.assertTrue(_file_matches_episode('Light.Shop.1x1.zh-CN.srt', request))

    def test_web_search_splits_pack_and_filters_wrong_season(self):
        empty_search = '<html></html>'
        title_search = '''
            <a href="/xml/sub/694/694349.xml">\u866b\u5e08 \u7eed\u7ae0</a>
            <a href="/xml/sub/694/694348.xml">\u866b\u5e08 [\u516826\u96c6]</a>
            <a href="/xml/sub/608/608732.xml">[\u866b\u5e08][\u7b2c\u4e00\u5b63+\u7b2c\u4e8c\u5b63]</a>
        '''
        zoku_detail = '''
            <title>\u866b\u5e08 \u7eed\u7ae0</title>
            onclick='onthefly("694349","11","[Kamigami] Mushishi Zoku Shou - 06.ass")'
        '''
        first_season_detail = '''
            <title>\u866b\u5e08 [\u516826\u96c6] \u7b80\u65e5\u53cc\u8bed</title>
            onclick='onthefly("694348","6","[Kamigami] Mushishi - 06 [BD].ass")'
        '''
        mixed_pack_detail = '''
            <title>[\u866b\u5e08][\u7b2c\u4e00\u5b63+\u7b2c\u4e8c\u5b63] \u7b80</title>
            onclick='onthefly("608732","6","[Mushishi Zoku Shou][06].ass")'
            onclick='onthefly("608732","28","[\u6f0f\u52farip][Mushishi][06][BDrip].ass")'
        '''
        provider = AssrtProvider()
        provider.session = _Session([empty_search, title_search, zoku_detail, first_season_detail, mixed_pack_detail])
        request = SubtitleSearchRequest(
            media_type='tv',
            tmdb_id=26867,
            title='\u866b\u5e08',
            year=None,
            season=1,
            episode=6,
            languages=('zh-cn',),
        )

        candidates = provider._web_search(request)

        self.assertEqual([candidate.file_id for candidate in candidates], ['694348:6', '608732:28'])
        self.assertEqual(candidates[1].file_name, '[\u6f0f\u52farip][Mushishi][06][BDrip].ass')

    def test_select_download_url_prefers_exact_pack_member(self):
        provider = AssrtProvider()
        candidate = OnlineSubtitleCandidate(
            provider='assrt',
            candidate_id='608732:28',
            file_id='608732:28',
            file_name='[\u6f0f\u52farip][Mushishi][06][BDrip].ass',
            language='zh-CN',
            subtitle_type='normal',
            format='ass',
            media_type='tv',
            season=1,
            episode=6,
            metadata={'assrt_detail_id': 608732, 'assrt_file_index': '28'},
        )
        detail = {
            'filelist': [
                {'id': '1', 'f': '[Mushishi Zoku Shou][01].ass', 'url': 'wrong'},
                {'id': '28', 'f': '[\u6f0f\u52farip][Mushishi][06][BDrip].ass', 'url': 'right'},
            ]
        }

        url, file_name = provider._select_download_url(detail, candidate)

        self.assertEqual(url, 'right')
        self.assertEqual(file_name, '[\u6f0f\u52farip][Mushishi][06][BDrip].ass')

    def test_download_caches_archive_and_reuses_pack_member(self):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('[Mushishi][06].ass', 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,\u7b2c\u516d\u96c6')
            archive.writestr('[Mushishi][07].ass', 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,\u7b2c\u4e03\u96c6')

        with tempfile.TemporaryDirectory() as cache_dir:
            provider = AssrtProvider()
            provider.cache_dir = cache_dir
            first = OnlineSubtitleCandidate(
                provider='assrt',
                candidate_id='608732:6',
                file_id='608732:6',
                file_name='[Mushishi][06].ass',
                language='zh-CN',
                subtitle_type='normal',
                format='ass',
                media_type='tv',
                season=1,
                episode=6,
                metadata={'assrt_detail_id': 608732, 'assrt_file_index': '6'},
            )
            archive_path = provider._cache_archive('608732', buffer.getvalue(), 'pack.zip')
            provider._cache_member('608732', first, b'cached-single', '[Mushishi][06].ass')

            cached_first = provider._download_from_cache('608732', first)

            self.assertIsInstance(cached_first, DownloadedSubtitle)
            self.assertEqual(cached_first.content, b'cached-single')

            second = OnlineSubtitleCandidate(
                provider='assrt',
                candidate_id='608732:7',
                file_id='608732:7',
                file_name='[Mushishi][07].ass',
                language='zh-CN',
                subtitle_type='normal',
                format='ass',
                media_type='tv',
                season=1,
                episode=7,
                metadata={'assrt_detail_id': 608732, 'assrt_file_index': '7'},
            )

            cached_second = provider._download_from_cache('608732', second)

            self.assertTrue(archive_path.endswith('archive.zip'))
            self.assertIsInstance(cached_second, DownloadedSubtitle)
            self.assertEqual(cached_second.file_name, '[Mushishi][07].ass')
            self.assertIn('\u7b2c\u4e03\u96c6'.encode('utf-8'), cached_second.content)


if __name__ == '__main__':
    unittest.main()
