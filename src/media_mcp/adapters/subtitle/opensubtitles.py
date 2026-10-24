#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenSubtitles.com REST API provider."""

from __future__ import annotations

import json
import os
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from media_mcp.ingest.domain.path_builder import MEDIA_ROOT
from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    ProviderTemporarilyUnavailable,
    SubtitleSearchRequest,
)


LANGUAGE_MAP = {
    'en': 'en',
    'eng': 'en',
    'english': 'en',
    'ja': 'ja',
    'jpn': 'ja',
    'jp': 'ja',
    'japanese': 'ja',
    'ko': 'ko',
    'kor': 'ko',
    'kr': 'ko',
    'korean': 'ko',
    'fr': 'fr',
    'fre': 'fr',
    'fra': 'fr',
    'french': 'fr',
    'de': 'de',
    'ger': 'de',
    'deu': 'de',
    'german': 'de',
    'es': 'es',
    'spa': 'es',
    'spanish': 'es',
    'ru': 'ru',
    'rus': 'ru',
    'russian': 'ru',
    'zh-cn': 'zh-CN',
    'zh-hans': 'zh-CN',
    'zh-tw': 'zh-Hant',
    'zh-hant': 'zh-Hant',
    'zh': 'zh',
}

REQUEST_LANGUAGE_MAP = {
    'en': 'en',
    'ja': 'ja',
    'ko': 'ko',
    'fr': 'fr',
    'de': 'de',
    'es': 'es',
    'ru': 'ru',
    'zh-cn': 'zh-CN',
    'zh-hans': 'zh-CN',
    'zh-tw': 'zh-Hant',
    'zh-hant': 'zh-Hant',
    'zh': 'zh',
}


def _default_rate_limit_state_file() -> str:
    return os.path.join(
        MEDIA_ROOT,
        '.subtitle-provider-state',
        'opensubtitles_rate_limit.json',
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class OpenSubtitlesProvider:
    name = 'opensubtitles'

    def __init__(self):
        self.base_url = os.environ.get(
            'OPENSUBTITLES_BASE_URL',
            'https://api.opensubtitles.com/api/v1',
        ).rstrip('/')
        self.api_key = os.environ.get('OPENSUBTITLES_API_KEY', '').strip()
        self.user_agent = os.environ.get(
            'OPENSUBTITLES_USER_AGENT',
            'phantom_slayer v1.0',
        ).strip()
        self.username = os.environ.get('OPENSUBTITLES_USERNAME', '').strip()
        self.password = os.environ.get('OPENSUBTITLES_PASSWORD', '').strip()
        self.timeout = float(os.environ.get('OPENSUBTITLES_TIMEOUT_SECONDS', '30'))
        self.rate_limit_state_file = os.environ.get(
            'OPENSUBTITLES_RATE_LIMIT_STATE_FILE',
            _default_rate_limit_state_file(),
        ).strip()
        self.default_throttle_seconds = int(
            os.environ.get('OPENSUBTITLES_THROTTLE_SECONDS', '900')
        )
        self.default_quota_seconds = int(
            os.environ.get('OPENSUBTITLES_QUOTA_SECONDS', '86400')
        )
        self.session = requests.Session()
        self._token: str | None = None
        self._blocked_until = 0.0
        self._blocked_reason = ''
        self._load_rate_limit_state()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.user_agent)

    def _load_rate_limit_state(self) -> None:
        if not self.rate_limit_state_file:
            return
        try:
            with open(self.rate_limit_state_file, 'r', encoding='utf-8') as handle:
                state = json.load(handle)
        except (OSError, ValueError, TypeError):
            return
        blocked_until = _optional_float(state.get('blocked_until')) or 0.0
        if blocked_until > time.time():
            self._blocked_until = blocked_until
            self._blocked_reason = str(state.get('reason') or 'rate limit')

    def _save_rate_limit_state(self) -> None:
        if not self.rate_limit_state_file:
            return
        directory = os.path.dirname(self.rate_limit_state_file)
        temporary_path = f'{self.rate_limit_state_file}.part'
        try:
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(temporary_path, 'w', encoding='utf-8') as handle:
                json.dump(
                    {
                        'provider': self.name,
                        'blocked_until': self._blocked_until,
                        'reason': self._blocked_reason,
                        'updated_at': time.time(),
                    },
                    handle,
                )
            os.replace(temporary_path, self.rate_limit_state_file)
        except OSError:
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
            except OSError:
                pass

    def _ensure_available(self) -> None:
        if self._blocked_until <= time.time():
            return
        raise ProviderTemporarilyUnavailable(
            self.name,
            self._blocked_reason or 'OpenSubtitles temporarily unavailable',
            self._blocked_until,
        )

    def _retry_at_from_headers(self, response, default_seconds: int) -> float:
        now = time.time()
        retry_after = str(response.headers.get('Retry-After') or '').strip()
        if retry_after:
            try:
                return now + max(1, int(float(retry_after)))
            except ValueError:
                try:
                    return max(now + 1, parsedate_to_datetime(retry_after).timestamp())
                except (TypeError, ValueError, OverflowError):
                    pass
        for name in (
            'RateLimit-Reset',
            'X-RateLimit-Reset',
            'X-RateLimit-Reset-After',
        ):
            value = str(response.headers.get(name) or '').strip()
            if not value:
                continue
            try:
                parsed = float(value)
            except ValueError:
                continue
            return parsed if parsed > now else now + max(1, parsed)
        return now + default_seconds

    def _response_message(self, response) -> str:
        try:
            payload = response.json() or {}
        except (ValueError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            return str(payload.get('message') or payload.get('error') or '').strip()
        return ''

    def _record_exhausted_quota(self, response, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        remaining_values = (
            response.headers.get('RateLimit-Remaining'),
            response.headers.get('X-RateLimit-Remaining'),
            payload.get('remaining'),
        )
        remaining = next(
            (
                parsed
                for value in remaining_values
                if (parsed := _optional_int(value)) is not None
            ),
            None,
        )
        if remaining is None or remaining > 0:
            return
        self._blocked_until = self._retry_at_from_headers(
            response,
            self.default_quota_seconds,
        )
        reset_time = str(
            payload.get('reset_time_utc')
            or payload.get('reset_time')
            or ''
        ).strip()
        self._blocked_reason = 'OpenSubtitles download quota exhausted'
        if reset_time:
            self._blocked_reason += f'; reset={reset_time}'
        self._save_rate_limit_state()

    def _check_rate_limit(self, response, operation: str) -> None:
        message = self._response_message(response)
        lowered = message.lower()
        quota_exhausted = (
            response.status_code == 406
            or 'download limit' in lowered
            or 'download quota' in lowered
            or 'quota' in lowered
        )
        throttled = response.status_code == 429 or 'throttle limit' in lowered
        if not quota_exhausted and not throttled:
            return
        default_seconds = (
            self.default_quota_seconds if quota_exhausted else self.default_throttle_seconds
        )
        self._blocked_until = self._retry_at_from_headers(response, default_seconds)
        kind = 'download quota exhausted' if quota_exhausted else 'request throttled'
        self._blocked_reason = (
            f'OpenSubtitles {kind} during {operation}'
            + (f': {message}' if message else '')
        )
        self._save_rate_limit_state()
        raise ProviderTemporarilyUnavailable(
            self.name,
            self._blocked_reason,
            self._blocked_until,
        )

    def _headers(self, *, authenticated: bool = False) -> dict[str, str]:
        headers = {
            'Api-Key': self.api_key,
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
        }
        if authenticated:
            token = self._login()
            if token:
                headers['Authorization'] = f'Bearer {token}'
        return headers

    def _login(self) -> str | None:
        self._ensure_available()
        if self._token:
            return self._token
        if not self.username or not self.password:
            return None
        response = self.session.post(
            f'{self.base_url}/login',
            headers=self._headers(authenticated=False),
            json={'username': self.username, 'password': self.password},
            timeout=self.timeout,
        )
        self._check_rate_limit(response, 'login')
        response.raise_for_status()
        self._token = str((response.json() or {}).get('token') or '') or None
        return self._token

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        if not self.configured:
            return []
        self._ensure_available()
        languages = sorted(
            {
                REQUEST_LANGUAGE_MAP[language.lower()]
                for language in request.languages
                if language.lower() in REQUEST_LANGUAGE_MAP
            }
        )
        if not languages:
            return []
        params: dict[str, Any] = {
            'languages': ','.join(languages),
            'order_by': 'download_count',
            'order_direction': 'desc',
            'page': 1,
        }
        if request.media_type == 'tv':
            params['type'] = 'episode'
            if request.tmdb_id is not None:
                params['parent_tmdb_id'] = request.tmdb_id
            if request.season is not None:
                params['season_number'] = request.season
            if request.episode is not None:
                params['episode_number'] = request.episode
        else:
            params['type'] = 'movie'
            if request.tmdb_id is not None:
                params['tmdb_id'] = request.tmdb_id
        if request.title and request.tmdb_id is None:
            params['query'] = request.title
        if request.year is not None and request.tmdb_id is None:
            params['year'] = request.year

        response = self.session.get(
            f'{self.base_url}/subtitles',
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        self._check_rate_limit(response, 'search')
        response.raise_for_status()
        rows = (response.json() or {}).get('data') or []
        candidates: list[OnlineSubtitleCandidate] = []
        for row in rows:
            attributes = row.get('attributes') or {}
            feature = attributes.get('feature_details') or {}
            files = attributes.get('files') or []
            feature_type = str(feature.get('feature_type') or '').lower()
            media_type = {
                'episode': 'tv',
                'movie': 'movie',
            }.get(feature_type)
            language = LANGUAGE_MAP.get(str(attributes.get('language') or '').lower())
            if not language:
                continue
            subtitle_type = 'normal'
            if attributes.get('foreign_parts_only'):
                subtitle_type = 'forced'
            elif attributes.get('hearing_impaired'):
                subtitle_type = 'sdh'
            for file_item in files:
                file_id = file_item.get('file_id')
                file_name = str(file_item.get('file_name') or '')
                if file_id is None or not file_name:
                    continue
                candidates.append(
                    OnlineSubtitleCandidate(
                        provider=self.name,
                        candidate_id=str(row.get('id') or attributes.get('subtitle_id') or file_id),
                        file_id=file_id,
                        file_name=file_name,
                        language=language,
                        subtitle_type=subtitle_type,
                        format='srt',
                        media_type=media_type,
                        tmdb_id=_optional_int(feature.get('tmdb_id')),
                        parent_tmdb_id=_optional_int(feature.get('parent_tmdb_id')),
                        season=_optional_int(feature.get('season_number')),
                        episode=_optional_int(feature.get('episode_number')),
                        title=feature.get('movie_name') or feature.get('title'),
                        release=attributes.get('release'),
                        fps=_optional_float(attributes.get('fps')),
                        download_count=_optional_int(attributes.get('download_count')) or 0,
                        rating=_optional_float(attributes.get('ratings')) or 0.0,
                        trusted=bool(attributes.get('from_trusted')),
                        machine_translated=bool(
                            attributes.get('machine_translated')
                            or attributes.get('ai_translated')
                        ),
                        hearing_impaired=bool(attributes.get('hearing_impaired')),
                        foreign_parts_only=bool(attributes.get('foreign_parts_only')),
                        metadata={
                            'subtitle_id': attributes.get('subtitle_id'),
                            'url': attributes.get('url'),
                            'upload_date': attributes.get('upload_date'),
                        },
                    )
                )
        return candidates

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        self._ensure_available()
        headers = self._headers(authenticated=bool(self.username and self.password))
        headers['Content-Type'] = 'application/json'
        response = self.session.post(
            f'{self.base_url}/download',
            headers=headers,
            json={'file_id': candidate.file_id, 'sub_format': 'srt'},
            timeout=self.timeout,
        )
        self._check_rate_limit(response, 'download')
        response.raise_for_status()
        payload = response.json() or {}
        if isinstance(payload, dict):
            self._record_exhausted_quota(response, payload)
        link = payload.get('link')
        if not link:
            raise RuntimeError(payload.get('message') or 'OpenSubtitles returned no download link')
        file_response = self.session.get(link, timeout=self.timeout)
        file_response.raise_for_status()
        return DownloadedSubtitle(
            content=file_response.content,
            file_name=str(payload.get('file_name') or candidate.file_name or 'subtitle.srt'),
            content_type=file_response.headers.get('Content-Type'),
        )
