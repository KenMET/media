#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classifier.py
媒体文件名规则解析与结果校验。
优先用确定性规则抽取信息，降低 LLM 猜错概率。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any

FALLBACK_SPECIAL_KEYWORDS = [
    '栋笃笑', '棟篤笑', 'stand up', 'stand-up', 'comedy special', 'talk show',
    '黄子华', '黃子華', 'concert', 'live', 'special'
]

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}

COMMON_NOISE_PATTERNS = [
    r"\b(2160p|1080p|720p|480p)\b",
    r"\b(BluRay|BDRip|BRRip|WEB[- _.]?DL|WEBRip|HDTV|DVDRip|Remux)\b",
    r"\b(x264|x265|h\.264|h\.265|HEVC|AVC|10bit|8bit)\b",
    r"\b(AAC[0-9.]*)\b",
    r"\b(DTS([-. ]?HD([-. ]?MA)?)?)\b",
    r"\b(TrueHD|Atmos|DDP?[0-9.]*)\b",
    r"\b(YTS|RARBG|CMRG|NC-Raws|Lilith-Raws|ZZZFUN)\b",
    r"\b(CHS|CHT|ENG|JPN|GB|BIG5|简繁|中字|双语|内封|外挂)\b",
    r"\b(Proper|REPACK|Extended|Complete|Multi)\b",
]

TV_PATTERNS = [
    re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b"),
]

TV_EXTRA_PATTERNS = [
    ('NCOP', re.compile(r'(?i)\bNC[ ._-]*OP[ ._-]*(?P<index>\d{1,3})?\b')),
    ('NCED', re.compile(r'(?i)\bNC[ ._-]*ED[ ._-]*(?P<index>\d{1,3})?\b')),
    ('NCOP', re.compile(r'无字幕(?:片头曲|片头|OP)\s*(?P<index>\d{1,3})?', re.IGNORECASE)),
    ('NCED', re.compile(r'无字幕(?:片尾曲|片尾|ED)\s*(?P<index>\d{1,3})?', re.IGNORECASE)),
    ('OP', re.compile(r'(?i)\bOP[ ._-]*(?P<index>\d{1,3})\b')),
    ('ED', re.compile(r'(?i)\bED[ ._-]*(?P<index>\d{1,3})\b')),
]

YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
TV_GROUP_TRIM_PATTERNS = [
    re.compile(r"(?i)\bchapter\b.*$"),
    re.compile(r"(?i)\bpart\b.*$"),
    re.compile(r"(?i)\bepisode\b.*$"),
    re.compile(r"(?i)\bcapitulo\b.*$"),
    re.compile(r"(?i)\bepisodio\b.*$"),
]


@dataclass
class ParsedMedia:
    source_path: str
    filename: str
    extension: str
    title_guess: str
    year: Optional[int]
    media_type: str
    season: Optional[int] = None
    episode: Optional[int] = None
    extra_type: Optional[str] = None
    extra_index: Optional[int] = None

    def to_prompt_payload(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "filename": self.filename,
            "extension": self.extension,
            "title_guess": self.title_guess,
            "year": self.year,
            "media_type": self.media_type,
            "season": self.season,
            "episode": self.episode,
            "extra_type": self.extra_type,
            "extra_index": self.extra_index,
        }


def _normalize_name(name: str) -> str:
    value = name
    value = value.replace("_", " ").replace(".", " ")
    value = re.sub(r"[\[\]\(\){}]", " ", value)
    for pattern in COMMON_NOISE_PATTERNS:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" -_.")
    return value.strip()


def _extract_year(text: str) -> Optional[int]:
    match = YEAR_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _detect_tv(text: str) -> tuple[bool, Optional[int], Optional[int]]:
    for pattern in TV_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        season = match.groupdict().get("season")
        episode = match.groupdict().get("episode")
        return True, int(season) if season else 1, int(episode) if episode else None
    return False, None, None


def _detect_tv_extra(text: str) -> tuple[Optional[str], Optional[int]]:
    for extra_type, pattern in TV_EXTRA_PATTERNS:
        match = pattern.search(text)
        if match:
            index = match.groupdict().get('index')
            return extra_type, int(index) if index else 1
    return None, None


def parse_media_filename(file_path: str) -> ParsedMedia:
    filename = os.path.basename(file_path)
    stem, ext = os.path.splitext(filename)
    ext = ext.lower()
    normalized = _normalize_name(stem)
    year = _extract_year(normalized)
    is_tv, season, episode = _detect_tv(normalized)
    extra_type, extra_index = _detect_tv_extra(normalized)

    title = normalized
    if year:
        title = re.sub(rf"(?<!\d){year}(?!\d)", " ", title)
    if is_tv:
        title = re.sub(r"(?i)\bS\d{1,2}[ ._-]*E\d{1,3}\b", " ", title)
    elif extra_type:
        for _, pattern in TV_EXTRA_PATTERNS:
            title = pattern.sub(' ', title)
    title = re.sub(r"\s+", " ", title).strip(" -_.")

    media_type = "tv" if is_tv else ("tv_extra" if extra_type else "movie")
    return ParsedMedia(
        source_path=file_path,
        filename=filename,
        extension=ext,
        title_guess=title or stem,
        year=year,
        media_type=media_type,
        season=season,
        episode=episode,
        extra_type=extra_type,
        extra_index=extra_index,
    )


def is_video_path(file_path: str) -> bool:
    return os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS


def extract_season_episode(text: str) -> tuple[Optional[int], Optional[int]]:
    for pattern in TV_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group("season")), int(match.group("episode"))
    return None, None


def build_tv_group_key(file_path: str, parsed: ParsedMedia) -> str:
    parent_name = os.path.basename(os.path.dirname(file_path))
    candidate = _normalize_name(parent_name) if parent_name else ''

    if not candidate:
        candidate = parsed.title_guess or ''

    candidate = re.sub(r"(?i)\bS\d{1,2}\b", ' ', candidate)
    candidate = re.sub(r"(?i)\bSeason\s*\d{1,2}\b", ' ', candidate)
    candidate = re.sub(r"(?i)\b第\s*\d{1,2}\s*季\b", ' ', candidate)
    for pattern in TV_GROUP_TRIM_PATTERNS:
        candidate = pattern.sub(' ', candidate)
    candidate = re.sub(r"\s+", ' ', candidate).strip(' -_.')

    if not candidate:
        candidate = parsed.title_guess or os.path.splitext(os.path.basename(file_path))[0]

    return candidate


def should_allow_non_tmdb_fallback(parsed: ParsedMedia) -> bool:
    title = (parsed.title_guess or '').lower()
    filename = (parsed.filename or '').lower()
    haystack = f'{title} {filename}'
    return any(keyword.lower() in haystack for keyword in FALLBACK_SPECIAL_KEYWORDS)


def validate_result(result: Dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, "result is not dict"
    if not result.get("success"):
        return False, result.get("error", "inference failed")

    source_path = result.get("source_path") or ""
    hardlink_path = result.get("hardlink_path") or ""
    media_type = result.get("media_type") or result.get("kind")

    if not source_path or not hardlink_path:
        return False, "missing source_path or hardlink_path"

    if any(ch in hardlink_path for ch in [":", "*", "?", '"', "<", ">", "|"]):
        return False, "hardlink_path contains invalid chars"

    if not is_video_path(hardlink_path):
        return False, "hardlink_path is not video file"

    if media_type == "tv":
        src_s, src_e = extract_season_episode(source_path)
        dst_s, dst_e = extract_season_episode(hardlink_path)
        result_s = result.get("season")
        result_e = result.get("episode")
        if result_s is None or result_e is None:
            return False, "tv result missing season/episode"
        try:
            result_s = int(result_s)
            result_e = int(result_e)
        except (TypeError, ValueError):
            return False, "tv result has invalid season/episode"
        if dst_s is None or dst_e is None:
            return False, "cannot extract season/episode from hardlink_path"
        if dst_s != result_s or dst_e != result_e:
            return False, f"season/episode mismatch: result S{result_s:02d}E{result_e:02d}, dst S{dst_s:02d}E{dst_e:02d}"
        if src_s is not None and src_e is not None and (dst_s != src_s or dst_e != src_e):
            return False, f"season/episode mismatch: src S{src_s:02d}E{src_e:02d}, dst S{dst_s:02d}E{dst_e:02d}"
    elif media_type == 'tv_extra':
        extra_type = result.get('extra_type')
        extra_index = result.get('extra_index')
        if not extra_type or extra_index is None:
            return False, 'tv_extra missing extra_type/extra_index'

    return True, "ok"
