#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
path_builder.py
Build deterministic hardlink destinations from structured media classifications.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from media_mcp.ingest.domain.file_utils import sanitize_path, sanitize_segment
from media_mcp.ingest.domain.naming import build_base_title, strip_season_suffix

MEDIA_ROOT = os.environ.get('MEDIA_LIBRARY_ROOT', '/data/media_hub')


def _pick_base_title(result: Dict[str, Any]) -> str:
    title = result.get('title') or {}
    display = title.get('zh')
    original_name = title.get('original')

    if result.get('kind') in {'tv', 'tv_extra'}:
        display = strip_season_suffix(display) or display

    built, _, _ = build_base_title(display, None, original_name)
    return sanitize_segment(built)


def _pick_year(result: Dict[str, Any], fallback: Optional[int]) -> int:
    year = result.get('year', fallback)
    if year is None:
        return 0
    return int(year)


def build_hardlink_path(result: Dict[str, Any], extension: str, media_root: str = MEDIA_ROOT) -> str:
    media_type = result.get('kind')
    base_title = _pick_base_title(result)
    year = _pick_year(result, None)
    extension = extension.lower()

    if media_type == 'movie':
        path = os.path.join(media_root, 'movie', f'{base_title} - {year}{extension}')
        return path

    if media_type == 'tv':
        season = int(result.get('season'))
        episode = int(result.get('episode'))
        episode_name_obj = result.get('episode_title') or {}
        episode_name = episode_name_obj.get('base') or episode_name_obj.get('zh') or episode_name_obj.get('original')
        if episode_name:
            episode_name = sanitize_segment(episode_name)
            filename = f'{base_title} - S{season:02d}E{episode:02d} - {episode_name} - {year}{extension}'
        else:
            filename = f'{base_title} - S{season:02d}E{episode:02d} - {year}{extension}'
        path = os.path.join(
            media_root,
            'series',
            base_title,
            f'\u7b2c{season:02d}\u5b63',
            filename,
        )
        return path

    if media_type == 'tv_extra':
        extra_type = sanitize_segment(str(result.get('extra_type')).upper())
        extra_index = int(result.get('extra_index'))
        filename = f'{base_title} - {extra_type}{extra_index:02d} - {year}{extension}'
        return os.path.join(media_root, 'series', base_title, '\u7279\u5178', filename)

    raise ValueError(f'Unsupported media_type: {media_type}')
