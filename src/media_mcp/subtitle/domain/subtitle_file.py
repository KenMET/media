#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subtitle file discovery, language parsing, and preference scoring."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable


SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt'}
SAMPLE_LINE_LIMIT = 40

LANGUAGE_PRIORITY = {
    'zh-CN-bilingual': 100,
    'zh-CN': 90,
    'zh-Hant': 70,
    'zh': 60,
}


@dataclass(frozen=True)
class SubtitleCandidate:
    path: str
    extension: str
    language: str | None
    subtitle_type: str | None
    season: int | None
    episode: int | None
    release_group: str | None
    sample: list[str]
    generated_by_agent: bool = False

    @property
    def preference_score(self) -> int:
        return LANGUAGE_PRIORITY.get(self.language or '', 0)


def is_subtitle_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUBTITLE_EXTENSIONS


def _raise_scan_error(error):
    raise error


def discover_subtitle_files(root_path: str) -> list[str]:
    if os.path.isfile(root_path):
        directory = os.path.dirname(root_path)
    else:
        directory = root_path
    if not os.path.isdir(directory):
        return []

    paths: list[str] = []
    for current, _, files in os.walk(directory,onerror=_raise_scan_error):
        for filename in files:
            full_path = os.path.join(current, filename)
            if is_subtitle_file(full_path):
                paths.append(full_path)
    return sorted(paths)


def read_subtitle_sample(path: str, limit: int = SAMPLE_LINE_LIMIT) -> list[str]:
    encodings = ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'latin-1')
    for encoding in encodings:
        try:
            lines: list[str] = []
            with open(path, 'r', encoding=encoding, errors='strict') as handle:
                for line in handle:
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
                    if len(lines) >= limit:
                        return lines
            return lines
        except UnicodeDecodeError:
            continue
        except OSError:
            return []
    return []


def _contains_any(text: str, values: Iterable[str]) -> bool:
    return any(value in text for value in values)


def detect_language(text: str, sample: list[str] | None = None) -> str | None:
    lowered = text.lower()
    joined_sample = '\n'.join(sample or [])
    if 'Title: AI translated Chinese subtitle' in joined_sample:
        return 'zh-CN'
    if 'Title: AI translated bilingual subtitle' in joined_sample:
        return 'zh-CN-bilingual'

    has_bilingual_marker = _contains_any(
        lowered,
        ('bilingual', 'dual', 'chs&eng', 'chi&eng', 'zh&en', '\u7b80\u82f1', '\u4e2d\u82f1', '\u53cc\u8bed', '\u7b80\u4f53&\u82f1\u6587'),
    )
    has_simplified_marker = _contains_any(
        lowered,
        ('zh-cn', 'zh_cn', 'zh-hans', 'zhs', 'chs', 'gb', 'simplified', 'simplified chinese', '\u7b80\u4f53', '\u7b80\u4e2d', '\u7b80'),
    )
    has_traditional_marker = _contains_any(
        lowered,
        ('zh-tw', 'zh_tw', 'zh-hk', 'zh_hk', 'zh-hant', 'zht', 'cht', 'big5', 'traditional', 'traditional chinese', '\u7e41\u4f53', '\u7e41\u4e2d', '\u7e41'),
    )
    has_zh_marker = _contains_any(lowered, ('zh', 'chi', 'zho', 'cmn', 'chinese', '\u4e2d\u6587', '\u4e2d\u5b57'))

    if has_bilingual_marker and (has_simplified_marker or _looks_simplified(joined_sample)):
        return 'zh-CN-bilingual'
    if has_simplified_marker:
        return 'zh-CN'
    if has_traditional_marker:
        return 'zh-Hant'
    if has_bilingual_marker:
        return 'zh-CN-bilingual'
    if has_zh_marker:
        return 'zh'
    if _looks_simplified(joined_sample):
        return 'zh-CN'
    if _looks_traditional(joined_sample):
        return 'zh-Hant'
    foreign_markers = (
        ('en', ('english', '.eng', '_eng', '-eng', '.en.', '_en_', '-en-')),
        ('ja', ('japanese', '.jpn', '_jpn', '-jpn', '.ja.', '_ja_', '-ja-')),
        ('ko', ('korean', '.kor', '_kor', '-kor', '.ko.', '_ko_', '-ko-')),
        ('fr', ('french', '.fre', '.fra', '_fre', '_fra', '.fr.')),
        ('de', ('german', '.ger', '.deu', '_ger', '_deu', '.de.')),
        ('es', ('spanish', '.spa', '_spa', '.es.')),
        ('ru', ('russian', '.rus', '_rus', '.ru.')),
    )
    padded = f'.{lowered}.'
    for language, markers in foreign_markers:
        if _contains_any(padded, markers):
            return language
    if any('\u3040' <= char <= '\u30ff' for char in joined_sample):
        return 'ja'
    if any('\uac00' <= char <= '\ud7af' for char in joined_sample):
        return 'ko'
    if any('\u0400' <= char <= '\u04ff' for char in joined_sample):
        return 'ru'
    return None


def analyze_subtitle_sample(sample: list[str] | None) -> dict[str, int | float | str | None]:
    timestamp_pattern = re.compile(
        r'(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*'
        r'(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})'
    )

    def timestamp_seconds(value: str) -> float:
        hours, minutes, seconds = value.replace(',', '.').split(':')
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    raw_lines = [line.strip() for line in (sample or []) if line.strip()]
    timestamps = []
    for line in raw_lines:
        match = timestamp_pattern.search(line)
        if match:
            timestamps.append(
                (
                    timestamp_seconds(match.group('start')),
                    timestamp_seconds(match.group('end')),
                )
            )
    content_lines = [
        line
        for line in raw_lines
        if not line.isdigit() and not timestamp_pattern.search(line)
    ]
    text = '\n'.join(content_lines)
    chinese_count = sum('\u3400' <= char <= '\u9fff' for char in text)
    latin_count = sum(char.isascii() and char.isalpha() for char in text)
    simplified_count = sum(char in '\u8fd9\u4e3a\u56fd\u6c49\u540e\u53d1\u8bdd\u91cc\u4eec\u6765\u65f6\u4f1a\u4e2a\u95e8\u89c1\u8bf4\u8f66\u4e1c\u4e0e\u4e91\u65e0\u8fc7\u8fd8\u8fdb\u5f00\u5173\u542c\u5199\u4f53\u5b66\u4e07\u957f\u4e48\u4ece\u5bf9\u5934\u6837' for char in text)
    traditional_count = sum(char in '\u9019\u70ba\u570b\u6f22\u5f8c\u767c\u8a71\u88e1\u5011\u4f86\u6642\u6703\u500b\u9580\u898b\u8aaa\u8eca\u6771\u8207\u96f2\u7121\u904e\u9084\u9032\u958b\u95dc\u807d\u5beb\u9ad4\u5b78\u842c\u9577\u9ebc\u5f9e\u5c0d\u982d\u6a23' for char in text)
    bilingual_lines = sum(
        any('\u3400' <= char <= '\u9fff' for char in line)
        and any(char.isascii() and char.isalpha() for char in line)
        for line in content_lines
    )

    language: str | None = None
    confidence = 0.0
    if simplified_count >= traditional_count + 2:
        language = 'zh-CN'
        confidence = min(0.98, 0.7 + simplified_count / 100)
    elif traditional_count >= simplified_count + 2:
        language = 'zh-Hant'
        confidence = min(0.98, 0.7 + traditional_count / 100)
    elif chinese_count:
        language = 'zh'
        confidence = 0.45

    bilingual = (
        chinese_count >= 10
        and latin_count >= 20
        and (bilingual_lines >= 2 or latin_count >= chinese_count * 0.35)
    )
    if bilingual and language in {'zh-CN', 'zh'}:
        language = 'zh-CN-bilingual'
        confidence = max(confidence, 0.8)

    normalized_lines = [
        re.sub(r'\s+', '', re.sub(r'<[^>]+>|\{[^}]+\}', '', line)).lower()
        for line in content_lines
    ]
    normalized_lines = [line for line in normalized_lines if line]
    unique_lines = len(set(normalized_lines))
    duplicate_ratio = (
        1.0 - unique_lines / len(normalized_lines)
        if normalized_lines
        else 1.0
    )
    hearing_impaired_lines = sum(
        bool(re.search(r'^\s*[\[(（【].+[\])）】]\s*$|[♪♫♬]', line))
        for line in content_lines
    )
    hearing_impaired_ratio = (
        hearing_impaired_lines / len(content_lines)
        if content_lines
        else 0.0
    )
    replacement_chars = text.count('\ufffd')
    first_start = min((start for start, _ in timestamps), default=0.0)
    last_end = max((end for _, end in timestamps), default=0.0)
    span_seconds = max(0.0, last_end - first_start)

    quality_score = 0.0
    quality_score += min(len(timestamps) / 120.0, 1.0) * 25
    quality_score += min(len(content_lines) / 120.0, 1.0) * 20
    quality_score += min(span_seconds / 1800.0, 1.0) * 25
    quality_score += min(chinese_count / 800.0, 1.0) * 15
    quality_score += confidence * 15
    quality_score -= duplicate_ratio * 10
    quality_score -= hearing_impaired_ratio * 8
    quality_score -= min(replacement_chars, 10) * 2
    quality_score = max(0.0, min(100.0, quality_score))

    return {
        'language': language,
        'subtitle_type': 'bilingual' if bilingual else 'normal',
        'confidence': confidence,
        'quality_score': round(quality_score, 2),
        'subtitle_events': len(timestamps),
        'dialogue_lines': len(content_lines),
        'span_seconds': round(span_seconds, 3),
        'chinese_chars': chinese_count,
        'latin_chars': latin_count,
        'simplified_markers': simplified_count,
        'traditional_markers': traditional_count,
        'bilingual_lines': bilingual_lines,
        'hearing_impaired_lines': hearing_impaired_lines,
        'duplicate_ratio': round(duplicate_ratio, 4),
        'replacement_chars': replacement_chars,
    }


def detect_subtitle_type(text: str, language: str | None = None) -> str | None:
    lowered = text.lower()
    if any(marker in lowered for marker in ('commentary', '\u8bc4\u8bba', '\u5c0e\u8a55', '\u5bfc\u8bc4')):
        return 'commentary'
    if re.search(r'\b(?:signs|songs)(?:\s*(?:&|/|and)\s*(?:signs|songs))?\b', lowered):
        return 'forced'
    if any(marker in lowered for marker in ('forced', '\u5f3a\u5236', '\u5f37\u5236')):
        return 'forced'
    if any(marker in lowered for marker in ('sdh', 'cc', 'hearing impaired', '\u542c\u969c', '\u807d\u969c')):
        return 'sdh'
    if language == 'zh-CN-bilingual':
        return 'bilingual'
    if any(marker in lowered for marker in ('bilingual', 'dual', '\u53cc\u8bed', '\u4e2d\u82f1', '\u7b80\u82f1')):
        return 'bilingual'
    return 'normal'


def parse_episode_markers(text: str) -> tuple[int | None, int | None]:
    lowered = text.lower()
    match = re.search(r's(\d{1,2})\s*e(\d{1,3})', lowered)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r'(\d{1,2})x(\d{1,3})', lowered)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search('(?:ep?|\u7b2c)\\s*(\\d{1,3})\\s*(?:\u96c6|\u8bdd|\u8a71)?', lowered)
    if match:
        return None, int(match.group(1))
    return None, None


def parse_subtitle_candidate(path: str) -> SubtitleCandidate:
    filename = os.path.basename(path)
    stem, extension = os.path.splitext(filename)
    sample = read_subtitle_sample(path)
    generated_by_agent = any(
        line in {
            'Title: AI translated bilingual subtitle',
            'Title: AI translated Chinese subtitle',
        }
        for line in sample
    )
    language = detect_language(stem, sample)
    subtitle_type = detect_subtitle_type(stem, language)
    season, episode = parse_episode_markers(stem)
    release_group = None
    release_match = re.search(r'-([A-Za-z0-9]+)$', stem)
    if release_match:
        release_group = release_match.group(1)
    return SubtitleCandidate(
        path=path,
        extension=extension.lower(),
        language=language,
        subtitle_type=subtitle_type,
        season=season,
        episode=episode,
        release_group=release_group,
        sample=sample,
        generated_by_agent=generated_by_agent,
    )


def _looks_simplified(text: str) -> bool:
    return any(ch in text for ch in '\u7b80\u4f53\u56fd\u6c49\u540e\u53d1\u8bdd')


def _looks_traditional(text: str) -> bool:
    return any(ch in text for ch in '\u7e41\u9ad4\u570b\u6f22\u5f8c\u767c\u8a71')
