"""Provider title integrity without network access or real state."""
import unittest
from unittest.mock import Mock, patch

from media_mcp.adapters.tmdb import TMDB


class TitleIntegrityTests(unittest.TestCase):
    def adapter(self, *payloads):
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=row)) for row in payloads]
        return TMDB(session, remote=False), session

    @patch.dict('os.environ', {'TMDB_API_KEY': 'fixture', 'MEDIA_EXECUTION_ONLY': 'false'})
    def test_unicode_advertising_is_repaired_by_id_without_changing_ranking(self):
        spam = '\u6deb\u7247\u7f51 448832\U0001d7f5.com'
        adapter, session = self.adapter(
            {'results': [{'id': 2, 'title': spam, 'original_title': spam, 'vote_average': 9.1},
                         {'id': 1, 'title': '\u6b63\u5e38\u4e2d\u6587', 'original_title': 'Clean'}]},
            {'results': [{'id': 1, 'title': 'Clean'}, {'id': 2, 'title': 'Real title', 'original_title': spam}]})
        rows = adapter.get('movie/top_rated')['results']
        self.assertEqual([row['id'] for row in rows], [2, 1])
        self.assertEqual(rows[0]['title'], 'Real title')
        self.assertEqual(rows[0]['original_title'], 'Real title')
        self.assertEqual(rows[0]['vote_average'], 9.1)
        self.assertEqual(rows[1]['title'], '\u6b63\u5e38\u4e2d\u6587')
        self.assertEqual(session.get.call_count, 2)

    @patch.dict('os.environ', {'TMDB_API_KEY': 'fixture', 'MEDIA_EXECUTION_ONLY': 'false'})
    def test_unrecoverable_rows_are_omitted_and_unrelated_ids_never_substituted(self):
        spam = '4488329.com'
        adapter, _ = self.adapter({'results': [{'id': 1, 'title': spam}]},
                                  {'results': [{'id': 2, 'title': 'Wrong identity'}]})
        self.assertEqual(adapter.get('movie/top_rated')['results'], [])
        adapter, _ = self.adapter({'id': 1, 'name': spam}, {'id': 2, 'name': 'Wrong'})
        with self.assertRaisesRegex(RuntimeError, 'tmdb_unavailable'):
            adapter.get('tv/1')

    @patch.dict('os.environ', {'TMDB_API_KEY': 'fixture', 'MEDIA_EXECUTION_ONLY': 'false'})
    def test_clean_names_and_legitimate_domains_do_not_trigger_fallback(self):
        adapter, session = self.adapter({'results': [{'id': 1, 'title': 'dot.com'}]})
        self.assertEqual(adapter.get('movie/top_rated')['results'][0]['title'], 'dot.com')
        self.assertEqual(session.get.call_count, 1)

    @patch.dict('os.environ', {'TMDB_API_KEY': 'fixture', 'MEDIA_EXECUTION_ONLY': 'false'})
    def test_original_title_survives_an_unavailable_translation(self):
        import requests
        adapter, session = self.adapter()
        session.get.side_effect = [Mock(json=Mock(return_value={
            'id':1, 'title':'4488329.com', 'original_title':'Reliable original'})), requests.Timeout('private URL')]
        row = adapter.get('movie/1')
        self.assertEqual(row['title'], 'Reliable original')
        self.assertEqual(row['original_title'], 'Reliable original')
