#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subtitle workflow settings and external capabilities; no orchestration state."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, replace
from typing import Any, Callable, TYPE_CHECKING
from urllib.parse import unquote

from media_mcp.ingest.domain.file_utils import create_hardlink as _create_hardlink
from media_mcp.subtitle.domain.embedded_subtitle import (
    EmbeddedSubtitleProbeError,
    EmbeddedSubtitleStream,
    extract_embedded_subtitle,
    ffprobe_subtitle_streams,
    sample_embedded_subtitle,
    select_preferred_embedded,
    set_mkv_default_subtitle,
)
from media_mcp.subtitle.domain.audio_transcription import (
    AudioTranscriptionError,
    build_asr_sidecar_path,
    transcribe_audio,
    write_srt,
)
from media_mcp.subtitle.domain.path_builder import (
    build_sidecar_path,
    shorten_sidecar_path,
)
from media_mcp.subtitle.domain.online_subtitle import (
    validate_online_subtitle,
    validate_online_translation_source,
)
from media_mcp.subtitle.domain.subtitle_ocr import (
    is_ocr_supported_stream,
    ocr_embedded_pgs_to_srt,
)
from media_mcp.subtitle.domain.notify_summary import (
    failure_detail_key,
    subtitle_detail_label,
    subtitle_notify_parts,
    translation_detail_key,
)
from media_mcp.subtitle.domain.result_schema import (
    normalize_subtitle_result,
    validate_subtitle_result,
)
from media_mcp.subtitle.domain.subtitle_file import (
    SUBTITLE_EXTENSIONS,
    SubtitleCandidate,
    analyze_subtitle_sample,
    detect_language,
    discover_subtitle_files,
    parse_episode_markers,
)
from media_mcp.subtitle.domain.subtitle_sync import sync_subtitle_to_audio
from media_mcp.subtitle.domain.translation import (
    SubtitleTranslationError,
    parse_text_subtitle,
    render_bilingual_ass,
    render_chinese_ass,
    restyle_bilingual_ass as _restyle_bilingual_ass,
    translate_events,
    validate_translation_events,
    write_text_atomic as _write_text_atomic,
)
from media_mcp.subtitle.providers.base import (
    OnlineSubtitleCandidate,
    SubtitleSearchRequest,
)
from media_mcp.subtitle.providers.base import ProviderTemporarilyUnavailable
from media_mcp.subtitle.providers.registry import SubtitleProviderRegistry
from media_mcp.subtitle.services.cache import SubtitleRunCache
from media_mcp.storage.media import (
    add_failed_case as _add_failed_case,
    list_media_links_by_source_prefix,
    get_media_link_by_source,
    list_media_subtitles_by_video,
    list_media_links_by_target_prefix,
    upsert_media_subtitle as _upsert_media_subtitle,
)
from media_mcp.adapters.dispatch import mcp_direct_call_ns

from media_mcp.runtime.state import assert_mutation_lock


def write_text_atomic(*args, **kwargs):
    assert_mutation_lock()
    return _write_text_atomic(*args, **kwargs)


def restyle_bilingual_ass(*args, **kwargs):
    assert_mutation_lock()
    return _restyle_bilingual_ass(*args, **kwargs)


def create_hardlink(*args, **kwargs):
    assert_mutation_lock()
    return _create_hardlink(*args, **kwargs)


def add_failed_case(*args, **kwargs):
    assert_mutation_lock()
    return _add_failed_case(*args, **kwargs)


def upsert_media_subtitle(*args, **kwargs):
    assert_mutation_lock()
    return _upsert_media_subtitle(*args, **kwargs)


MEDIA_DB = (
    os.environ.get("MEDIA_DB_NAME") or "media"
)
FULL_SCAN_ROOT = os.environ.get("SUBTITLE_SCAN_ROOT") or "/data/downloads"
LOW_CONFIDENCE_THRESHOLD = float(
    os.environ.get("SUBTITLE_LOW_CONFIDENCE_THRESHOLD", "0.75")
)
SET_EMBEDDED_DEFAULT = os.environ.get(
    "SUBTITLE_SET_EMBEDDED_DEFAULT", "false"
).lower() in {"1", "true", "yes", "on"}
EXTRACT_EMBEDDED_FALLBACK = os.environ.get(
    "SUBTITLE_EXTRACT_EMBEDDED_FALLBACK", "true"
).lower() in {"1", "true", "yes", "on"}
ALLOW_COPY_FALLBACK = os.environ.get(
    "SUBTITLE_ALLOW_COPY_FALLBACK", "true"
).lower() in {"1", "true", "yes", "on"}
TRANSLATION_BATCH_EVENTS = int(
    os.environ.get("SUBTITLE_TRANSLATION_BATCH_EVENTS", "160")
)
TRANSLATION_BATCH_CHARACTERS = int(
    os.environ.get("SUBTITLE_TRANSLATION_BATCH_CHARACTERS", "12000")
)
TRANSLATION_BATCH_TOKENS = int(os.environ.get("SUBTITLE_TRANSLATION_BATCH_TOKENS", "0"))
TRANSLATION_INCOMPLETE_RETRIES = int(
    os.environ.get("SUBTITLE_TRANSLATION_INCOMPLETE_RETRIES", "2")
)
AI_RETRY_WAIT_SECONDS = int(os.environ.get("SUBTITLE_AI_RETRY_WAIT_SECONDS", "3600"))
AI_RETRY_MAX_WAIT_SECONDS = int(
    os.environ.get("SUBTITLE_AI_RETRY_MAX_WAIT_SECONDS", str(8 * 3600))
)
CHINESE_FONT_SIZE = int(os.environ.get("SUBTITLE_CHINESE_FONT_SIZE", "68"))
SOURCE_FONT_SIZE = int(os.environ.get("SUBTITLE_SOURCE_FONT_SIZE", "46"))
SUBTITLE_BOTTOM_MARGIN = int(os.environ.get("SUBTITLE_BOTTOM_MARGIN", "18"))
WARN_TRANSLATION_EVENTS = int(
    os.environ.get("SUBTITLE_WARN_TRANSLATION_EVENTS", "4000")
)
MAX_TRANSLATION_EVENTS = int(os.environ.get("SUBTITLE_MAX_TRANSLATION_EVENTS", "12000"))
WARN_EVENTS_PER_MINUTE = float(os.environ.get("SUBTITLE_WARN_EVENTS_PER_MINUTE", "65"))
MAX_EVENTS_PER_MINUTE = float(os.environ.get("SUBTITLE_MAX_EVENTS_PER_MINUTE", "120"))
ENABLE_AUDIO_ASR = os.environ.get("SUBTITLE_ENABLE_AUDIO_ASR", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ASR_MODEL = os.environ.get("SUBTITLE_ASR_MODEL", "small")
ASR_LANGUAGE = os.environ.get("SUBTITLE_ASR_LANGUAGE") or None
ASR_DEVICE = os.environ.get("SUBTITLE_ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.environ.get("SUBTITLE_ASR_COMPUTE_TYPE", "int8")
ASR_BEAM_SIZE = int(os.environ.get("SUBTITLE_ASR_BEAM_SIZE", "5"))
ASR_VAD_FILTER = os.environ.get("SUBTITLE_ASR_VAD_FILTER", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ONLINE_SEARCH_LANGUAGES = ("zh-cn", "zh-tw")
ONLINE_CANDIDATES_PER_PROVIDER = 5
SUBTITLE_SYNC_MODE = os.environ.get("SUBTITLE_SYNC_MODE", "required").lower()
SUBTITLE_SYNC_BINARY = os.environ.get("SUBTITLE_SYNC_BINARY", "ffsubsync")
SUBTITLE_SYNC_TIMEOUT_SECONDS = int(
    os.environ.get("SUBTITLE_SYNC_TIMEOUT_SECONDS", "600")
)
ONLINE_SUBTITLE_MAX_END_OVERRUN_SECONDS = float(
    os.environ.get("ONLINE_SUBTITLE_MAX_END_OVERRUN_SECONDS", "180")
)
ONLINE_SUBTITLE_MAX_END_OVERRUN_RATIO = float(
    os.environ.get("ONLINE_SUBTITLE_MAX_END_OVERRUN_RATIO", "0.08")
)
TRANSLATION_FALLBACK_LANGUAGE = "en"
TRANSLATION_ANY_FALLBACK_LANGUAGES = (
    "ja",
    "ko",
    "fr",
    "de",
    "es",
    "ru",
    "it",
    "pt",
    "nl",
    "pl",
)

logger = logging.getLogger("SubtitleAgent")

LANGUAGE_ALIASES = {
    "jpn": "ja",
    "jp": "ja",
    "japanese": "ja",
    "kor": "ko",
    "kr": "ko",
    "korean": "ko",
    "eng": "en",
    "english": "en",
    "fre": "fr",
    "fra": "fr",
    "french": "fr",
    "ger": "de",
    "deu": "de",
    "german": "de",
    "spa": "es",
    "spanish": "es",
    "rus": "ru",
    "russian": "ru",
    "chi": "zh",
    "zho": "zh",
    "chs": "zh-CN",
    "cht": "zh-Hant",
}

COUNTRY_LANGUAGE_ALIASES = {
    "JP": "ja",
    "JPN": "ja",
    "KR": "ko",
    "KOR": "ko",
    "US": "en",
    "USA": "en",
    "GB": "en",
    "UK": "en",
    "CA": "en",
    "AU": "en",
    "NZ": "en",
    "FR": "fr",
    "FRA": "fr",
    "DE": "de",
    "DEU": "de",
    "ES": "es",
    "ESP": "es",
    "RU": "ru",
    "RUS": "ru",
    "CN": "zh-CN",
    "CHN": "zh-CN",
    "TW": "zh-Hant",
    "HK": "zh-Hant",
}

CHINESE_LANGUAGES = {"zh-CN", "zh-Hant", "zh", "zh-CN-bilingual"}
from media_mcp.redaction import redact_sensitive_text

HANDLED_ACTIONS = {
    "embedded_default_set",
    "embedded_extracted",
    "linked",
    "copied",
    "downloaded",
    "translated",
    "audio_transcribed",
    "audio_translated",
    "exists",
}


# Explicit capability exports shared by every subtitle stage.
__all__ = [
    "Any",
    "AudioTranscriptionError",
    "Callable",
    "EmbeddedSubtitleProbeError",
    "EmbeddedSubtitleStream",
    "OnlineSubtitleCandidate",
    "ProviderTemporarilyUnavailable",
    "SUBTITLE_EXTENSIONS",
    "SubtitleCandidate",
    "SubtitleProviderRegistry",
    "SubtitleRunCache",
    "SubtitleSearchRequest",
    "SubtitleTranslationError",
    "TYPE_CHECKING",
    "add_failed_case",
    "analyze_subtitle_sample",
    "asdict",
    "build_asr_sidecar_path",
    "build_sidecar_path",
    "create_hardlink",
    "detect_language",
    "discover_subtitle_files",
    "extract_embedded_subtitle",
    "failure_detail_key",
    "ffprobe_subtitle_streams",
    "is_ocr_supported_stream",
    "json",
    "list_media_links_by_source_prefix",
    "list_media_links_by_target_prefix",
    "list_media_subtitles_by_video",
    "logging",
    "math",
    "mcp_direct_call_ns",
    "normalize_subtitle_result",
    "ocr_embedded_pgs_to_srt",
    "os",
    "parse_episode_markers",
    "parse_text_subtitle",
    "re",
    "redact_sensitive_text",
    "render_bilingual_ass",
    "render_chinese_ass",
    "replace",
    "restyle_bilingual_ass",
    "sample_embedded_subtitle",
    "select_preferred_embedded",
    "set_mkv_default_subtitle",
    "shorten_sidecar_path",
    "shutil",
    "subprocess",
    "subtitle_detail_label",
    "subtitle_notify_parts",
    "sync_subtitle_to_audio",
    "time",
    "transcribe_audio",
    "translate_events",
    "translation_detail_key",
    "unquote",
    "upsert_media_subtitle",
    "validate_online_subtitle",
    "validate_online_translation_source",
    "validate_subtitle_result",
    "validate_translation_events",
    "write_srt",
    "write_text_atomic",
]
