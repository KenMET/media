#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
canonical_path.py
Normalize and strictly validate canonical media hardlink paths.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from media_mcp.ingest.domain.path_builder import MEDIA_ROOT, build_hardlink_path


def canonicalize_hardlink_path(result: Dict[str, Any], extension: str, media_root: str = MEDIA_ROOT) -> str:
    return build_hardlink_path(result, extension, media_root)


def validate_canonical_hardlink_path(result: Dict[str, Any], hardlink_path: str, extension: str, media_root: str = MEDIA_ROOT) -> Tuple[bool, str, str]:
    canonical_path = canonicalize_hardlink_path(result, extension, media_root)

    normalized_target = os.path.normpath(hardlink_path or '')
    normalized_canonical = os.path.normpath(canonical_path)
    normalized_root = os.path.normpath(media_root)

    if not normalized_target.startswith(normalized_root + os.sep):
        return False, f'hardlink_path must live under {media_root}', canonical_path

    rel = os.path.relpath(normalized_target, normalized_root)
    parts = rel.split(os.sep)
    media_type = result.get('kind')

    if media_type == 'movie':
        if len(parts) != 2 or parts[0] != 'movie':
            return False, 'movie path must match /data/media_hub/movie/<title - year.ext>', canonical_path
    elif media_type == 'tv':
        if len(parts) != 4 or parts[0] != 'series':
            return False, 'tv path must match /data/media_hub/series/<title>/<localized-season>/<title - SxxExx - episode - year.ext>', canonical_path
        season = result.get('season')
        expected_season_dir = f'\u7b2c{int(season):02d}\u5b63'
        if parts[2] != expected_season_dir:
            return False, f'invalid season directory: expected {expected_season_dir}', canonical_path
    elif media_type == 'tv_extra':
        if len(parts) != 4 or parts[0] != 'series' or parts[2] != '\u7279\u5178':
            return False, 'tv_extra path must match /data/media_hub/series/<title>/<localized-extras>/<title - typeXX - year.ext>', canonical_path
    else:
        return False, f'unsupported media type: {media_type}', canonical_path

    if normalized_target != normalized_canonical:
        return False, 'hardlink_path is not canonical', canonical_path

    return True, 'ok', canonical_path


def enforce_canonical_hardlink_path(result: Dict[str, Any], extension: str, media_root: str = MEDIA_ROOT) -> Dict[str, Any]:
    cloned = dict(result)
    cloned['hardlink_path'] = canonicalize_hardlink_path(cloned, extension, media_root)
    return cloned
