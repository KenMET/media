#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import unittest

from media_mcp.ingest.domain.canonical_path import validate_canonical_hardlink_path
from media_mcp.ingest.domain.classifier import parse_media_filename, validate_result
from media_mcp.ingest.domain.path_builder import build_hardlink_path
from media_mcp.ingest.domain.result_schema import normalize_result, validate_structured_result


class TvExtraClassificationTest(unittest.TestCase):
    def test_relife_nced_is_tv_extra(self):
        source = 'ReLIFE 重返17岁 无字幕片尾曲1(ReLIFE NCED1) - 2016.mkv'

        parsed = parse_media_filename(source)

        self.assertEqual('tv_extra', parsed.media_type)
        self.assertEqual('NCED', parsed.extra_type)
        self.assertEqual(1, parsed.extra_index)
        self.assertEqual(2016, parsed.year)

    def test_tv_extra_normalization_and_path(self):
        source = 'ReLIFE 重返17岁 无字幕片尾曲1(ReLIFE NCED1) - 2016.mkv'
        parsed = parse_media_filename(source)
        result = normalize_result(
            {
                'success': True,
                'kind': 'tv_extra',
                'source_path': source,
                'tmdb_id': 66941,
                'title': {
                    'zh': 'ReLIFE 重返17岁',
                    'original': 'ReLIFE',
                    'base': 'ReLIFE 重返17岁',
                },
                'year': 2016,
                'confidence': 0.95,
            },
            parsed.to_prompt_payload(),
        )
        target = build_hardlink_path(result, '.mkv')
        result['hardlink_path'] = target

        self.assertEqual(
            os.path.join(
                '/data/media_hub',
                'series',
                'ReLIFE 重返17岁(ReLIFE)',
                '特典',
                'ReLIFE 重返17岁(ReLIFE) - NCED01 - 2016.mkv',
            ),
            target,
        )
        self.assertEqual((True, 'ok'), validate_structured_result(result))
        self.assertEqual((True, 'ok'), validate_result(result))
        self.assertEqual(
            (True, 'ok', target),
            validate_canonical_hardlink_path(result, target, '.mkv'),
        )

    def test_filename_classification_overrides_movie_response(self):
        source = 'ReLIFE 重返17岁 无字幕片尾曲1(ReLIFE NCED1) - 2016.mkv'
        parsed = parse_media_filename(source)

        result = normalize_result(
            {
                'success': True,
                'kind': 'movie',
                'source_path': source,
                'title': {'zh': 'ReLIFE 重返17岁', 'base': 'ReLIFE 重返17岁'},
                'year': 2016,
                'confidence': 0.9,
            },
            parsed.to_prompt_payload(),
        )

        self.assertEqual('tv_extra', result['kind'])
        self.assertEqual('NCED', result['extra_type'])
        self.assertEqual(1, result['extra_index'])

    def test_normalization_preserves_original_language_and_country(self):
        parsed = parse_media_filename('孤独摇滚！ S01E01 - 2022.mkv')

        result = normalize_result(
            {
                'success': True,
                'kind': 'tv',
                'source_path': parsed.source_path,
                'tmdb_id': 119100,
                'title': {
                    'zh': '孤独摇滚！',
                    'original': 'ぼっち・ざ・ろっく！',
                    'base': '孤独摇滚！(ぼっち・ざ・ろっく！)',
                },
                'original_language': 'ja',
                'production_countries': [{'iso_3166_1': 'JP', 'name': 'Japan'}],
                'year': 2022,
                'season': 1,
                'episode': 1,
                'confidence': 0.95,
            },
            parsed.to_prompt_payload(),
        )

        self.assertEqual('ja', result['original_language'])
        self.assertEqual('JP', result['origin_country'])

    def test_validate_result_accepts_ai_tv_result_when_source_episode_is_unparseable(self):
        result = {
            'success': True,
            'kind': 'tv',
            'source_path': '/data/downloads/Unusual Release Name.mkv',
            'season': 1,
            'episode': 4,
            'hardlink_path': '/data/media_hub/series/Example Show/第01季/Example Show - S01E04 - 2024.mkv',
        }

        self.assertEqual((True, 'ok'), validate_result(result))

    def test_validate_result_rejects_ai_tv_result_when_target_episode_mismatches(self):
        result = {
            'success': True,
            'kind': 'tv',
            'source_path': '/data/downloads/Unusual Release Name.mkv',
            'season': 1,
            'episode': 4,
            'hardlink_path': '/data/media_hub/series/Example Show/第01季/Example Show - S01E05 - 2024.mkv',
        }

        self.assertEqual(
            (False, 'season/episode mismatch: result S01E04, dst S01E05'),
            validate_result(result),
        )


if __name__ == '__main__':
    unittest.main()
