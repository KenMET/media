#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI quality gate for downloaded online subtitles.

Machine-translation aggregator sites (e.g. subtitlecat) often serve word-salad
Chinese that passes coverage and timing QA. This module asks the subtitle Codex
model to review an evenly-spaced sample before the file is installed. Rejected
candidates fall through to the existing AI translation pipeline, which
translates a foreign-language source with the configured model instead.

The gate is fail-open: when the AI client is unavailable or returns an
unexpected payload, the candidate is accepted so online acquisition keeps
working without the model.
"""

from __future__ import annotations

from media_mcp.subtitle.services import dependencies

MIN_SAMPLE_LINES_FOR_REVIEW = 4


def review_online_subtitle_quality(
    self,
    media_link: dict[str, dependencies.Any],
    candidate_ref: str,
    validated,
) -> tuple[bool, str]:
    """Return (accepted, reason) for a validated online subtitle download."""
    if not dependencies.ENABLE_ONLINE_SUBTITLE_AI_REVIEW:
        return True, "ai_review=disabled"
    if getattr(self, "disable_agent", False):
        return True, "ai_review=skipped:agent_disabled"
    sample = dependencies.sample_subtitle_lines(
        validated.content,
        validated.extension,
        dependencies.ONLINE_SUBTITLE_AI_REVIEW_SAMPLE_LINES,
    )
    if len(sample) < MIN_SAMPLE_LINES_FOR_REVIEW:
        return True, "ai_review=skipped:sample_too_small"
    if self.client is None:
        from media_mcp.subtitle.clients.codex import CodexSubtitleClient

        self.client = CodexSubtitleClient()
    media_label = self._media_display_name(media_link)
    payload = {
        "media": self._translation_media_context(media_link),
        "lines": sample,
    }
    try:
        result = self._call_ai_with_usage_retry(
            lambda: self.client.review_subtitle_sample(payload),
            media_label=media_label,
            operation="subtitle_review",
        )
    except Exception as exc:
        dependencies.logger.warning(
            "Online subtitle AI review unavailable %s (%s); accepting candidate",
            candidate_ref,
            self._redact_sensitive_text(str(exc)),
        )
        return True, "ai_review=unavailable"
    if not isinstance(result, dict) or not result.get("success"):
        dependencies.logger.warning(
            "Online subtitle AI review inconclusive %s (%s); accepting candidate",
            candidate_ref,
            self._redact_sensitive_text(dependencies.json.dumps(result, default=str)[:200])
            if result is not None
            else "empty response",
        )
        return True, "ai_review=inconclusive"
    try:
        score = float(result.get("quality_score"))
    except (TypeError, ValueError):
        dependencies.logger.warning(
            "Online subtitle AI review missing score %s; accepting candidate",
            candidate_ref,
        )
        return True, "ai_review=inconclusive"
    issues = result.get("issues") or []
    if not isinstance(issues, list):
        issues = []
    issues_text = ";".join(str(item)[:80] for item in issues[:3])
    min_score = dependencies.ONLINE_SUBTITLE_AI_REVIEW_MIN_SCORE
    if score >= min_score:
        dependencies.logger.info(
            "Online subtitle AI review passed %s score=%.1f min=%.1f",
            candidate_ref,
            score,
            min_score,
        )
        return True, f"ai_review=passed; ai_review_score={score:g}"
    dependencies.logger.warning(
        "Online subtitle AI review rejected %s score=%.1f min=%.1f issues=%s",
        candidate_ref,
        score,
        min_score,
        issues_text or "-",
    )
    reason = f"ai_review=rejected; ai_review_score={score:g}"
    if issues_text:
        reason = f"{reason}; ai_review_issues={issues_text}"
    return False, reason
