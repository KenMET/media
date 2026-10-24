#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subtitle provider proxy backed by the cloud MCP subtitle tools."""

from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from media_mcp.adapters.dispatch import mcp_direct_call_ns
from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    ProviderTemporarilyUnavailable,
    SubtitleSearchRequest,
)


TRANSIENT_PROVIDER_ERROR_COOLDOWN_SECONDS = int(os.environ.get('SUBTITLE_PROVIDER_ERROR_COOLDOWN_SECONDS', '1800'))


def _provider_unavailable_from_error(provider: str, exc: Exception) -> ProviderTemporarilyUnavailable | None:
    message = str(exc)
    retry_at = None
    if 'ProviderTemporarilyUnavailable' in message:
        reset_match = re.search(r'\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\)', message)
        if reset_match:
            try:
                retry_at = datetime.strptime(reset_match.group(1), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                retry_at = None
        match = re.search(r'\bts=(\d+)', message)
        if retry_at is None and match:
            try:
                retry_at = float(match.group(1))
            except ValueError:
                retry_at = None
        reason = message.split('ProviderTemporarilyUnavailable:', 1)[-1].strip() or message
        return ProviderTemporarilyUnavailable(provider, reason, retry_at)

    transient_patterns = (
        r'\bHTTPError:\s*(?:429|5\d\d)\b',
        r'\b(?:429|5\d\d)\s+(?:Server Error|Service Unavailable|Bad Gateway|Gateway Timeout)',
        r'\b(?:timed out|timeout|connection error|connection reset|temporarily unavailable)\b',
    )
    if not any(re.search(pattern, message, flags=re.IGNORECASE) for pattern in transient_patterns):
        return None
    retry_at = time.time() + TRANSIENT_PROVIDER_ERROR_COOLDOWN_SECONDS
    reason = f'transient provider error: {message}'
    return ProviderTemporarilyUnavailable(provider, reason, retry_at)


def _candidate_from_payload(provider: str, payload: dict[str, Any]) -> OnlineSubtitleCandidate:
    return OnlineSubtitleCandidate(
        provider=provider,
        candidate_id=str(payload.get('candidate_id') or payload.get('file_id') or ''),
        file_id=payload.get('file_id'),
        file_name=str(payload.get('file_name') or 'subtitle.srt'),
        language=str(payload.get('language') or ''),
        subtitle_type=str(payload.get('subtitle_type') or 'normal'),
        format=str(payload.get('format') or 'srt'),
        media_type=payload.get('media_type'),
        tmdb_id=payload.get('tmdb_id'),
        parent_tmdb_id=payload.get('parent_tmdb_id'),
        season=payload.get('season'),
        episode=payload.get('episode'),
        title=payload.get('title'),
        release=payload.get('release'),
        fps=payload.get('fps'),
        download_count=int(payload.get('download_count') or 0),
        rating=float(payload.get('rating') or 0.0),
        trusted=bool(payload.get('trusted')),
        machine_translated=bool(payload.get('machine_translated')),
        hearing_impaired=bool(payload.get('hearing_impaired')),
        foreign_parts_only=bool(payload.get('foreign_parts_only')),
        metadata=dict(payload.get('metadata') or {}),
    )


class CloudMCPSubtitleProvider:
    def __init__(self, provider_name: str):
        self.name = provider_name

    @property
    def configured(self) -> bool:
        return True

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        candidates: list[OnlineSubtitleCandidate] = []
        for language in request.languages:
            try:
                result = mcp_direct_call_ns(
                    'subtitle.search',
                    provider=self.name,
                    query=request.title or '',
                    language=language,
                    media_type=request.media_type,
                    tmdb_id=request.tmdb_id,
                    year=request.year,
                    season=request.season,
                    episode=request.episode,
                )
            except Exception as exc:
                unavailable = _provider_unavailable_from_error(self.name, exc)
                if unavailable:
                    raise unavailable
                raise
            rows = result.get('candidates') if isinstance(result, dict) else None
            for row in rows or []:
                if isinstance(row, dict):
                    candidates.append(_candidate_from_payload(self.name, row))
        return candidates

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        try:
            result = mcp_direct_call_ns(
                'subtitle.download',
                provider=self.name,
                file_id=str(candidate.file_id),
                candidate=asdict(candidate),
                file_name=candidate.file_name,
                language=candidate.language,
                subtitle_type=candidate.subtitle_type,
                fmt=candidate.format,
            )
        except Exception as exc:
            unavailable = _provider_unavailable_from_error(self.name, exc)
            if unavailable:
                raise unavailable
            raise
        if not isinstance(result, dict):
            raise RuntimeError('cloud subtitle download returned non-object response')
        content_base64 = result.get('content_base64')
        if not content_base64:
            raise RuntimeError('cloud subtitle download returned empty content')
        return DownloadedSubtitle(
            content=base64.b64decode(content_base64),
            file_name=str(result.get('file_name') or candidate.file_name or 'subtitle.srt'),
            content_type=result.get('content_type'),
        )
