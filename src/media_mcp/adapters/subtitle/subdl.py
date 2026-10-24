#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SubDL API provider."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    SubtitleSearchRequest,
)


LANGUAGE_TO_SUBDL = {
    'en': 'EN',
    'ja': 'JA',
    'ko': 'KO',
    'fr': 'FR',
    'de': 'DE',
    'es': 'ES',
    'ru': 'RU',
    'zh-cn': 'ZH',
    'zh-hans': 'ZH',
    'zh-hant': 'ZH',
    'zh-tw': 'ZH',
    'zh': 'ZH',
}

SUBDL_TO_LANGUAGE = {
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
    'zh': 'zh-CN',
    'zh-cn': 'zh-CN',
    'zh-hans': 'zh-CN',
    'chinese': 'zh-CN',
    'cn': 'zh-CN',
    'zh-hant': 'zh-Hant',
    'zh-tw': 'zh-Hant',
    'zt': 'zh-Hant',
    'big_5_code': 'zh-Hant',
}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


def _extension_name(name: str, fallback: str = 'srt') -> str:
    extension = os.path.splitext(name)[1].lower().lstrip('.')
    return extension if extension in {'srt', 'ass', 'ssa', 'vtt'} else fallback


def _download_extension(value: str) -> str:
    return os.path.splitext(urlsplit(value).path)[1].lower()


def _language_from_row(row: dict[str, Any]) -> str | None:
    values = (
        row.get('language'),
        row.get('lang'),
        row.get('language_code'),
        row.get('target_language'),
    )
    for value in values:
        key = str(value or '').strip().lower()
        if key in SUBDL_TO_LANGUAGE:
            return SUBDL_TO_LANGUAGE[key]
    return None


SENSITIVE_QUERY_KEYS = {'api_key', 'apikey', 'key', 'token', 'access_token'}


def _strip_sensitive_query(value: str) -> str:
    if not value or '?' not in value:
        return value
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY_KEYS
        ],
        doseq=True,
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _redact_sensitive_query(value: str) -> str:
    if not value or '?' not in value:
        return value
    parts = urlsplit(value)
    query = urlencode(
        [
            (key, '<redacted>' if key.lower() in SENSITIVE_QUERY_KEYS else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class SubDLProvider:
    name = 'subdl'

    def __init__(self):
        self.api_base_url = os.environ.get(
            'SUBDL_API_BASE_URL',
            'https://api.subdl.com/api/v1',
        ).rstrip('/')
        self.download_base_url = os.environ.get(
            'SUBDL_DOWNLOAD_BASE_URL',
            'https://dl.subdl.com',
        ).rstrip('/')
        self.api_key = os.environ.get('SUBDL_API_KEY', '').strip()
        self.timeout = float(os.environ.get('SUBDL_TIMEOUT_SECONDS', '30'))
        self.subs_per_page = int(os.environ.get('SUBDL_SUBS_PER_PAGE', '30'))
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        if not self.configured:
            return []
        languages = sorted(
            {
                LANGUAGE_TO_SUBDL[language.lower()]
                for language in request.languages
                if language.lower() in LANGUAGE_TO_SUBDL
            }
        )
        if not languages:
            return []
        params: dict[str, Any] = {
            'api_key': self.api_key,
            'type': 'tv' if request.media_type == 'tv' else 'movie',
            'languages': ','.join(languages),
            'subs_per_page': min(30, max(1, self.subs_per_page)),
            'releases': '1',
            'hi': '1',
        }
        if request.tmdb_id is not None:
            params['tmdb_id'] = request.tmdb_id
        elif request.title:
            params['film_name'] = request.title
        if request.year is not None:
            params['year'] = request.year
        if request.media_type == 'tv':
            if request.season is not None:
                params['season_number'] = request.season
            if request.episode is not None:
                params['episode_number'] = request.episode

        response = self.session.get(
            f'{self.api_base_url}/subtitles',
            params=params,
            headers={'Accept': 'application/json', 'User-Agent': 'phantom_slayer v1.0'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json() or {}
        if not payload.get('status'):
            raise RuntimeError(str(payload.get('error') or payload.get('message') or 'SubDL search failed'))

        result = (payload.get('results') or [{}])[0] or {}
        result_tmdb_id = _optional_int(result.get('tmdb_id'))
        media_type = str(result.get('type') or request.media_type or '').lower() or None
        candidates: list[OnlineSubtitleCandidate] = []
        for row in payload.get('subtitles') or []:
            if not isinstance(row, dict):
                continue
            candidates.extend(self._candidate_from_row(row, request, result_tmdb_id, media_type))
        return candidates

    def _candidate_from_row(
        self,
        row: dict[str, Any],
        request: SubtitleSearchRequest,
        tmdb_id: int | None,
        media_type: str | None,
    ) -> list[OnlineSubtitleCandidate]:
        url = str(row.get('url') or '').strip()
        if not url:
            return []
        safe_url = _strip_sensitive_query(url)
        if _download_extension(safe_url) not in {'.zip', '.srt', '.ass', '.ssa', '.vtt'}:
            return []
        language = _language_from_row(row)
        if not language:
            return []
        file_name = str(row.get('name') or row.get('release_name') or os.path.basename(safe_url) or 'subtitle.srt')
        file_id = str(row.get('file_n_id') or row.get('n_id') or row.get('id') or safe_url)
        subtitle_type = 'sdh' if row.get('hi') else 'normal'
        return [
            OnlineSubtitleCandidate(
                provider=self.name,
                candidate_id=file_id,
                file_id=safe_url,
                file_name=file_name,
                language=language,
                subtitle_type=subtitle_type,
                format=str(row.get('format') or _extension_name(file_name)),
                media_type='tv' if media_type == 'tv' else 'movie' if media_type == 'movie' else request.media_type,
                tmdb_id=tmdb_id if request.media_type != 'tv' else None,
                parent_tmdb_id=tmdb_id if request.media_type == 'tv' else None,
                season=_optional_int(row.get('season')) or request.season,
                episode=_optional_int(row.get('episode')) or request.episode,
                title=str(row.get('release_name') or row.get('name') or ''),
                release=str(row.get('release_name') or ''),
                fps=_optional_float(row.get('fps')),
                download_count=_optional_int(row.get('downloads') or row.get('download_count')) or 0,
                rating=_optional_float(row.get('rating') or row.get('rate')) or 0.0,
                hearing_impaired=bool(row.get('hi')),
                metadata={'url': safe_url, 'size': row.get('size'), 'md5': row.get('md5')},
            )
        ]

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        url = str(candidate.file_id)
        if url.startswith('/'):
            url = urljoin(f'{self.download_base_url}/', url.lstrip('/'))
        headers = {'User-Agent': 'phantom_slayer v1.0'}
        if self.api_key:
            headers['x-api-key'] = self.api_key
        response = self.session.get(url, headers=headers, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(_redact_sensitive_query(str(exc)), response=exc.response) from exc
        return DownloadedSubtitle(
            content=response.content,
            file_name=candidate.file_name,
            content_type=response.headers.get('Content-Type'),
        )
