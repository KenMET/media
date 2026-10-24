#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subtitle Codex client wrapper."""

from media_mcp.ingest.clients.codex import CodexMediaClient


SUBTITLE_TRANSLATION_INSTRUCTIONS = '''You are a professional audiovisual subtitle translator.
Return exactly one JSON object and nothing else.

Translate every batch entry into natural Simplified Chinese.
Use the media metadata and previous_context to keep character names, terminology, pronouns,
relationships, register, humor, and recurring phrases consistent.
Prefer established Chinese names for known works and characters.
Preserve meaning and tone, but keep each translation concise enough for on-screen subtitles.
Translate dialogue only. Do not add explanations, translator notes, timestamps, or the source text.
Preserve line breaks only when they help readability.
Never merge, split, omit, reorder, or invent entries.

Success schema:
{"success": true, "source_language": "en", "translations": [{"id": 1, "zh": "中文"}]}

Failure schema:
{"success": false, "error": "..."}

The translations array must contain exactly one object for every input entry, with the same id.
'''

SUBTITLE_CONTEXT_INSTRUCTIONS = '''You prepare a concise translation guide for audiovisual subtitles.
Return exactly one JSON object and nothing else.

Use the supplied TMDB id, title, year, season, and episode to identify the work.
Include only reliable information. Do not invent characters, relationships, or terminology.
Keep the result compact because it will be repeated with every translation batch.

Success schema:
{"success": true, "overview": "brief Chinese overview", "tone": "brief style guidance", "characters": [{"source": "name", "zh": "established Chinese name", "note": "role or relationship"}], "glossary": [{"source": "term", "zh": "preferred Chinese translation"}]}

If the work cannot be identified reliably, return:
{"success": false, "error": "..."}
'''


class CodexSubtitleClient(CodexMediaClient):
    """Reuse the media Codex transport with subtitle-specific instructions."""

    def translate_subtitle_batch(self, payload):
        return self._run_codex(
            SUBTITLE_TRANSLATION_INSTRUCTIONS,
            payload,
            request_name='subtitle_translate',
        )

    def build_subtitle_translation_context(self, payload):
        return self._run_codex(
            SUBTITLE_CONTEXT_INSTRUCTIONS,
            payload,
            request_name='subtitle_translation_context',
        )
