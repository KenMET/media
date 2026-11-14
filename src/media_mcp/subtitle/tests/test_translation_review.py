#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest import mock

from media_mcp.subtitle.domain.online_subtitle import sample_translation_pairs
from media_mcp.subtitle.domain.translation import SubtitleEvent
from media_mcp.subtitle.services import dependencies, review, translation


def _events(count):
    return [
        SubtitleEvent(
            index=index + 1,
            start_seconds=float(index),
            end_seconds=float(index + 1),
            source_text=f'source line {index + 1}',
        )
        for index in range(count)
    ]


class _FakeAgent:
    disable_agent = False
    client = object()

    def _media_display_name(self, media_link):
        return 'fake-media'

    def _translation_media_context(self, media_link):
        return {'title': 'fake'}

    def _redact_sensitive_text(self, value):
        return value

    def _call_ai_with_usage_retry(self, fn, media_label=None, operation=None):
        return fn()


class SampleTranslationPairsTest(unittest.TestCase):
    def test_even_sampling_with_ids(self):
        events = _events(100)
        translations = [f'译 {event.index}' for event in events]
        sample = sample_translation_pairs(events, translations, 10)
        self.assertEqual(10, len(sample))
        self.assertEqual({pair['id'] for pair in sample}, {pair['id'] for pair in sample})
        for pair in sample:
            self.assertTrue(pair['source'])
            self.assertTrue(pair['zh'])

    def test_small_input_returns_all(self):
        events = _events(3)
        translations = ['甲', '', '丙']
        sample = sample_translation_pairs(events, translations, 24)
        self.assertEqual(2, len(sample))

    def test_empty_input(self):
        self.assertEqual([], sample_translation_pairs([], [], 10))
        self.assertEqual([], sample_translation_pairs(_events(2), ['', ''], 10))


class ReviewModelTranslationTest(unittest.TestCase):
    def setUp(self):
        self.agent = _FakeAgent()
        self.events = _events(30)
        self.translations = [f'译 {event.index}' for event in self.events]

    def test_disabled_accepts(self):
        with mock.patch.object(dependencies, 'ENABLE_TRANSLATION_AI_REVIEW', False):
            accepted, reason = review.review_model_translation(
                self.agent, {}, self.events, self.translations
            )
        self.assertTrue(accepted)
        self.assertIn('disabled', reason)

    def test_small_sample_skips(self):
        accepted, reason = review.review_model_translation(
            self.agent, {}, self.events[:2], self.translations[:2]
        )
        self.assertTrue(accepted)
        self.assertIn('sample_too_small', reason)

    def test_llm_failure_fails_open(self):
        def boom(*args, **kwargs):
            raise RuntimeError('model down')

        self.agent._call_ai_with_usage_retry = boom
        accepted, reason = review.review_model_translation(
            self.agent, {}, self.events, self.translations
        )
        self.assertTrue(accepted)
        self.assertIn('unavailable', reason)

    def test_inconclusive_fails_open(self):
        self.agent._call_ai_with_usage_retry = lambda *a, **k: {'success': False}
        accepted, reason = review.review_model_translation(
            self.agent, {}, self.events, self.translations
        )
        self.assertTrue(accepted)
        self.assertIn('inconclusive', reason)

    def test_good_score_passes(self):
        self.agent._call_ai_with_usage_retry = lambda *a, **k: {
            'success': True, 'quality_score': 9, 'issues': [],
        }
        accepted, reason = review.review_model_translation(
            self.agent, {}, self.events, self.translations
        )
        self.assertTrue(accepted)
        self.assertIn('passed', reason)

    def test_low_score_rejected_with_issues(self):
        self.agent._call_ai_with_usage_retry = lambda *a, **k: {
            'success': True,
            'quality_score': 3,
            'issues': ["pair 5: mistranslation"],
        }
        accepted, reason = review.review_model_translation(
            self.agent, {}, self.events, self.translations
        )
        self.assertFalse(accepted)
        self.assertIn('rejected', reason)
        self.assertIn('pair 5', reason)


class ReviewRetryLoopTest(unittest.TestCase):
    def _translate_fn(self, calls, results):
        def translate_fn(ctx):
            calls.append(ctx)
            return results[len(calls) - 1]
        return translate_fn

    def test_retry_injects_feedback_and_keeps_final(self):
        agent = _FakeAgent()
        events = _events(30)
        verdicts = [
            {'success': True, 'quality_score': 3, 'issues': ['pair 2: bad']},
            {'success': True, 'quality_score': 8, 'issues': []},
        ]
        state = {'call': 0}

        def fake_review(self, media_link, events, translations):
            result = verdicts[state['call']]
            state['call'] += 1
            if result['quality_score'] >= 7:
                return True, 'translation_ai_review=passed'
            return False, 'translation_ai_review=rejected; translation_ai_review_issues=pair 2: bad'

        calls = []
        with mock.patch.object(review, 'review_model_translation', fake_review):
            result = translation._review_translations_with_retry(
                agent, {}, events, {'title': 'x'},
                self._translate_fn(calls, [['v1'] * 30, ['v2'] * 30]),
            )
        self.assertEqual(['v2'] * 30, result)
        self.assertEqual(2, len(calls))
        self.assertNotIn('quality_feedback', calls[0])
        self.assertIn('pair 2', calls[1]['quality_feedback'])

    def test_no_retry_when_passed(self):
        agent = _FakeAgent()
        events = _events(30)

        def fake_review(self, media_link, events, translations):
            return True, 'translation_ai_review=passed'

        calls = []
        with mock.patch.object(review, 'review_model_translation', fake_review):
            result = translation._review_translations_with_retry(
                agent, {}, events, {'title': 'x'},
                self._translate_fn(calls, [['v1'] * 30]),
            )
        self.assertEqual(['v1'] * 30, result)
        self.assertEqual(1, len(calls))


if __name__ == '__main__':
    unittest.main()
