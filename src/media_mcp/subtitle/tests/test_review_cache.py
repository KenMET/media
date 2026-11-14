#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the persistent AI-review rejection cache."""

import json
import os
import tempfile
import unittest

from media_mcp.subtitle.services import review_cache


class ReviewCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.directory.name, 'rejections.json')
        os.environ['SUBTITLE_REVIEW_CACHE_FILE'] = self.cache_file

    def tearDown(self):
        os.environ.pop('SUBTITLE_REVIEW_CACHE_FILE', None)
        self.directory.cleanup()

    def test_record_and_hit(self):
        review_cache.record_rejection('/data/m.mkv', 'subtitlecat', 123, 'ai_review=rejected', 2.0)
        memory = review_cache.rejection_memory('/data/m.mkv', 'subtitlecat', 123)
        self.assertIsNotNone(memory)
        self.assertEqual(memory['score'], 2.0)
        self.assertIn('ai_review=rejected', memory['reason'])

    def test_media_and_file_isolation(self):
        review_cache.record_rejection('/data/m.mkv', 'subtitlecat', 123, 'r')
        self.assertIsNone(review_cache.rejection_memory('/data/other.mkv', 'subtitlecat', 123))
        self.assertIsNone(review_cache.rejection_memory('/data/m.mkv', 'opensubtitles', 123))
        self.assertIsNone(review_cache.rejection_memory('/data/m.mkv', 'subtitlecat', 456))

    def test_filter_rejected_candidates(self):
        review_cache.record_rejection('/data/m.mkv', 'subtitlecat', 123, 'r')

        class Candidate:
            def __init__(self, provider, file_id):
                self.provider = provider
                self.file_id = file_id

        ranked = [(1.0, Candidate('subtitlecat', 123), 'a'), (0.9, Candidate('subtitlecat', 999), 'b')]
        kept, skipped = review_cache.filter_rejected_candidates('/data/m.mkv', ranked)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0][1].file_id, 999)

    def test_ttl_expiry(self):
        review_cache.record_rejection('/data/t.mkv', 'p', 1, 'r')
        with open(self.cache_file, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        key = review_cache.rejection_cache_key('/data/t.mkv', 'p', 1)
        data[key]['at'] -= 8 * 24 * 3600
        with open(self.cache_file, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        self.assertIsNone(review_cache.rejection_memory('/data/t.mkv', 'p', 1))

    def test_corrupt_cache_file_degrades_to_empty(self):
        with open(self.cache_file, 'w', encoding='utf-8') as handle:
            handle.write('{broken json')
        self.assertIsNone(review_cache.rejection_memory('/data/x', 'p', 1))
        self.assertTrue(
            review_cache.record_rejection('/data/x', 'p', 2, 'r')
        )
        self.assertIsNotNone(review_cache.rejection_memory('/data/x', 'p', 2))

    def test_key_sanitizes_unsafe_characters(self):
        review_cache.record_rejection('/data/weird|path\x01', 'p', 'a|b', 'r')
        memory = review_cache.rejection_memory('/data/weird|path\x01', 'p', 'a|b')
        self.assertIsNotNone(memory)


if __name__ == '__main__':
    unittest.main()
