#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ASSRT API and web fallback provider."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urljoin
import zipfile

import requests

from media_mcp.adapters.subtitle.html_tools import extract_links
from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    SubtitleSearchRequest,
)


TEXT_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt'}
ASSRT_WEB_BASE_URL = 'https://assrt.net'
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
DETAIL_HREF_RE = re.compile(r'^/xml/sub/(?P<prefix>\d+)/(?P<id>\d+)\.xml$')
ONTHEFLY_RE = re.compile(
    r'onthefly\(\s*["\'](?P<subtitle_id>\d+)["\']\s*,\s*["\'](?P<file_index>\d+)["\']\s*,\s*["\'](?P<file_name>.*?)["\']\s*\)'
)


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


def _query(request: SubtitleSearchRequest) -> str:
    parts = [str(request.title or '').strip()]
    if request.year is not None:
        parts.append(str(request.year))
    if request.media_type == 'tv':
        if request.season is not None:
            parts.append(f'S{int(request.season):02d}')
        if request.episode is not None:
            parts.append(f'E{int(request.episode):02d}')
    return ' '.join(part for part in parts if part).strip()


def _query_variants(request: SubtitleSearchRequest) -> list[str]:
    variants = [_query(request), str(request.title or '').strip()]
    seen: set[str] = set()
    result: list[str] = []
    for value in variants:
        key = re.sub(r'\s+', ' ', value).strip().casefold()
        if key in seen:
            continue
        if len(key) < 3 and not re.search(r'[\u4e00-\u9fff]{2,}', key):
            continue
        seen.add(key)
        result.append(value.strip())
    return result


def _subtitle_format(value: Any, file_name: str = '') -> str:
    text = f'{value or ""} {file_name}'.lower()
    if 'ass' in text or 'ssa' in text:
        return 'ass'
    if 'vtt' in text:
        return 'vtt'
    return 'srt'


def _language_from_lang(lang: dict[str, Any] | None) -> str | None:
    if not isinstance(lang, dict):
        return None
    langlist = lang.get('langlist') or {}
    desc = str(lang.get('desc') or '')
    if (
        langlist.get('langdou')
        or '\u53cc\u8bed' in desc
        or '\u4e2d\u82f1' in desc
        or '\u7b80\u82f1' in desc
        or '\u7e41\u82f1' in desc
        or '\u7b80\u65e5' in desc
        or '\u7e41\u65e5' in desc
    ):
        return 'zh-CN-bilingual'
    if langlist.get('langchs') or '\u7b80' in desc:
        return 'zh-CN'
    if langlist.get('langcht') or '\u7e41' in desc:
        return 'zh-Hant'
    return None


def _language_from_text(text: str) -> str | None:
    if any(
        marker in text
        for marker in (
            '\u53cc\u8bed',
            '\u4e2d\u82f1',
            '\u7b80\u82f1',
            '\u7e41\u82f1',
            '\u7b80\u65e5',
            '\u7e41\u65e5',
        )
    ):
        return 'zh-CN-bilingual'
    if '\u7b80' in text:
        return 'zh-CN'
    if '\u7e41' in text:
        return 'zh-Hant'
    return None


def _file_matches_episode(file_name: str, request: SubtitleSearchRequest) -> bool:
    if request.media_type != 'tv' or request.episode is None:
        return True
    episode = int(request.episode)
    season = int(request.season or 1)
    season_token = rf'0?{season}' if season < 10 else str(season)
    episode_token = rf'0?{episode}' if episode < 10 else str(episode)
    explicit_patterns = [
        rf'(?i)(?:^|[^A-Za-z0-9])S{season_token}[\s._-]*E{episode_token}(?:[^A-Za-z0-9]|$)',
        rf'(?i)(?:^|[^A-Za-z0-9]){season_token}x{episode_token}(?:[^A-Za-z0-9]|$)',
    ]
    any_explicit = re.search(
        r'(?i)(?:^|[^A-Za-z0-9])S\d{1,2}[\s._-]*E\d{1,3}(?:[^A-Za-z0-9]|$)|'
        r'(?:^|[^A-Za-z0-9])\d{1,2}x\d{1,3}(?:[^A-Za-z0-9]|$)',
        file_name,
    )
    if any_explicit:
        return any(re.search(pattern, file_name) for pattern in explicit_patterns)
    patterns = [
        rf'(?i)\bE{episode_token}\b',
        rf'(?<!\d){episode:02d}(?!\d)',
        rf'(?i)(?:^|[\s._\-\[\(]){episode}(?:[\s._\-\]\)]|$)',
    ]
    return any(re.search(pattern, file_name) for pattern in patterns)


def _looks_like_sequel_for_first_season(text: str, request: SubtitleSearchRequest) -> bool:
    if request.media_type != 'tv' or int(request.season or 1) != 1:
        return False
    request_title = str(request.title or '')
    if re.search(r'(?i)\b(?:zoku|2nd|second)\b|续章|續章|続章', request_title):
        return False
    return bool(re.search(r'(?i)\b(?:zoku|2nd|second)\b|续章|續章|続章', text))


def _matches_request_title(text: str, request: SubtitleSearchRequest) -> bool:
    title = re.sub(r'\s+', '', str(request.title or '')).casefold()
    haystack = re.sub(r'\s+', '', text).casefold()
    if not title:
        return True
    cjk_chars = re.findall(r'[\u4e00-\u9fff]', title)
    if len(cjk_chars) >= 2:
        return all(char in haystack for char in cjk_chars)
    words = [word for word in re.split(r'[^a-z0-9]+', title) if len(word) >= 3]
    if words:
        return all(word in haystack for word in words[:3])
    return title in haystack


def _matches_request_context(text: str, request: SubtitleSearchRequest) -> bool:
    if _looks_like_sequel_for_first_season(text, request):
        return False
    return _matches_request_title(text, request)


def _web_result_download_count(text: str) -> int:
    match = re.search(r'\u4e0b\u8f7d\u6b21\u6570[^\d]*(\d+)', text)
    return int(match.group(1)) if match else 0


def _is_archive_content(content: bytes, file_name: str = '') -> bool:
    suffix = os.path.splitext(file_name)[1].lower()
    return (
        content.startswith(b'PK\x03\x04')
        or content.startswith(b'Rar!\x1a\x07\x00')
        or content.startswith(b'\x1f\x8b')
        or suffix in {'.zip', '.rar', '.gz'}
    )


def _archive_extension(content: bytes, file_name: str = '') -> str:
    suffix = os.path.splitext(file_name)[1].lower()
    if content.startswith(b'PK\x03\x04') or suffix == '.zip':
        return '.zip'
    if content.startswith(b'Rar!\x1a\x07\x00') or suffix == '.rar':
        return '.rar'
    if content.startswith(b'\x1f\x8b') or suffix == '.gz':
        return '.gz'
    return suffix or '.bin'


def _atomic_write(path: str, content: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f'{path}.part'
    with open(temporary_path, 'wb') as handle:
        handle.write(content)
    os.replace(temporary_path, path)


def _default_cache_dir() -> str:
    root = (
        os.environ.get('ASSRT_CACHE_DIR')
        or os.environ.get('MEDIA_CACHE_DIR')
        or os.environ.get('PHANTOM_CACHE_DIR')
        or os.path.join(os.path.expanduser('~'), '.cache', 'phantom_slayer')
    )
    if os.path.basename(os.path.normpath(root)) == 'assrt':
        return root
    return os.path.join(root, 'assrt')


class AssrtProvider:
    name = 'assrt'

    def __init__(self):
        self.base_url = os.environ.get('ASSRT_API_BASE_URL', 'https://api.assrt.net/v1').rstrip('/')
        self.web_base_url = os.environ.get('ASSRT_WEB_BASE_URL', ASSRT_WEB_BASE_URL).rstrip('/')
        self.cache_dir = _default_cache_dir()
        self.token = os.environ.get('ASSRT_API_KEY', '').strip()
        self.timeout = float(os.environ.get('ASSRT_TIMEOUT_SECONDS', '30'))
        self.count = int(os.environ.get('ASSRT_SEARCH_COUNT', '15'))
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        if not self.configured:
            return []
        candidates: list[OnlineSubtitleCandidate] = []
        for query in _query_variants(request):
            payload = self._api_get(
                'sub/search',
                {
                    'q': query,
                    'cnt': min(15, max(1, self.count)),
                    'pos': 0,
                    'filelist': 1,
                },
            )
            rows = ((payload.get('sub') or {}).get('subs') or [])
            for row in rows:
                if isinstance(row, dict):
                    candidates.extend(self._candidates_from_row(row, request))
            if candidates:
                return self._dedupe_candidates(candidates)
        return self._web_search(request)

    def _candidates_from_row(
        self,
        row: dict[str, Any],
        request: SubtitleSearchRequest,
    ) -> list[OnlineSubtitleCandidate]:
        language = _language_from_lang(row.get('lang'))
        if not language:
            language = _language_from_text(
                ' '.join(str(row.get(key) or '') for key in ('lang', 'native_name', 'videoname', 'filename'))
            )
        if not language:
            return []
        subtitle_id = _optional_int(row.get('id'))
        if subtitle_id is None:
            return []
        title = str(row.get('native_name') or row.get('videoname') or '')
        common = dict(
            provider=self.name,
            language=language,
            subtitle_type='normal',
            media_type=request.media_type,
            tmdb_id=request.tmdb_id if request.media_type != 'tv' else None,
            parent_tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
            season=request.season,
            episode=request.episode,
            title=title,
            release=str(row.get('release_site') or ''),
            download_count=_optional_int(row.get('down_count')) or 0,
            rating=_optional_float(row.get('vote_score')) or 0.0,
            machine_translated=bool(row.get('vote_machine_translate')),
        )
        candidates: list[OnlineSubtitleCandidate] = []
        for index, item in enumerate(row.get('filelist') or []):
            if not isinstance(item, dict):
                continue
            file_name = str(item.get('f') or item.get('filename') or '')
            if os.path.splitext(file_name)[1].lower() not in TEXT_EXTENSIONS:
                continue
            if not _file_matches_episode(file_name, request):
                continue
            if not _matches_request_context(f'{title} {file_name}', request):
                continue
            file_index = str(item.get('id') or item.get('no') or item.get('file_index') or index + 1)
            candidates.append(
                OnlineSubtitleCandidate(
                    **common,
                    candidate_id=f'{subtitle_id}:{file_index}',
                    file_id=f'{subtitle_id}:{file_index}',
                    file_name=file_name,
                    format=_subtitle_format(row.get('subtype'), file_name),
                    metadata={
                        'assrt_detail_id': subtitle_id,
                        'assrt_file_index': file_index,
                        'upload_time': row.get('upload_time'),
                        'videoname': row.get('videoname'),
                        'download_url': item.get('url'),
                    },
                )
            )
        if candidates:
            return candidates
        file_name = str(row.get('filename') or row.get('videoname') or title or f'{subtitle_id}.srt')
        return [
            OnlineSubtitleCandidate(
                **common,
                candidate_id=str(subtitle_id),
                file_id=subtitle_id,
                file_name=file_name,
                format=_subtitle_format(row.get('subtype'), file_name),
                metadata={'upload_time': row.get('upload_time'), 'videoname': row.get('videoname')},
            )
        ]

    def _web_search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        candidates: list[OnlineSubtitleCandidate] = []
        seen_detail_ids: set[int] = set()
        for query in _query_variants(request):
            response = self.session.get(
                f'{self.web_base_url}/sub/',
                params={'searchword': query},
                headers={'User-Agent': 'phantom_slayer v1.0'},
                timeout=self.timeout,
            )
            response.raise_for_status()
            for link in extract_links(response.text):
                match = DETAIL_HREF_RE.match(link.href)
                if not match:
                    continue
                subtitle_id = int(match.group('id'))
                if subtitle_id in seen_detail_ids:
                    continue
                seen_detail_ids.add(subtitle_id)
                candidates.extend(
                    self._candidates_from_web_detail(
                        subtitle_id,
                        urljoin(self.web_base_url, link.href),
                        link.text,
                        request,
                    )
                )
                if len(seen_detail_ids) >= min(10, max(1, self.count)):
                    break
            if candidates:
                return self._dedupe_candidates(candidates)
        return []

    def _candidates_from_web_detail(
        self,
        subtitle_id: int,
        detail_url: str,
        search_text: str,
        request: SubtitleSearchRequest,
    ) -> list[OnlineSubtitleCandidate]:
        response = self.session.get(
            detail_url,
            headers={'User-Agent': 'phantom_slayer v1.0', 'Referer': f'{self.web_base_url}/'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        html = response.text
        language = _language_from_text(f'{search_text} {html}') or 'zh-CN'
        title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r'\s+', ' ', title_match.group(1)).strip() if title_match else search_text
        download_count = _web_result_download_count(html)
        candidates: list[OnlineSubtitleCandidate] = []
        for item in ONTHEFLY_RE.finditer(html):
            file_name = item.group('file_name')
            if os.path.splitext(file_name)[1].lower() not in TEXT_EXTENSIONS:
                continue
            if not _file_matches_episode(file_name, request):
                continue
            if not _matches_request_context(f'{title} {search_text} {file_name}', request):
                continue
            file_index = item.group('file_index')
            candidates.append(
                OnlineSubtitleCandidate(
                    provider=self.name,
                    candidate_id=f'{subtitle_id}:{file_index}',
                    file_id=f'{subtitle_id}:{file_index}',
                    file_name=file_name,
                    language=language,
                    subtitle_type='normal',
                    format=_subtitle_format(None, file_name),
                    media_type=request.media_type,
                    tmdb_id=request.tmdb_id if request.media_type != 'tv' else None,
                    parent_tmdb_id=request.tmdb_id if request.media_type == 'tv' else None,
                    season=request.season,
                    episode=request.episode,
                    title=title,
                    download_count=download_count,
                    metadata={
                        'assrt_detail_id': subtitle_id,
                        'assrt_file_index': file_index,
                        'assrt_detail_url': detail_url,
                        'source': 'web',
                    },
                )
            )
        return candidates

    def _dedupe_candidates(self, candidates: list[OnlineSubtitleCandidate]) -> list[OnlineSubtitleCandidate]:
        result: list[OnlineSubtitleCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate.file_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        return result

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        detail_id = candidate.metadata.get('assrt_detail_id') or str(candidate.file_id).split(':', 1)[0]
        cached = self._download_from_cache(str(detail_id), candidate)
        if cached:
            return cached
        payload = self._api_get('sub/detail', {'id': detail_id})
        rows = ((payload.get('sub') or {}).get('subs') or [])
        if not rows:
            raise RuntimeError('ASSRT detail returned no subtitles')
        detail = rows[0] or {}
        url, file_name = self._select_download_url(detail, candidate)
        response = self.session.get(
            url,
            headers={'User-Agent': 'phantom_slayer v1.0', 'Referer': 'https://assrt.net/'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.content
        if _is_archive_content(content, file_name):
            cached_archive = self._cache_archive(str(detail_id), content, file_name)
            extracted = self._extract_cached_archive_member(cached_archive, candidate)
            if extracted:
                extracted_content, extracted_name = extracted
                return DownloadedSubtitle(
                    content=extracted_content,
                    file_name=extracted_name,
                    content_type=response.headers.get('Content-Type'),
                )
        else:
            self._cache_member(str(detail_id), candidate, content, file_name)
        return DownloadedSubtitle(
            content=content,
            file_name=file_name,
            content_type=response.headers.get('Content-Type'),
        )

    def _download_from_cache(
        self,
        detail_id: str,
        candidate: OnlineSubtitleCandidate,
    ) -> DownloadedSubtitle | None:
        member_path = self._member_cache_path(detail_id, candidate)
        if member_path and os.path.exists(member_path):
            with open(member_path, 'rb') as handle:
                return DownloadedSubtitle(
                    content=handle.read(MAX_MEMBER_BYTES + 1),
                    file_name=candidate.file_name,
                    content_type='application/octet-stream',
                )
        for archive_path in self._archive_cache_paths(detail_id):
            extracted = self._extract_cached_archive_member(archive_path, candidate)
            if extracted:
                content, file_name = extracted
                self._cache_member(detail_id, candidate, content, file_name)
                return DownloadedSubtitle(
                    content=content,
                    file_name=file_name,
                    content_type='application/octet-stream',
                )
        return None

    def _archive_cache_paths(self, detail_id: str) -> list[str]:
        safe_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', detail_id)
        directory = os.path.join(self.cache_dir, safe_id)
        return [
            os.path.join(directory, f'archive{extension}')
            for extension in ('.zip', '.rar', '.gz')
            if os.path.exists(os.path.join(directory, f'archive{extension}'))
        ]

    def _cache_archive(self, detail_id: str, content: bytes, file_name: str) -> str:
        if len(content) > MAX_ARCHIVE_BYTES:
            raise RuntimeError('ASSRT archive exceeds cache size limit')
        safe_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', detail_id)
        path = os.path.join(self.cache_dir, safe_id, f'archive{_archive_extension(content, file_name)}')
        if not os.path.exists(path):
            _atomic_write(path, content)
        return path

    def _member_cache_path(self, detail_id: str, candidate: OnlineSubtitleCandidate) -> str | None:
        file_index = str(candidate.metadata.get('assrt_file_index') or '').strip()
        if not file_index:
            return None
        safe_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', detail_id)
        safe_index = re.sub(r'[^A-Za-z0-9_.-]+', '_', file_index)
        extension = os.path.splitext(candidate.file_name or '')[1].lower() or f'.{candidate.format or "srt"}'
        if extension not in TEXT_EXTENSIONS:
            extension = '.srt'
        return os.path.join(self.cache_dir, safe_id, 'members', f'{safe_index}{extension}')

    def _cache_member(
        self,
        detail_id: str,
        candidate: OnlineSubtitleCandidate,
        content: bytes,
        file_name: str,
    ) -> None:
        if len(content) > MAX_MEMBER_BYTES:
            return
        path = self._member_cache_path(detail_id, candidate)
        if not path or os.path.exists(path):
            return
        _atomic_write(path, content)

    def _extract_cached_archive_member(
        self,
        archive_path: str,
        candidate: OnlineSubtitleCandidate,
    ) -> tuple[bytes, str] | None:
        suffix = os.path.splitext(archive_path)[1].lower()
        if suffix == '.zip':
            return self._extract_zip_member(archive_path, candidate)
        if suffix == '.rar':
            return self._extract_rar_member(archive_path, candidate)
        return None

    def _extract_zip_member(
        self,
        archive_path: str,
        candidate: OnlineSubtitleCandidate,
    ) -> tuple[bytes, str] | None:
        wanted = os.path.basename(candidate.file_name or '')
        request = self._request_from_candidate(candidate)
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and os.path.splitext(item.filename)[1].lower() in TEXT_EXTENSIONS
                and item.file_size <= MAX_MEMBER_BYTES
            ]
            exact = [item for item in members if os.path.basename(item.filename) == wanted]
            matched = exact or [item for item in members if _file_matches_episode(item.filename, request)]
            if not matched:
                return None
            member = matched[0]
            with archive.open(member) as handle:
                content = handle.read(MAX_MEMBER_BYTES + 1)
            if len(content) > MAX_MEMBER_BYTES:
                return None
            return content, os.path.basename(member.filename)

    def _extract_rar_member(
        self,
        archive_path: str,
        candidate: OnlineSubtitleCandidate,
    ) -> tuple[bytes, str] | None:
        tar_command = shutil.which('tar') or shutil.which('tar.exe')
        if not tar_command:
            return None
        wanted = os.path.basename(candidate.file_name or '')
        list_proc = subprocess.run(
            [tar_command, '-tf', archive_path],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if list_proc.returncode != 0:
            return None
        request = self._request_from_candidate(candidate)
        names = [line.strip() for line in list_proc.stdout.splitlines() if line.strip()]
        text_members = [
            name
            for name in names
            if os.path.splitext(name)[1].lower() in TEXT_EXTENSIONS
        ]
        exact = [name for name in text_members if os.path.basename(name) == wanted]
        matched = exact or [name for name in text_members if _file_matches_episode(name, request)]
        if not matched:
            return None
        member = matched[0]
        extract_proc = subprocess.run(
            [tar_command, '-xOf', archive_path, member],
            capture_output=True,
            timeout=self.timeout,
        )
        if extract_proc.returncode == 0 and len(extract_proc.stdout) <= MAX_MEMBER_BYTES:
            return extract_proc.stdout, os.path.basename(member)
        return self._extract_rar_member_via_directory(tar_command, archive_path, candidate)

    def _extract_rar_member_via_directory(
        self,
        tar_command: str,
        archive_path: str,
        candidate: OnlineSubtitleCandidate,
    ) -> tuple[bytes, str] | None:
        wanted = os.path.basename(candidate.file_name or '')
        request = self._request_from_candidate(candidate)
        with tempfile.TemporaryDirectory(prefix='assrt-rar-') as directory:
            extract_proc = subprocess.run(
                [tar_command, '-xf', archive_path, '-C', directory],
                capture_output=True,
                timeout=self.timeout,
            )
            if extract_proc.returncode != 0:
                return None
            files: list[str] = []
            for root, _, names in os.walk(directory):
                for name in names:
                    path = os.path.join(root, name)
                    if os.path.splitext(name)[1].lower() in TEXT_EXTENSIONS:
                        files.append(path)
            exact = [path for path in files if os.path.basename(path) == wanted]
            matched = exact or [path for path in files if _file_matches_episode(os.path.basename(path), request)]
            if not matched:
                return None
            path = matched[0]
            if os.path.getsize(path) > MAX_MEMBER_BYTES:
                return None
            with open(path, 'rb') as handle:
                return handle.read(MAX_MEMBER_BYTES + 1), os.path.basename(path)

    def _request_from_candidate(self, candidate: OnlineSubtitleCandidate) -> SubtitleSearchRequest:
        return SubtitleSearchRequest(
            media_type=candidate.media_type or 'movie',
            tmdb_id=candidate.parent_tmdb_id or candidate.tmdb_id,
            title=candidate.title,
            year=None,
            season=candidate.season,
            episode=candidate.episode,
            languages=(candidate.language,),
        )

    def _select_download_url(
        self,
        detail: dict[str, Any],
        candidate: OnlineSubtitleCandidate,
    ) -> tuple[str, str]:
        filelist = detail.get('filelist') or []
        wanted_name = os.path.basename(candidate.file_name or '')
        wanted_index = str(candidate.metadata.get('assrt_file_index') or '')
        for item in filelist:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get('f') or '')
            item_index = str(item.get('id') or item.get('no') or item.get('file_index') or '')
            if item.get('url') and (item_index == wanted_index or file_name == wanted_name):
                return str(item['url']), file_name or wanted_name
        request = SubtitleSearchRequest(
            media_type=candidate.media_type or 'movie',
            tmdb_id=candidate.parent_tmdb_id or candidate.tmdb_id,
            title=candidate.title,
            year=None,
            season=candidate.season,
            episode=candidate.episode,
            languages=(candidate.language,),
        )
        for item in filelist:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get('f') or '')
            if item.get('url') and file_name and _file_matches_episode(file_name, request):
                return str(item['url']), file_name
        for item in filelist:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get('f') or '')
            if os.path.splitext(file_name)[1].lower() in TEXT_EXTENSIONS and item.get('url'):
                return str(item['url']), file_name
        url = str(detail.get('url') or '').strip()
        if not url:
            raise RuntimeError('ASSRT detail returned no download URL')
        return url, str(detail.get('filename') or candidate.file_name or 'subtitle.srt')

    def _api_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {'token': self.token}
        query.update(params)
        response = self.session.get(
            f'{self.base_url}/{path.lstrip("/")}',
            params=query,
            headers={'Accept': 'application/json', 'User-Agent': 'phantom_slayer v1.0'},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json() or {}
        if payload.get('status') not in (0, '0'):
            raise RuntimeError(str(payload.get('errmsg') or payload.get('error') or payload))
        return payload
