#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from media_mcp.subtitle.providers.base import DownloadedSubtitle, OnlineSubtitleCandidate
from media_mcp.subtitle.providers.registry import SubtitleProviderRegistry
from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent


class FakeProvider:
    def __init__(self, name, *, search_candidates=None, download_error=None):
        self.name = name
        self.search_candidates = search_candidates or []
        self.download_error = download_error
        self.search_calls = 0
        self.download_calls = 0

    @property
    def configured(self):
        return True

    def search(self, request):
        self.search_calls += 1
        return self.search_candidates

    def download(self, candidate):
        self.download_calls += 1
        if self.download_error:
            raise self.download_error
        return DownloadedSubtitle(
            content=(
                b'1\n'
                b'00:00:01,000 --> 00:00:02,000\n'
                b'\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xb8\x80\xe8\xa1\x8c\xe4\xb8\xad\xe6\x96\x87\xe5\xad\x97\xe5\xb9\x95\n\n'
                b'2\n'
                b'00:00:03,000 --> 00:00:04,000\n'
                b'\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xba\x8c\xe8\xa1\x8c\xe4\xb8\xad\xe6\x96\x87\xe5\xad\x97\xe5\xb9\x95\n\n'
                b'3\n'
                b'00:00:05,000 --> 00:00:06,000\n'
                b'\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xb8\x89\xe8\xa1\x8c\xe4\xb8\xad\xe6\x96\x87\xe5\xad\x97\xe5\xb9\x95\n\n'
                b'4\n'
                b'00:00:07,000 --> 00:00:08,000\n'
                b'\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe5\x9b\x9b\xe8\xa1\x8c\xe4\xb8\xad\xe6\x96\x87\xe5\xad\x97\xe5\xb9\x95\n\n'
                b'5\n'
                b'00:00:09,000 --> 00:00:10,000\n'
                b'\xe8\xbf\x99\xe6\x98\xaf\xe7\xac\xac\xe4\xba\x94\xe8\xa1\x8c\xe4\xb8\xad\xe6\x96\x87\xe5\xad\x97\xe5\xb9\x95\n'
            ),
            file_name='fallback.srt',
            content_type='text/plain',
        )


def make_candidate(provider, file_id):
    return OnlineSubtitleCandidate(
        provider=provider,
        candidate_id=str(file_id),
        file_id=str(file_id),
        file_name=f'{file_id}.srt',
        language='zh-CN',
        subtitle_type='normal',
        format='srt',
        media_type='movie',
        tmdb_id=27205,
    )


class SubtitleProviderRegistryTest(unittest.TestCase):
    def test_default_provider_order_includes_new_sources_when_configured(self):
        with patch.dict(
            'os.environ',
            {
                'OPENSUBTITLES_API_KEY': 'opensubtitles-key',
                'SUBDL_API_KEY': 'subdl-key',
                'ASSRT_API_KEY': 'assrt-key',
            },
            clear=False,
        ):
            registry = SubtitleProviderRegistry()

        self.assertEqual(
            [provider.name for provider in registry.providers],
            ['opensubtitles', 'subdl', 'assrt', 'subtitlecat'],
        )

    def test_online_download_falls_back_to_next_provider(self):
        import os
        import tempfile

        first = FakeProvider(
            'opensubtitles',
            search_candidates=[make_candidate('opensubtitles', 'bad')],
            download_error=RuntimeError('download failed'),
        )
        second = FakeProvider(
            'subdl',
            search_candidates=[make_candidate('subdl', 'good')],
        )
        registry = SubtitleProviderRegistry(providers=[first, second])
        agent = SubtitleAgent(provider_registry=registry, disable_agent=True)

        with tempfile.TemporaryDirectory() as directory:
            media_path = os.path.join(directory, 'Inception.mkv')
            with open(media_path, 'wb') as handle:
                handle.write(b'video')
            media_link = {
                'target_path': media_path,
                'source_path': media_path,
                'media_type': 'movie',
                'media_tmdb_id': 27205,
                'base_title': 'Inception',
                'year': 2010,
            }
            with (
                patch('media_mcp.subtitle.services.dependencies.SUBTITLE_SYNC_MODE', 'disabled'),
                patch('media_mcp.subtitle.services.dependencies.upsert_media_subtitle') as upsert,
            ):
                result = agent._process_online_subtitle(media_link, test_mode=False)

            subtitle_path = os.path.join(directory, 'Inception.srt')
            subtitle_exists = os.path.exists(subtitle_path)

        self.assertEqual(result, 'downloaded')
        self.assertEqual(first.search_calls, 1)
        self.assertEqual(first.download_calls, 1)
        self.assertEqual(second.search_calls, 1)
        self.assertEqual(second.download_calls, 1)
        upsert.assert_called_once()
        self.assertTrue(subtitle_exists)


if __name__ == '__main__':
    unittest.main()
