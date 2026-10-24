#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Notification labels and ordering for subtitle processing summaries."""

from __future__ import annotations

from typing import Any

SUBTITLE_NOTIFY_LABELS = {
    'embedded_default_set': '内嵌选择',
    'embedded_extracted': '内嵌提取',
    'linked': '本地外挂',
    'copied': '复制外挂',
    'downloaded': '在线下载',
    'downloaded:online': '在线下载',
    'downloaded:online_synced': '在线下载校准',
    'translated': 'AI翻译',
    'audio_transcribed': '音频识别',
    'audio_translated': '音频识译',
    'exists': '已有',
    'missing': '缺失',
    'needs_review': '需复核',
    'failed': '错误',
}

SUBTITLE_NOTIFY_ORDER = (
    'embedded_default_set',
    'embedded_extracted',
    'downloaded:online',
    'downloaded:online_synced',
    'downloaded',
    'translated:embedded',
    'translated:embedded_ocr',
    'translated:sidecar',
    'translated:online',
    'translated',
    'audio_transcribed',
    'audio_translated',
    'linked',
    'copied',
    'exists',
    'missing',
    'needs_review',
    'failed',
)

TRANSLATION_SOURCE_LABELS = {
    'embedded': '内嵌',
    'embedded_ocr': '内嵌 OCR',
    'sidecar': '外挂',
    'online': '下载',
    'translation': 'AI',
}

TRANSLATION_SOURCE_TYPES = {
    'embedded_translation': 'embedded',
    'embedded_ocr_translation': 'embedded_ocr',
    'sidecar_translation': 'sidecar',
    'provider_translation': 'online',
    'translation': 'translation',
}

LANGUAGE_ALIASES = {
    'eng': 'en',
    'english': 'en',
    'jpn': 'ja',
    'jp': 'ja',
    'japanese': 'ja',
    'kor': 'ko',
    'kr': 'ko',
    'korean': 'ko',
    'chi': 'zh',
    'zho': 'zh',
    'chs': 'zh-CN',
    'cht': 'zh-Hant',
}

LANGUAGE_NOTIFY_LABELS = {
    'en': 'EN',
    'ja': 'JP',
    'ko': 'KR',
    'zh': 'ZH',
    'zh-CN': 'CN',
    'zh-Hant': 'TW',
}

FAILURE_STAGE_LABELS = {
    'invalid_media_link': '媒体记录错误',
    'batch_exception': '批处理错误',
    'embedded_probe': '内嵌探测错误',
    'embedded_default_set': '内嵌选择错误',
    'embedded_extract': '内嵌提取错误',
    'embedded_translation_source': '内嵌翻译源错误',
    'translation': '翻译错误',
    'audio_transcription': '音频识别错误',
    'audio_asr_translation': '音频识译错误',
    'subtitle_sync': '字幕校准错误',
    'sidecar_copy': '外挂复制错误',
    'sidecar_link': '外挂链接错误',
}


def _clean_key(value: Any) -> str:
    return str(value or '').strip().replace(' ', '_').replace(':', '_')


def normalize_notify_language(language: Any) -> str:
    value = str(language or '').strip()
    if not value:
        return 'auto'
    lowered = value.lower()
    return LANGUAGE_ALIASES.get(lowered, lowered)


def language_notify_label(language: Any) -> str:
    normalized = normalize_notify_language(language)
    if normalized == 'auto':
        return ''
    return LANGUAGE_NOTIFY_LABELS.get(normalized, normalized.upper())


def translation_detail_key(source_type: Any, source_language: Any) -> str:
    source = TRANSLATION_SOURCE_TYPES.get(str(source_type or ''), 'translation')
    language = normalize_notify_language(source_language)
    return f'translated:{source}:{language}'


def failure_detail_key(stage: Any) -> str:
    return f'failed:{_clean_key(stage) or "unknown"}'


def subtitle_detail_label(detail: Any) -> str:
    key = str(detail or '')
    if key.startswith('translated:'):
        _, source, *rest = key.split(':')
        language = rest[0] if rest else ''
        source_label = TRANSLATION_SOURCE_LABELS.get(source, source)
        language_label = language_notify_label(language)
        if language_label:
            return f'{source_label} {language_label} 翻译'
        return f'{source_label}翻译'
    if key.startswith('failed:'):
        stage = key.split(':', 1)[1]
        return FAILURE_STAGE_LABELS.get(stage, f'{stage} 错误')
    return SUBTITLE_NOTIFY_LABELS.get(key, key)


def _notify_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    key, _ = item
    for index, prefix in enumerate(SUBTITLE_NOTIFY_ORDER):
        if key == prefix or key.startswith(f'{prefix}:'):
            return index, key
    return len(SUBTITLE_NOTIFY_ORDER), key


def subtitle_notify_parts(
    counts: dict[str, int] | None,
    *,
    ignored_noop_actions: set[str] | None = None,
) -> list[str]:
    ignored = ignored_noop_actions or set()
    parts: list[str] = []
    for key, raw_count in sorted((counts or {}).items(), key=_notify_sort_key):
        if key in ignored:
            continue
        count = int(raw_count or 0)
        if count > 0:
            parts.append(f'{subtitle_detail_label(key)}{count}')
    return parts
