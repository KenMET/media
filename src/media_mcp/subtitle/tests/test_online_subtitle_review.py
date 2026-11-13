#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from media_mcp.subtitle.domain.online_subtitle import sample_subtitle_lines
from media_mcp.subtitle.services import review as review_module
from media_mcp.subtitle.services.dependencies import ONLINE_SUBTITLE_AI_REVIEW_MIN_SCORE


GOOD_SRT = """1
00:00:01,000 --> 00:00:02,000
海洋里的动物比地球上任何地方都要多。

2
00:00:03,000 --> 00:00:04,000
二十五年来，我们走遍了地球的每个角落。

3
00:00:05,000 --> 00:00:06,000
在热带海域，生命在热点区域蓬勃繁衍。

4
00:00:07,000 --> 00:00:08,000
这里是地球上海豚密度最高的家园之一。

5
00:00:09,000 --> 00:00:10,000
想在这个拥挤的世界里出人头地，得有过人的智慧。
""".encode('utf-8')


class ReviewStub:
    """Minimal stand-in for SubtitleAgent in review tests."""

    def __init__(self, client=None, disable_agent=False):
        self.client = client
        self.disable_agent = disable_agent

    def _media_display_name(self, media_link):
        return media_link.get('target_path', 'media')

    def _translation_media_context(self, media_link):
        return {'title': media_link.get('base_title'), 'kind': 'tv'}

    def _redact_sensitive_text(self, text):
        return text

    def _call_ai_with_usage_retry(self, call, *, media_label, operation):
        return call()


def make_validated(content=GOOD_SRT):
    from media_mcp.subtitle.domain.online_subtitle import validate_online_subtitle

    return validate_online_subtitle(content, 'sample.srt')


class SampleSubtitleLinesTest(unittest.TestCase):
    def test_samples_evenly_across_file(self):
        lines = sample_subtitle_lines(GOOD_SRT, '.srt', 2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]['id'], 1)
        texts = {item['text'] for item in lines}
        self.assertNotEqual(texts, set())

    def test_returns_all_lines_when_under_limit(self):
        lines = sample_subtitle_lines(GOOD_SRT, '.srt', 24)
        self.assertEqual(len(lines), 5)
        self.assertEqual([item['id'] for item in lines], [1, 2, 3, 4, 5])

    def test_empty_for_non_positive_limit(self):
        self.assertEqual(sample_subtitle_lines(GOOD_SRT, '.srt', 0), [])


class ReviewOnlineSubtitleQualityTest(unittest.TestCase):
    def setUp(self):
        self.media_link = {'target_path': '/x/show.mkv', 'base_title': 'Demo'}

    def test_accepts_high_score(self):
        client = type('C', (), {'review_subtitle_sample': staticmethod(
            lambda payload: {'success': True, 'quality_score': 8, 'verdict': 'acceptable', 'issues': []})})()
        ok, reason = review_module.review_online_subtitle_quality(
            ReviewStub(client=client), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)
        self.assertIn('ai_review=passed', reason)

    def test_rejects_low_score(self):
        client = type('C', (), {'review_subtitle_sample': staticmethod(
            lambda payload: {'success': True, 'quality_score': 2,
                             'verdict': 'unacceptable', 'issues': ['word salad']})})()
        ok, reason = review_module.review_online_subtitle_quality(
            ReviewStub(client=client), self.media_link, 'p:1', make_validated())
        self.assertFalse(ok)
        self.assertIn('ai_review=rejected', reason)
        self.assertIn('word salad', reason)

    def test_fail_open_when_client_raises(self):
        class Broken:
            def review_subtitle_sample(self, payload):
                raise RuntimeError('codex down')

        ok, reason = review_module.review_online_subtitle_quality(
            ReviewStub(client=Broken()), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)
        self.assertEqual(reason, 'ai_review=unavailable')

    def test_fail_open_on_inconclusive_payload(self):
        client = type('C', (), {'review_subtitle_sample': staticmethod(
            lambda payload: {'success': False, 'error': 'nope'})})()
        ok, reason = review_module.review_online_subtitle_quality(
            ReviewStub(client=client), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)
        self.assertEqual(reason, 'ai_review=inconclusive')

    def test_disabled_flag_short_circuits(self):
        with patch.object(review_module.dependencies,
                          'ENABLE_ONLINE_SUBTITLE_AI_REVIEW', False):
            ok, reason = review_module.review_online_subtitle_quality(
                ReviewStub(), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)
        self.assertEqual(reason, 'ai_review=disabled')

    def test_agent_disabled_skips_review(self):
        ok, reason = review_module.review_online_subtitle_quality(
            ReviewStub(disable_agent=True), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)
        self.assertEqual(reason, 'ai_review=skipped:agent_disabled')

    def test_threshold_boundary_uses_config(self):
        score = int(ONLINE_SUBTITLE_AI_REVIEW_MIN_SCORE)
        client = type('C', (), {'review_subtitle_sample': staticmethod(
            lambda payload: {'success': True, 'quality_score': score,
                             'verdict': 'acceptable', 'issues': []})})()
        ok, _ = review_module.review_online_subtitle_quality(
            ReviewStub(client=client), self.media_link, 'p:1', make_validated())
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
