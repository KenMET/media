#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe cloud MCP subtitle providers with the same inputs as SubtitleAgent."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from media_mcp.adapters.dispatch import mcp_direct_call_ns
from media_mcp.subtitle.domain.online_subtitle import validate_online_subtitle


DEFAULT_PROVIDERS = ('opensubtitles', 'subdl', 'assrt', 'subtitlecat')
DEFAULT_LANGUAGES = ('zh-cn', 'zh-tw')


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, 'reconfigure', None)
    if callable(reconfigure):
        reconfigure(encoding='utf-8')


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        'provider',
        'candidate_id',
        'file_id',
        'file_name',
        'language',
        'subtitle_type',
        'format',
        'media_type',
        'tmdb_id',
        'parent_tmdb_id',
        'season',
        'episode',
        'title',
        'release',
        'download_count',
        'rating',
        'trusted',
        'machine_translated',
        'hearing_impaired',
        'foreign_parts_only',
    )
    return {key: candidate.get(key) for key in keys if candidate.get(key) not in (None, '')}


def _print_json(prefix: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(f'{prefix} {text}')


def _search_provider(args: argparse.Namespace, provider: str, language: str) -> list[dict[str, Any]]:
    result = mcp_direct_call_ns(
        'subtitle.search',
        provider=provider,
        query=args.query,
        language=language,
        media_type=args.media_type,
        tmdb_id=args.tmdb_id,
        year=args.year,
        season=args.season,
        episode=args.episode,
    )
    candidates = result.get('candidates') if isinstance(result, dict) else None
    return [item for item in candidates or [] if isinstance(item, dict)]


def _download_and_validate(provider: str, candidate: dict[str, Any]) -> dict[str, Any]:
    result = mcp_direct_call_ns(
        'subtitle.download',
        provider=provider,
        file_id=str(candidate.get('file_id')),
        candidate=candidate,
        file_name=candidate.get('file_name'),
        language=candidate.get('language'),
        subtitle_type=candidate.get('subtitle_type') or 'normal',
        fmt=candidate.get('format') or 'srt',
    )
    content = base64.b64decode(str(result.get('content_base64') or ''))
    file_name = str(result.get('file_name') or candidate.get('file_name') or 'subtitle.srt')
    validated = validate_online_subtitle(content, file_name)
    return {
        'file_name': file_name,
        'size_bytes': len(content),
        'extension': validated.extension,
        'encoding': validated.encoding,
        'profile': validated.profile,
    }


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(
        description='Probe subtitle.search/download through the configured MCP service.',
    )
    parser.add_argument('--query', required=True, help='Movie or TV title to search.')
    parser.add_argument('--media-type', choices=('movie', 'tv'), default='movie')
    parser.add_argument('--tmdb-id', type=int)
    parser.add_argument('--year', type=int)
    parser.add_argument('--season', type=int)
    parser.add_argument('--episode', type=int)
    parser.add_argument('--provider', action='append', choices=DEFAULT_PROVIDERS)
    parser.add_argument('--language', action='append', default=None)
    parser.add_argument('--download', action='store_true', help='Download and validate top candidates.')
    parser.add_argument('--limit', type=int, default=3, help='Candidates to print/download per provider-language.')
    parser.add_argument('--raw', action='store_true', help='Print full candidate payloads.')
    args = parser.parse_args()

    providers = tuple(args.provider or DEFAULT_PROVIDERS)
    languages = tuple(args.language or DEFAULT_LANGUAGES)
    args.limit = max(1, args.limit)

    _print_json(
        'REQUEST',
        {
            'query': args.query,
            'media_type': args.media_type,
            'tmdb_id': args.tmdb_id,
            'year': args.year,
            'season': args.season,
            'episode': args.episode,
            'providers': providers,
            'languages': languages,
            'download': args.download,
        },
    )

    total = 0
    for provider in providers:
        for language in languages:
            try:
                candidates = _search_provider(args, provider, language)
            except Exception as exc:
                _print_json(
                    'SEARCH_ERROR',
                    {'provider': provider, 'language': language, 'error': f'{type(exc).__name__}: {exc}'},
                )
                continue

            total += len(candidates)
            _print_json(
                'SEARCH_OK',
                {'provider': provider, 'language': language, 'count': len(candidates)},
            )
            for index, candidate in enumerate(candidates[: args.limit], start=1):
                view = candidate if args.raw else _compact_candidate(candidate)
                _print_json('CANDIDATE', {'index': index, **view})
                if not args.download:
                    continue
                try:
                    validation = _download_and_validate(provider, candidate)
                except Exception as exc:
                    _print_json(
                        'DOWNLOAD_ERROR',
                        {
                            'provider': provider,
                            'language': language,
                            'index': index,
                            'file_id': candidate.get('file_id'),
                            'error': f'{type(exc).__name__}: {exc}',
                        },
                    )
                    continue
                _print_json(
                    'DOWNLOAD_OK',
                    {
                        'provider': provider,
                        'language': language,
                        'index': index,
                        'file_id': candidate.get('file_id'),
                        **validation,
                    },
                )

    _print_json('SUMMARY', {'total_candidates': total})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
