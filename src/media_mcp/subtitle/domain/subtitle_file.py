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
        ('bilingual', 'dual', 'chs&eng', 'chi&eng', 'zh&en', '简英', '中英', '双语', '简体&英文'),
    )
    has_simplified_marker = _contains_any(
        lowered,
        ('zh-cn', 'zh_cn', 'zh-hans', 'zhs', 'chs', 'gb', 'simplified', 'simplified chinese', '简体', '简中', '简'),
    )
    has_traditional_marker = _contains_any(
        lowered,
        ('zh-tw', 'zh_tw', 'zh-hk', 'zh_hk', 'zh-hant', 'zht', 'cht', 'big5', 'traditional', 'traditional chinese', '繁体', '繁中', '繁'),
    )
    has_zh_marker = _contains_any(lowered, ('zh', 'chi', 'zho', 'cmn', 'chinese', '中文', '中字'))

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
    simplified_count = sum(char in '这为国汉后发话里们来时会个门见说车东与云无过还进开关听写体学万长么从对头样' for char in text)
    traditional_count = sum(char in '這為國漢後發話裡們來時會個門見說車東與雲無過還進開關聽寫體學萬長麼從對頭樣' for char in text)
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
    if any(marker in lowered for marker in ('commentary', '评论', '導評', '导评')):
        return 'commentary'
    if re.search(r'\b(?:signs|songs)(?:\s*(?:&|/|and)\s*(?:signs|songs))?\b', lowered):
        return 'forced'
    if any(marker in lowered for marker in ('forced', '强制', '強制')):
        return 'forced'
    if any(marker in lowered for marker in ('sdh', 'cc', 'hearing impaired', '听障', '聽障')):
        return 'sdh'
    if language == 'zh-CN-bilingual':
        return 'bilingual'
    if any(marker in lowered for marker in ('bilingual', 'dual', '双语', '中英', '简英')):
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
    match = re.search(r'(?:ep?|第)\s*(\d{1,3})\s*(?:集|话|話)?', lowered)
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
    return any(ch in text for ch in '简体国汉后发话')


def _looks_traditional(text: str) -> bool:
    return any(ch in text for ch in '繁體國漢後發話')
