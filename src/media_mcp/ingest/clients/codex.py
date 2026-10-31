#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex app-server client for media and subtitle classification."""

from __future__ import annotations

from typing import Any, Dict, Optional
from media_mcp.storage.model_settings import (DEFAULT_MODEL, DEFAULT_EFFORT)

from media_mcp.adapters.codex import (
    APP_SERVER_TOKEN_FILES, APP_SERVER_URL, CodexClient,
)

MODEL = DEFAULT_MODEL
REASONING_EFFORT = DEFAULT_EFFORT
CWD = '/tmp'
TIMEOUT_SECONDS = 300.0
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 3.0

STRICT_JSON_INSTRUCTIONS = '''You are a media classification and naming API for a Chinese-first media library.
Write all reasons and operational explanations in English; preserve original media names and requested subtitle languages.
Return exactly one JSON object and nothing else.
Do not include markdown fences, explanations, bullet points, or prose.
If uncertain, still return valid JSON with success=false.

Priority of knowledge sources:
1. Use TMDB first for canonical match and ids.
2. If TMDB lacks Chinese title or Chinese episode title, search other reliable public sources to fill missing Chinese metadata.
3. Keep TMDB ids when TMDB provided the canonical match, even if Chinese names come from another source.
4. Do not leave Chinese title null when a commonly used Chinese title can be found reliably elsewhere.

Naming policy:
- Chinese title is the primary library title whenever it exists.
- Original-language title must be preserved when known.
- For Japanese works, original title should be Japanese, not romanized English unless Japanese is unavailable.
- For Korean works, original title should be Korean when available.
- English title is auxiliary only.
- Include original_language as a BCP-47/ISO-like language code when known, such as ja, ko, en, fr, de, es, ru, zh.
- Include origin_country as ISO 3166-1 alpha-2 country code(s) when known, such as JP, KR, US, CN, FR.
- If zh and original are identical or effectively the same text, do not duplicate with parentheses.
- For TV episode titles, prefer Chinese episode title. If Chinese episode title is unavailable, fall back to original-language episode title, then English.

Single-item output schema:
TV success:
{"success": true, "kind": "tv", "source_path": "...", "tmdb_id": 123, "title": {"zh": "Chinese series title", "original": "Original series title", "base": "Chinese series title(Original series title)"}, "original_language": "ja", "origin_country": "JP", "year": 2009, "season": 2, "episode": 24, "episode_title": {"zh": "Chinese episode title", "original": "Original episode title", "base": "Chinese episode title"}, "confidence": 0.95}

Movie success:
{"success": true, "kind": "movie", "source_path": "...", "tmdb_id": 123, "title": {"zh": "Chinese movie title", "original": "Original movie title", "base": "Chinese movie title(Original movie title)"}, "original_language": "en", "origin_country": "US", "year": 2022, "confidence": 0.95}

TV extra success:
{"success": true, "kind": "tv_extra", "source_path": "...", "tmdb_id": 123, "title": {"zh": "Chinese series title", "original": "Original series title", "base": "Chinese series title(Original series title)"}, "original_language": "ja", "origin_country": "JP", "year": 2016, "extra_type": "NCED", "extra_index": 1, "confidence": 0.95}

TV series lookup output schema:
{"success": true, "kind": "tv_series_lookup", "tmdb_id": 123, "title": {"zh": "Chinese series title", "original": "Original series title", "base": "Chinese series title(Original series title)"}, "original_language": "ja", "origin_country": "JP", "year": 2009, "season": 2, "confidence": 0.95}

TV episode batch output schema:
{"success": true, "kind": "tv_episode_batch", "tmdb_id": 123, "season": 2, "episodes": [{"episode": 10, "episode_title": {"zh": "Chinese episode title", "original": "Original episode title", "base": "Chinese episode title"}}, {"episode": 24, "episode_title": {"zh": "Chinese episode title", "original": "Original episode title", "base": "Chinese episode title"}}], "confidence": 0.95}

Media batch output schema:
{"success": true, "kind": "media_batch", "results": [<single-item success or failure object>, ...]}

Failure:
{"success": false, "source_path": "...", "error_code": "NO_CONFIDENT_MATCH", "error": "..."}

Rules:
- Preserve source_path exactly for single-item calls.
- For tv_series_lookup, identify the series once and return title/tmdb/year/season only.
- For tv_episode_batch, do not repeat the series title per episode, only return episode mappings.
- For tv_episode_batch calls, return one episode entry per requested episode.
- For media_batch, return exactly one result object per input file in results, preserve each source_path exactly, and classify each item using the single-item schemas.
- In media_batch, when multiple files clearly belong to one TV season, infer the series once conceptually and return per-file TV results with season, episode, and episode_title.
- Prefer structured fields over prose.
- For TV input, return season and episode matching the input or fail.
- Treat NCOP, NCED, numbered OP/ED videos, and Chinese labels meaning creditless opening or ending as TV extras, never as movies.
- For tv_extra input, return kind="tv_extra" and preserve extra_type and extra_index from the input or fail.
- TV extras belong to their parent series and do not use season or episode fields.
- Only include TV-only fields for TV results.
- Do not include unused null placeholder fields.
- If TMDB has no confident match but the input appears to be a stand-up special, live performance, talk show special, or other non-TMDB-friendly video, you may still return success=true with kind="movie", tmdb_id omitted, and a title derived from reliable public sources or the cleaned filename.
- For such non-TMDB fallback results, keep confidence conservative, prefer Chinese title when present, and never fabricate TMDB ids.
- Never output any text before or after the JSON object.
'''

SUBTITLE_JSON_INSTRUCTIONS = '''You are a subtitle classification API for a Chinese-first media library.
Write reasons and operational explanations in English; keep subtitle language/content decisions unchanged.
Return exactly one JSON object and nothing else.
Do not include markdown fences, explanations, bullet points, or prose.
If uncertain, return success=false with a concise error.

Goal:
- Choose the best subtitle candidate for the matched media target.
- This is an automatic subtitle-management pipeline. Resolve ambiguous candidates from metadata,
  content_profile, and subtitle_sample without asking for human input.
- Default language priority is:
  1. Simplified Chinese as the main text with bilingual Chinese-English subtitles.
  2. Simplified Chinese.
  3. Traditional Chinese.
  4. Generic Chinese when simplified/traditional cannot be determined.
- English-only subtitles should not be selected as the default result.

Success schema:
{"success": true, "source_subtitle_path": "...", "matched_video_target_path": "...", "kind": "movie|tv", "season": 1, "episode": 2, "language": "zh-CN-bilingual|zh-CN|zh-Hant|zh", "subtitle_type": "bilingual|normal|forced|sdh|commentary", "format": "ass|srt|ssa|vtt|sup", "source_type": "sidecar|embedded", "stream_index": 3, "confidence": 0.92, "reason": "..."}

Failure schema:
{"success": false, "source_subtitle_path": "...", "error_code": "NO_PREFERRED_CHINESE_SUBTITLE", "error": "..."}

Rules:
- matched_video_target_path must be one of candidate_videos.target_path.
- If source_type is embedded, stream_index must be one of embedded_streams.stream_index.
- For embedded candidates, compare subtitle_sample and content_profile, not only language tags.
- Prefer a complete dialogue subtitle over forced-only, commentary, signs-only, or SDH variants.
- When two streams are both generic zh, infer Simplified/Traditional and bilingual characteristics
  from the actual text. Prefer Simplified Chinese-main bilingual, then Simplified Chinese.
- Never invent a stream index or source path.
- Prefer Chinese-main bilingual over pure Simplified Chinese.
- Prefer Simplified Chinese over Traditional Chinese.
- Avoid commentary and SDH unless no better Chinese subtitle exists.
- Never output text before or after the JSON object.
'''


class CodexMediaClient(CodexClient):
    """Compatibility facade: Media owns prompts; shared client owns transport."""

    def classify(self, media_payload: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        return self._run_codex(STRICT_JSON_INSTRUCTIONS, media_payload, request_name='single_media')

    def classify_batch(self, payload: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        return self._run_codex(STRICT_JSON_INSTRUCTIONS, payload, request_name='media_batch')

    def classify_tv_series_lookup(self, payload: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        return self._run_codex(STRICT_JSON_INSTRUCTIONS, payload, request_name='tv_series_lookup')

    def classify_tv_episode_batch(self, payload: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        return self._run_codex(STRICT_JSON_INSTRUCTIONS, payload, request_name='tv_episode_batch')

    def classify_subtitle(self, payload: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
        return self._run_codex(SUBTITLE_JSON_INSTRUCTIONS, payload, request_name='subtitle_classify')
