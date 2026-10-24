#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SubtitleCat public web provider."""

from __future__ import annotations

import os
import re
from urllib.parse import quote_plus, urljoin

import requests

from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    SubtitleSearchRequest,
)
from media_mcp.adapters.subtitle.html_tools import extract_links


LANGUAGE_MAP = {
    'en': 'en',
    'english': 'en',
    'ja': 'ja',
    'japanese': 'ja',
    'jp': 'ja',
    'ko': 'ko',
    'korean': 'ko',
    'kr': 'ko',
    'fr': 'fr',
    'french': 'fr',
    'de': 'de',
    'german': 'de',
    'es': 'es',
    'spanish': 'es',
    'ru': 'ru',
    'russian': 'ru',
    'zh-cn': 'zh-CN',
    'zh-hans': 'zh-CN',
    'zh-tw': 'zh-Hant',
    'zh-hant': 'zh-Hant',
}


def _search_query(request: SubtitleSearchRequest) -> str:
    parts = [str(request.title or '').strip()]
    if request.year is not None:
        parts.append(str(request.year))
    if request.media_type == 'tv':
        if request.season is not None:
            parts.append(f'S{int(request.season):02d}')
        if request.episode is not None:
            parts.append(f'E{int(request.episode):02d}')
    return ' '.join(part for part in parts if part).strip()


def _language_from_link(href: str, element_id: str) -> str | None:
    values = [element_id.replace('download_', ''), href]
    for value in values:
        lowered = value.lower()
        for marker, language in LANGUAGE_MAP.items():
            if marker in lowered:
                return language
    return None


def _explicit_episode_marker(text: str) -> tuple[int | None, int | None] | None:
    for pattern in (
        re.compile(r'(?i)(?:^|[^a-z0-9])s(?P<season>\d{1,2})[\s._-]*e(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
        re.compile(r'(?i)(?:^|[^a-z0-9])(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
        re.compile(r'(?i)(?:^|[^a-z0-9])e(?:p(?:isode)?)?[\s._-]*(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
    ):
        match = pattern.search(text or '')
        if not match:
            continue
        season = match.groupdict().get('season')
        episode = match.groupdict().get('episode')
        if episode:
            return (int(season) if season else None, int(episode))
    return None


class SubtitleCatProvider:
    name = 'subtitlecat'

    def __init__(self):
        self.base_url = os.environ.get('SUBTITLECAT_BASE_URL', 'https://www.subtitlecat.com').rstrip('/')
        self.timeout = float(os.environ.get('SUBTITLECAT_TIMEOUT_SECONDS', '30'))
        self.result_limit = int(os.environ.get('SUBTITLECAT_RESULT_LIMIT', '5'))
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return True

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        if not self.configured:
            return []
        query = _search_query(request)
        if len(query) < 3:
            return []
        response = self.session.get(
            f'{self.base_url}/index.php?search={quote_plus(query)}',
            headers={'User-Agent': 'phantom_slayer v1.0'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        page_links = self._result_pages(response.text)
        candidates: list[OnlineSubtitleCandidate] = []
        for href, title in page_links[: max(1, self.result_limit)]:
            candidates.extend(self._language_candidates(href, title, request))
        return candidates

    def _result_pages(self, html: str) -> list[tuple[str, str]]:
        pages: list[tuple[str, str]] = []
        seen: set[str] = set()
        for link in extract_links(html):
            href = link.href.strip()
            if not re.match(r'/?subs/\d+/.+\.html$', href):
                continue
            absolute = urljoin(f'{self.base_url}/', href)
            if absolute in seen:
                continue
            seen.add(absolute)
            pages.append((absolute, link.text or os.path.splitext(os.path.basename(href))[0]))
        return pages

    def _language_candidates(
        self,
        page_url: str,
        title: str,
        request: SubtitleSearchRequest,
    ) -> list[OnlineSubtitleCandidate]:
        response = self.session.get(
            page_url,
            headers={'User-Agent': 'phantom_slayer v1.0'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        candidates: list[OnlineSubtitleCandidate] = []
        for link in extract_links(response.text):
            href = link.href.strip()
            element_id = link.attrs.get('id', '')
            if not element_id.startswith('download_') and 'Download' not in link.text:
                continue
            language = _language_from_link(href, element_id)
            if not language:
                continue
            absolute = urljoin(f'{self.base_url}/', href)
            file_name = os.path.basename(href) or f'{title}.srt'
            marker = _explicit_episode_marker(f'{title} {file_name}')
            season = request.season
            episode = request.episode
            if request.media_type == 'tv' and marker:
                marker_season, marker_episode = marker
                if request.season is not None and marker_season is not None and marker_season != request.season:
                    continue
                if request.episode is not None and marker_episode != request.episode:
                    continue
                season = marker_season or request.season
                episode = marker_episode
            candidates.append(
                OnlineSubtitleCandidate(
                    provider=self.name,
                    candidate_id=f'{page_url}#{element_id or language}',
                    file_id=absolute,
                    file_name=file_name,
                    language=language,
                    subtitle_type='normal',
                    format='srt',
                    media_type=request.media_type,
                    tmdb_id=request.tmdb_id if request.media_type != 'tv' else None,
                    parent_tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
                    season=season,
                    episode=episode,
                    title=title,
                    release=title,
                    machine_translated=True,
                    metadata={'page_url': page_url},
                )
            )
        return candidates

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        response = self.session.get(
            str(candidate.file_id),
            headers={'User-Agent': 'phantom_slayer v1.0'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return DownloadedSubtitle(
            content=response.content,
            file_name=candidate.file_name,
            content_type=response.headers.get('Content-Type'),
        )
