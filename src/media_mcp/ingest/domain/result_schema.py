#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
result_schema.py
Normalize and validate Codex media classification results.
"""

from __future__ import annotations

import math

from typing import Any, Dict


REQUIRED_SUCCESS_FIELDS = ['success', 'source_path', 'kind', 'confidence']


def _same_text(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().lower() == b.strip().lower())


def _build_base(zh: str | None, original: str | None) -> str | None:
    if zh and original and not _same_text(zh, original):
        return f'{zh}({original})'
    return zh or original


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif isinstance(value, (int, float)):
            return str(value)
    return None


def _country_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        countries = []
        for item in value:
            if isinstance(item, dict):
                text = _first_text(item.get('iso_3166_1'), item.get('code'), item.get('name'))
            else:
                text = str(item).strip()
            if text:
                countries.append(text)
        return ','.join(countries) or None
    if isinstance(value, dict):
        return _first_text(value.get('iso_3166_1'), value.get('code'), value.get('name'))
    return None


def normalize_result(result: Dict[str, Any], parsed: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(result or {})
    normalized.setdefault('success', False)
    normalized.setdefault('source_path', parsed.get('source_path'))
    normalized.setdefault('kind', normalized.get('media_type') or parsed.get('media_type'))
    normalized.setdefault('year', parsed.get('year'))
    normalized.setdefault('confidence', 0.0)
    if normalized.get('success') and parsed.get('media_type') == 'tv_extra':
        normalized['kind'] = 'tv_extra'
        normalized['extra_type'] = parsed.get('extra_type')
        normalized['extra_index'] = parsed.get('extra_index')

    title = dict(normalized.get('title') or {})
    zh = title.get('zh') or normalized.get('zh_name')
    original = title.get('original') or normalized.get('original_name') or normalized.get('en_name')
    title['zh'] = zh
    title['original'] = original
    title['base'] = title.get('base') or _build_base(zh, original) or parsed.get('title_guess')
    normalized['title'] = title
    normalized['original_language'] = _first_text(
        normalized.get('original_language'),
        normalized.get('language'),
        normalized.get('original_lang'),
        normalized.get('spoken_language'),
    )
    normalized['origin_country'] = _country_text(
        normalized.get('origin_country')
        or normalized.get('origin_countries')
        or normalized.get('production_country')
        or normalized.get('production_countries')
        or normalized.get('country')
    )

    if normalized.get('kind') == 'tv':
        normalized.setdefault('season', parsed.get('season'))
        normalized.setdefault('episode', parsed.get('episode'))
        episode_title = normalized.get('episode_title', normalized.get('episode_name'))
        if isinstance(episode_title, str):
            episode_title = {'zh': episode_title, 'original': None, 'base': episode_title}
        else:
            episode_title = dict(episode_title or {})
        ep_zh = episode_title.get('zh')
        ep_original = episode_title.get('original') or episode_title.get('en')
        episode_title['zh'] = ep_zh
        episode_title['original'] = ep_original
        episode_title['base'] = episode_title.get('base') or ep_zh or ep_original
        normalized['episode_title'] = episode_title
        normalized.pop('episode_name', None)
        normalized.pop('extra_type', None)
        normalized.pop('extra_index', None)
    elif normalized.get('kind') == 'tv_extra':
        normalized.setdefault('extra_type', parsed.get('extra_type'))
        normalized.setdefault('extra_index', parsed.get('extra_index'))
        normalized.pop('season', None)
        normalized.pop('episode', None)
        normalized.pop('episode_name', None)
        normalized.pop('episode_title', None)
    else:
        normalized.pop('season', None)
        normalized.pop('episode', None)
        normalized.pop('episode_name', None)
        normalized.pop('episode_title', None)
        normalized.pop('extra_type', None)
        normalized.pop('extra_index', None)

    normalized.pop('media_type', None)
    normalized.pop('media_name', None)
    normalized.pop('base_title', None)
    normalized.pop('alt_name', None)
    normalized.pop('zh_name', None)
    normalized.pop('en_name', None)
    normalized.pop('original_name', None)
    normalized.pop('season_tmdb_id', None)
    normalized.pop('episode_tmdb_id', None)
    normalized.pop('reason', None)
    return normalized


def validate_structured_result(result: Dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, 'result is not dict'

    if not result.get('success'):
        if result.get('error'):
            return False, result.get('error')
        return False, 'classification failed'

    for field in REQUIRED_SUCCESS_FIELDS:
        if field not in result:
            return False, f'missing field: {field}'

    confidence = result.get('confidence')
    if type(confidence) not in (float,int) or not math.isfinite(confidence) or not 0<=confidence<=1:
        return False, 'confidence must be finite between zero and one'

    kind = result.get('kind')
    if kind not in {'movie', 'tv', 'tv_extra'}:
        return False, f'unsupported kind: {kind}'

    title = result.get('title')
    if not isinstance(title, dict) or not title.get('base'):
        return False, 'missing title.base'

    if kind == 'tv':
        if result.get('season') is None or result.get('episode') is None:
            return False, 'tv result missing season/episode'
    elif kind == 'tv_extra':
        if not result.get('extra_type') or result.get('extra_index') is None:
            return False, 'tv_extra result missing extra_type/extra_index'

    return True, 'ok'
