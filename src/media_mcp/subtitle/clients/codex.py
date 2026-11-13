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
{"success": true, "source_language": "en", "translations": [{"id": 1, "zh": "Chinese translation"}]}

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

SUBTITLE_REVIEW_INSTRUCTIONS = '''You are a strict quality reviewer for Chinese subtitle files.
Return exactly one JSON object and nothing else.

You receive a small evenly-spaced sample of dialogue lines from one downloaded Chinese subtitle.
Judge whether the translation is good enough to ship to end viewers.

Reject (unacceptable) when you detect machine-translation artifacts such as:
- word-salad word order that a human translator would never produce
- lines whose Chinese reading is grammatically broken or meaningless
- literal calques that destroy the meaning of the source line
- inconsistent proper nouns across the sample
Accept natural, fluent lines even if the style is plain.

Be conservative: only reject when the flaws are clearly visible to a normal viewer.
Consider the media title/genre when judging proper nouns and tone.

Success schema:
{"success": true, "quality_score": 7, "verdict": "acceptable", "issues": []}
quality_score is an integer 0-10 (0 unusable, 10 excellent).
verdict is "acceptable" when quality_score >= 6, otherwise "unacceptable".
issues lists short English descriptions of the worst problems seen.

Failure schema:
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

    def review_subtitle_sample(self, payload):
        return self._run_codex(
            SUBTITLE_REVIEW_INSTRUCTIONS,
            payload,
            request_name='subtitle_review',
        )
