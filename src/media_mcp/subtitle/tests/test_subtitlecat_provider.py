import unittest

from media_mcp.adapters.subtitle.subtitlecat import SubtitleCatProvider
from media_mcp.subtitle.providers.base import SubtitleSearchRequest


class _Response:
    def __init__(self, text=''):
        self.text = text
        self.content = text.encode('utf-8')
        self.headers = {}

    def raise_for_status(self):
        return None


class _Session:
    def __init__(self, html):
        self.html = html

    def get(self, url, **kwargs):
        return _Response(self.html)


class SubtitleCatProviderTest(unittest.TestCase):
    def test_language_candidates_skip_conflicting_explicit_episode(self):
        provider = SubtitleCatProvider()
        provider.session = _Session(
            '<a id="download_zh-CN" '
            'href="/subs/1024/Light Shop S01E08 - Light (Awafim.tv)-zh-CN.srt">'
            'Download Chinese</a>'
        )
        request = SubtitleSearchRequest(
            media_type='tv',
            tmdb_id=226529,
            title='Light Shop',
            year=2024,
            season=1,
            episode=6,
            languages=('zh-cn',),
        )

        candidates = provider._language_candidates(
            'https://www.subtitlecat.com/subs/921/Light%20Shop%20S01E08.html',
            'Light Shop S01E08 - Light (Awafim.tv)',
            request,
        )

        self.assertEqual([], candidates)


if __name__ == '__main__':
    unittest.main()
