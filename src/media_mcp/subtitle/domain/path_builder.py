#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build canonical sidecar subtitle paths from media target paths."""

from __future__ import annotations

import os

from media_mcp.ingest.domain.file_utils import MAX_FILENAME_BYTES, _shorten_filename_for_limit


def _join_like_input(directory: str, filename: str) -> str:
    if directory and '/' in directory and '\\' not in directory:
        return f'{directory.rstrip("/")}/{filename}'
    return os.path.join(directory, filename)


def shorten_sidecar_path(
    matched_video_target_path: str,
    sidecar_suffix: str,
    *,
    max_bytes: int = MAX_FILENAME_BYTES,
) -> str:
    directory = os.path.dirname(matched_video_target_path)
    video_name = os.path.basename(matched_video_target_path)
    suffix = sidecar_suffix if sidecar_suffix.startswith('.') else f'.{sidecar_suffix}'
    suffix_bytes = len(suffix.encode('utf-8'))
    if suffix_bytes >= max_bytes:
        suffix = suffix.encode('utf-8')[-max_bytes + 16 :].decode('utf-8', errors='ignore')
        suffix_bytes = len(suffix.encode('utf-8'))
    video_budget = max(32, max_bytes - suffix_bytes)
    shortened_video_name = _shorten_filename_for_limit(video_name, max_bytes=video_budget)
    shortened_stem, _ = os.path.splitext(shortened_video_name)
    filename = f'{shortened_stem}{suffix}'
    if len(filename.encode('utf-8')) > max_bytes:
        stem_budget = max(16, max_bytes - suffix_bytes)
        stem_bytes = shortened_stem.encode('utf-8')[:stem_budget]
        while stem_bytes:
            try:
                shortened_stem = stem_bytes.decode('utf-8').rstrip(' .-_')
                break
            except UnicodeDecodeError:
                stem_bytes = stem_bytes[:-1]
        filename = f'{shortened_stem}{suffix}'
    return _join_like_input(directory, filename)


def build_sidecar_path(
    matched_video_target_path: str,
    subtitle_extension: str,
    language: str | None = None,
    subtitle_type: str | None = None,
    prefer_plain: bool = True,
) -> str:
    subtitle_extension = subtitle_extension if subtitle_extension.startswith('.') else f'.{subtitle_extension}'
    plain_path = shorten_sidecar_path(matched_video_target_path, subtitle_extension)
    if prefer_plain and not os.path.exists(plain_path):
        return plain_path

    suffix_parts = []
    if language:
        suffix_parts.append(language)
    if subtitle_type and subtitle_type not in {'normal', 'bilingual'}:
        suffix_parts.append(subtitle_type)
    tagged_suffix = ''.join(f'.{part}' for part in suffix_parts) + subtitle_extension
    tagged_path = shorten_sidecar_path(matched_video_target_path, tagged_suffix)
    if not os.path.exists(tagged_path):
        return tagged_path

    counter = 2
    while True:
        candidate_suffix = ''.join(f'.{part}' for part in suffix_parts + [str(counter)]) + subtitle_extension
        candidate = shorten_sidecar_path(matched_video_target_path, candidate_suffix)
        if not os.path.exists(candidate):
            return candidate
        counter += 1
