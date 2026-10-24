#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize and validate subtitle classification results."""

from __future__ import annotations

import os
from typing import Any

ALLOWED_LANGUAGES = {'zh-CN-bilingual', 'zh-CN', 'zh-Hant', 'zh'}
ALLOWED_SOURCE_TYPES = {'sidecar', 'embedded'}


def normalize_subtitle_result(result: dict[str, Any] | None, fallback: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result or {})
    normalized.setdefault('success', False)
    normalized.setdefault('source_subtitle_path', fallback.get('source_subtitle_path'))
    normalized.setdefault('matched_video_target_path', fallback.get('matched_video_target_path'))
    normalized.setdefault('language', fallback.get('language'))
    normalized.setdefault('subtitle_type', fallback.get('subtitle_type') or 'normal')
    normalized.setdefault('format', fallback.get('format'))
    normalized.setdefault('source_type', fallback.get('source_type'))
    normalized.setdefault('stream_index', fallback.get('stream_index'))
    normalized.setdefault('confidence', fallback.get('confidence') or 0.0)
    return normalized


def validate_subtitle_result(
    result: dict[str, Any],
    candidate_targets: set[str],
    *,
    candidate_sources: set[str] | None = None,
    expected_media: dict[str, Any] | None = None,
    expected_source_type: str | None = None,
    allowed_stream_indices: set[int] | None = None,
    low_confidence_threshold: float = 0.0,
) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, 'result is not dict'
    if not result.get('success'):
        return False, result.get('error') or 'classification failed'
    if result.get('matched_video_target_path') not in candidate_targets:
        return False, 'matched target is not a candidate'
    if candidate_sources is not None and result.get('source_subtitle_path') not in candidate_sources:
        return False, 'source subtitle is not a candidate'
    if result.get('language') not in ALLOWED_LANGUAGES:
        return False, f'unsupported language: {result.get("language")}'
    if result.get('source_type') not in ALLOWED_SOURCE_TYPES:
        return False, f'unsupported source_type: {result.get("source_type")}'
    if expected_source_type and result.get('source_type') != expected_source_type:
        return False, 'source_type does not match request'
    if not result.get('format'):
        return False, 'missing format'
    source_path = result.get('source_subtitle_path')
    if source_path and result.get('source_type') == 'sidecar':
        expected_format = os.path.splitext(source_path)[1].lower().lstrip('.')
        if expected_format and str(result.get('format')).lower().lstrip('.') != expected_format:
            return False, 'format does not match source subtitle'
    if result.get('source_type') == 'embedded':
        try:
            stream_index = int(result.get('stream_index'))
        except (TypeError, ValueError):
            return False, 'invalid stream_index'
        if allowed_stream_indices is not None and stream_index not in allowed_stream_indices:
            return False, 'stream_index is not a candidate'
    if expected_media:
        expected_kind = expected_media.get('media_type')
        if expected_kind and result.get('kind') != expected_kind:
            return False, 'kind does not match media'
        for field in ('season', 'episode'):
            expected_value = expected_media.get(field)
            if expected_value is not None:
                if result.get(field) is None:
                    return False, f'missing {field}'
                try:
                    if int(result.get(field)) != int(expected_value):
                        return False, f'{field} does not match media'
                except (TypeError, ValueError):
                    return False, f'invalid {field}'
    try:
        confidence = float(result.get('confidence') or 0.0)
    except (TypeError, ValueError):
        return False, 'invalid confidence'
    if confidence < low_confidence_threshold:
        return False, 'low confidence'
    return True, 'ok'
