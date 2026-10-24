#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tv_batch_processor.py
电视剧批量识别与季级缓存。
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import Dict, Iterable

from media_mcp.ingest.domain.classifier import ParsedMedia, build_tv_group_key, parse_media_filename, validate_result
from media_mcp.ingest.clients.codex import CodexMediaClient
from media_mcp.ingest.domain.path_builder import MEDIA_ROOT
from media_mcp.ingest.domain.canonical_path import enforce_canonical_hardlink_path, validate_canonical_hardlink_path
from media_mcp.ingest.domain.result_schema import normalize_result, validate_structured_result
from media_mcp.ingest.services.linking import apply_preferred_media

from media_mcp.storage.media import add_failed_case, get_canonical_media_title, upsert_media_link, get_tmdb_cache, upsert_tmdb_cache

MEDIA_DB = os.environ.get('MEDIA_DB_NAME') or 'media'
LOW_CONFIDENCE_THRESHOLD = 0.75
logger = logging.getLogger('MediaMonitor')


@dataclass
class BatchItem:
    file_path: str
    parsed: ParsedMedia


class TvBatchProcessor:
    def __init__(self, client: CodexMediaClient, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def process(self, file_paths: Iterable[str]) -> Dict[str, str]:
        file_paths = list(file_paths)
        logger.info('[TVBatch] start input_files=%d', len(file_paths))
        grouped: dict[tuple[str, int | None], list[BatchItem]] = defaultdict(list)
        for file_path in file_paths:
            parsed = parse_media_filename(file_path)
            if parsed.media_type != 'tv' or parsed.season is None or parsed.episode is None:
                logger.debug('[TVBatch] skip_non_batchable source=%s media_type=%s season=%s episode=%s', file_path, parsed.media_type, parsed.season, parsed.episode)
                continue
            group_key = build_tv_group_key(file_path, parsed)
            grouped[(group_key, parsed.year)].append(BatchItem(file_path=file_path, parsed=parsed))

        logger.info('[TVBatch] grouped_series=%d', len(grouped))
        results: Dict[str, str] = {}
        for series_items in grouped.values():
            season_groups: dict[int, list[BatchItem]] = defaultdict(list)
            for item in series_items:
                season_groups[int(item.parsed.season)].append(item)

            first_item = series_items[0]
            first = first_item.parsed
            series_guess = build_tv_group_key(first_item.file_path, first)
            series_payload = {
                'mode': 'tv_series_lookup',
                'series_guess': series_guess,
                'year': first.year,
                'season': first.season,
                'files': [
                    {
                        'source_path': item.parsed.source_path,
                        'filename': item.parsed.filename,
                        'episode': item.parsed.episode,
                    }
                    for item in series_items[:8]
                ],
            }
            logger.info('[TVBatch] series_lookup guess=%s year=%s files=%d', series_guess, first.year, len(series_items))
            series_result = self._lookup_series(series_payload)
            if not series_result.get('success'):
                logger.error('[TVBatch] series_lookup_failed payload=%s result=%s', json.dumps(series_payload, ensure_ascii=False), json.dumps(series_result, ensure_ascii=False))
                for item in series_items:
                    self._record_failed_case(item.file_path, item.parsed.to_prompt_payload(), series_result, 'tv_series_lookup')
                    results[item.file_path] = 'failed'
                continue

            canonical = get_canonical_media_title(MEDIA_DB, 'tv', series_result.get('tmdb_id'))
            title = dict(series_result.get('title') or {})
            if canonical and canonical.get('base_title'):
                title['base'] = canonical.get('base_title')
                if canonical.get('media_name') and not title.get('zh'):
                    title['zh'] = canonical.get('media_name')
                if canonical.get('alt_name'):
                    title['original'] = canonical.get('alt_name')
                series_result['title'] = title

            for season, season_items in season_groups.items():
                action_map = self._process_season(series_result, season, season_items)
                results.update(action_map)
        return results

    def _series_cache_key(self, payload: dict) -> str:
        files = payload.get('files') or []
        episodes = sorted(int(item.get('episode')) for item in files if item.get('episode') is not None)
        raw = json.dumps({
            'mode': payload.get('mode'),
            'series_guess': payload.get('series_guess'),
            'year': payload.get('year'),
            'season': payload.get('season'),
            'episodes': episodes,
        }, ensure_ascii=False, sort_keys=True)
        return sha1(raw.encode('utf-8')).hexdigest()

    def _episode_cache_key(self, tmdb_id: int | None, season: int, episodes: list[int]) -> str:
        raw = json.dumps({
            'mode': 'tv_episode_batch',
            'tmdb_id': tmdb_id,
            'season': season,
            'episodes': sorted(episodes),
        }, ensure_ascii=False, sort_keys=True)
        return sha1(raw.encode('utf-8')).hexdigest()

    def _lookup_series(self, payload: dict) -> dict:
        cache_key = self._series_cache_key(payload)
        if not self.dry_run:
            cached = get_tmdb_cache(MEDIA_DB, 'tv_series_lookup', cache_key)
            if cached and isinstance(cached.get('response'), dict):
                return cached['response']
        result = self.client.classify_tv_series_lookup(payload, user='phantom_slayer_tv_series_lookup')
        if result.get('success') and not self.dry_run:
            upsert_tmdb_cache(
                MEDIA_DB,
                'tv_series_lookup',
                cache_key,
                result,
                payload,
                media_type='tv',
                tmdb_id=result.get('tmdb_id'),
                season=result.get('season') or payload.get('season'),
                query=payload.get('series_guess'),
                year=result.get('year') or payload.get('year'),
                language=result.get('original_language'),
                region=result.get('origin_country'),
            )
        return result

    def _lookup_episode_batch(self, payload: dict) -> dict:
        cache_key = self._episode_cache_key(payload.get('tmdb_id'), int(payload.get('season')), [int(ep) for ep in payload.get('episodes') or []])
        if not self.dry_run:
            cached = get_tmdb_cache(MEDIA_DB, 'tv_episode_batch', cache_key)
            if cached and isinstance(cached.get('response'), dict):
                return cached['response']
        result = self.client.classify_tv_episode_batch(payload, user='phantom_slayer_tv_episode_batch')
        if result.get('success') and not self.dry_run:
            upsert_tmdb_cache(
                MEDIA_DB,
                'tv_episode_batch',
                cache_key,
                result,
                payload,
                media_type='tv',
                tmdb_id=payload.get('tmdb_id'),
                season=payload.get('season'),
                query=(payload.get('title') or {}).get('base') if isinstance(payload.get('title'), dict) else None,
            )
        return result

    def _process_season(self, series_result: dict, season: int, season_items: list[BatchItem]) -> Dict[str, str]:
        episodes = sorted({int(item.parsed.episode) for item in season_items if item.parsed.episode is not None})
        logger.info('[TVBatch][season] tmdb_id=%s season=%s files=%d episodes=%s', series_result.get('tmdb_id'), season, len(season_items), episodes)
        payload = {
            'mode': 'tv_episode_batch',
            'tmdb_id': series_result.get('tmdb_id'),
            'season': season,
            'title': series_result.get('title'),
            'episodes': episodes,
        }
        batch_result = self._lookup_episode_batch(payload)
        if not batch_result.get('success'):
            logger.error('[TVBatch][season] batch_failed season=%s payload=%s result=%s', season, json.dumps(payload, ensure_ascii=False), json.dumps(batch_result, ensure_ascii=False))
            logger.warning('[TVBatch][season] fallback_without_episode_titles season=%s files=%d', season, len(season_items))
            action_map: Dict[str, str] = {}
            for item in season_items:
                action_map[item.file_path] = self._finalize_episode(item, series_result, {'episode': item.parsed.episode, 'episode_title': None}, fallback_reason='tv_episode_batch_failed')
            return action_map

        episode_map = {int(entry.get('episode')): entry for entry in batch_result.get('episodes') or [] if entry.get('episode') is not None}
        action_map: Dict[str, str] = {}
        for item in season_items:
            episode_entry = episode_map.get(int(item.parsed.episode))
            if not episode_entry:
                logger.warning('[TVBatch][season] missing_episode_mapping source=%s season=%s episode=%s', item.file_path, season, item.parsed.episode)
                self._record_failed_case(item.file_path, item.parsed.to_prompt_payload(), {'success': False, 'error': f'missing episode mapping for E{item.parsed.episode}'}, 'tv_episode_batch')
                action_map[item.file_path] = 'failed'
                continue
            action_map[item.file_path] = self._finalize_episode(item, series_result, episode_entry)
        return action_map

    def _finalize_episode(self, item: BatchItem, series_result: dict, episode_entry: dict, fallback_reason: str | None = None) -> str:
        if not os.path.isfile(item.file_path):
            return 'failed'
        parsed_payload = item.parsed.to_prompt_payload()
        raw_result = {
            'success': True,
            'kind': 'tv',
            'source_path': item.file_path,
            'tmdb_id': series_result.get('tmdb_id'),
            'title': series_result.get('title'),
            'original_language': series_result.get('original_language'),
            'origin_country': series_result.get('origin_country'),
            'year': series_result.get('year', item.parsed.year),
            'season': item.parsed.season,
            'episode': item.parsed.episode,
            'episode_title': episode_entry.get('episode_title'),
            'confidence': min(
                float(series_result.get('confidence') or 0.95),
                float(episode_entry.get('confidence') or 0.95) if isinstance(episode_entry, dict) else 0.95,
            ),
        }
        if not raw_result.get('confidence'):
            raw_result['confidence'] = float(series_result.get('confidence') or 0.95)

        normalized = normalize_result(raw_result, parsed_payload)
        title = normalized.get('title') or {}
        canonical = get_canonical_media_title(MEDIA_DB, 'tv', normalized.get('tmdb_id'))
        if canonical and canonical.get('base_title'):
            title['base'] = canonical.get('base_title')
            if canonical.get('media_name') and not title.get('zh'):
                title['zh'] = canonical.get('media_name')
            if canonical.get('alt_name'):
                title['original'] = canonical.get('alt_name')
            normalized['title'] = title
        normalized['base_title'] = title.get('base')
        normalized['media_name'] = title.get('zh') or title.get('base')
        normalized['alt_name'] = title.get('original')
        normalized['source_path'] = item.file_path
        normalized['media_type'] = 'tv'
        normalized = enforce_canonical_hardlink_path(normalized, item.parsed.extension, MEDIA_ROOT)

        ok, reason = validate_structured_result(normalized)
        if not ok:
            self._record_failed_case(item.file_path, parsed_payload, normalized, f'tv_batch_validate:{reason}')
            return 'failed'

        path_ok, path_reason = validate_result(normalized)
        if not path_ok:
            self._record_failed_case(item.file_path, parsed_payload, normalized, f'tv_batch_path:{path_reason}')
            return 'failed'

        canonical_ok, canonical_reason, canonical_path = validate_canonical_hardlink_path(normalized, normalized.get('hardlink_path'), parsed_payload.get('extension'), MEDIA_ROOT)
        if not canonical_ok:
            if canonical_reason == 'hardlink_path is not canonical':
                normalized['hardlink_path'] = canonical_path
            else:
                self._record_failed_case(item.file_path, parsed_payload, normalized, f'tv_batch_canonical:{canonical_reason}')
                return 'failed'

        confidence = float(normalized.get('confidence') or 0.0)
        if fallback_reason:
            logger.warning('[TVBatch][finalize] source=%s fallback=%s target=%s confidence=%.3f', item.file_path, fallback_reason, normalized.get('hardlink_path'), confidence)
        else:
            logger.info('[TVBatch][finalize] source=%s target=%s confidence=%.3f', item.file_path, normalized.get('hardlink_path'), confidence)
        metadata = {
            'media_type': 'tv',
            'media_tmdb_id': normalized.get('tmdb_id'),
            'season_tmdb_id': None,
            'episode_tmdb_id': None,
            'title_guess': parsed_payload.get('title_guess'),
            'media_name': normalized.get('media_name'),
            'base_title': normalized.get('base_title'),
            'alt_name': normalized.get('alt_name'),
            'original_language': normalized.get('original_language'),
            'origin_country': normalized.get('origin_country'),
            'year': normalized.get('year', parsed_payload.get('year')),
            'season': normalized.get('season', parsed_payload.get('season')),
            'episode': normalized.get('episode', parsed_payload.get('episode')),
            'extension': parsed_payload.get('extension'),
            'confidence': confidence,
            'agent_payload_json': json.dumps(parsed_payload, ensure_ascii=False),
            'agent_result_json': json.dumps(
                {
                    'series_result': series_result,
                    'episode_entry': episode_entry,
                    'normalized_result': normalized,
                },
                ensure_ascii=False,
            ),
        }

        if confidence < LOW_CONFIDENCE_THRESHOLD:
            logger.warning('[TVBatch][finalize] source=%s stage=low_confidence confidence=%s threshold=%s', item.file_path, confidence, LOW_CONFIDENCE_THRESHOLD)
            if not self.dry_run:
                upsert_media_link(
                    MEDIA_DB,
                    normalized['source_path'],
                    normalized['hardlink_path'],
                    **metadata,
                    status='needs_review',
                    reason=f'low confidence: {confidence}',
                )
            self._record_failed_case(item.file_path, parsed_payload, normalized, 'low_confidence')
            return 'failed'

        if self.dry_run:
            logger.info('[TVBatch][dry-run] source=%s target=%s', item.file_path, normalized['hardlink_path'])
            return 'preview'

        flag, msg, actual_hardlink_path = apply_preferred_media(normalized['source_path'], normalized['hardlink_path'], metadata, MEDIA_DB)
        if not flag:
            logger.error('[TVBatch][finalize] source=%s stage=create_hardlink reason=%s', item.file_path, msg)
            self._record_failed_case(item.file_path, parsed_payload, normalized, f'create_hardlink:{msg}')
            return 'failed'

        if actual_hardlink_path and actual_hardlink_path != normalized['hardlink_path']:
            normalized['hardlink_path'] = actual_hardlink_path
            metadata['agent_result_json'] = json.dumps(
                {
                    'series_result': series_result,
                    'episode_entry': episode_entry,
                    'normalized_result': normalized,
                },
                ensure_ascii=False,
            )

        if msg == 'Unlinked lower or uncertain quality':
            return 'unlinked'

        if msg == 'Skip hardlink':
            logger.info('[MediaMap] %s ---> %s (exists)', item.file_path, normalized['hardlink_path'])
            return 'exists'
        if msg == 'Overwrite hardlink':
            logger.info('[MediaMap] %s ---> %s (relinked)', item.file_path, normalized['hardlink_path'])
            return 'relinked'
        logger.info('[MediaMap] %s ---> %s (created)', item.file_path, normalized['hardlink_path'])
        return 'created'

    def _record_failed_case(self, file_path: str, parsed_payload: dict, result: dict, fail_stage: str):
        if self.dry_run:
            return
        add_failed_case(
            MEDIA_DB,
            file_path,
            os.path.basename(file_path),
            parsed_json=json.dumps(parsed_payload, ensure_ascii=False),
            result_json=json.dumps(result, ensure_ascii=False) if result is not None else None,
            fail_stage=fail_stage,
            reason=result.get('error') if isinstance(result, dict) else fail_stage,
        )
