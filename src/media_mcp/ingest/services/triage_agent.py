#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media_agent.py
Codex 驱动的媒体分类版本，本地负责最终路径生成、校验、硬链接与落库。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Tuple

from media_mcp.ingest.domain.classifier import parse_media_filename, validate_result, should_allow_non_tmdb_fallback
from media_mcp.ingest.domain.naming import should_upgrade_canonical_title
from media_mcp.ingest.clients.codex import CodexMediaClient
from media_mcp.ingest.domain.path_builder import MEDIA_ROOT
from media_mcp.ingest.domain.canonical_path import enforce_canonical_hardlink_path, validate_canonical_hardlink_path
from media_mcp.ingest.domain.result_schema import normalize_result, validate_structured_result
from media_mcp.ingest.services.linking import apply_preferred_media

from media_mcp.storage.media import upsert_media_link, add_failed_case, get_canonical_media_title

MEDIA_DB = os.environ.get('MEDIA_DB_NAME') or 'media'
LOW_CONFIDENCE_THRESHOLD = 0.75
logger = logging.getLogger('MediaMonitor')
BATCH_SIZE = int(os.environ.get('MEDIA_INGEST_AI_BATCH_SIZE', '12'))


class CodexMediaTriageAgent:
    def _build_non_tmdb_fallback(self, file_path: str, parsed_payload: Dict, response: Dict | None, reason: str) -> Dict:
        title_guess = (parsed_payload.get('title_guess') or os.path.splitext(os.path.basename(file_path))[0]).strip()
        fallback_title = {
            'zh': title_guess,
            'original': None,
            'base': title_guess,
        }
        fallback = {
            'success': True,
            'kind': parsed_payload.get('media_type') or 'movie',
            'source_path': file_path,
            'title': fallback_title,
            'year': parsed_payload.get('year'),
            'confidence': 0.55,
            'fallback_source': 'non_tmdb_filename',
            'fallback_reason': reason,
        }
        logger.warning('[MediaTriage][fallback] source=%s reason=%s title=%s', file_path, reason, title_guess)
        return fallback

    def __init__(self, client: CodexMediaClient | None = None):
        self.client = client or CodexMediaClient()

    def _finalize_title(self, result: Dict) -> Dict:
        canonical_kind = 'tv' if result.get('kind') == 'tv_extra' else result.get('kind')
        canonical = get_canonical_media_title(MEDIA_DB, canonical_kind, result.get('tmdb_id'))
        title = result.get('title') or {}
        if canonical and canonical.get('base_title') and not should_upgrade_canonical_title(canonical.get('media_name'), title.get('zh')):
            title['base'] = canonical.get('base_title')
            if canonical.get('media_name') and not title.get('zh'):
                title['zh'] = canonical.get('media_name')
            if canonical.get('alt_name'):
                title['original'] = canonical.get('alt_name')
            result['title'] = title
        result['base_title'] = title.get('base')
        result['media_name'] = title.get('zh') or title.get('base')
        result['alt_name'] = title.get('original')
        return result

    def infer(self, file_path: str) -> tuple[Dict | None, Dict]:
        parsed = parse_media_filename(file_path)
        parsed_payload = parsed.to_prompt_payload()
        logger.debug('[MediaTriage][infer] source=%s parsed=%s', file_path, json.dumps(parsed_payload, ensure_ascii=False))
        try:
            result = self.client.classify(parsed_payload, user='phantom_slayer_media')
        except Exception as exc:
            logger.error('[MediaTriage][single] request_failed source=%s error=%s', file_path, exc)
            return {
                'success': False,
                'source_path': file_path,
                'error': f'codex_request_failed: {exc}',
            }, parsed_payload

        normalized = normalize_result(result, parsed_payload)
        if (not normalized.get('success')) and should_allow_non_tmdb_fallback(parsed):
            fallback_reason = normalized.get('error') or normalized.get('error_code') or 'non_tmdb_fallback'
            normalized = self._build_non_tmdb_fallback(file_path, parsed_payload, normalized, fallback_reason)
        normalized['_agent_raw_result'] = result
        normalized = self._finalize_title(normalized)
        normalized['source_path'] = file_path
        normalized = enforce_canonical_hardlink_path(normalized, parsed.extension, MEDIA_ROOT)
        logger.debug('[MediaTriage][infer] source=%s normalized=%s', file_path, json.dumps(normalized, ensure_ascii=False))
        return normalized, parsed_payload

    def _finalize_response(self, file_path: str, response: Dict | None, parsed: Dict, dry_run: bool = False) -> Tuple[bool, str]:
        if not os.path.isfile(file_path):
            return False, 'source_missing'
        ok, reason = validate_structured_result(response)
        if not ok:
            logger.warning('[MediaTriage][run] source=%s stage=validate_structured_result reason=%s', file_path, reason)
            if not dry_run:
                add_failed_case(
                    MEDIA_DB,
                    file_path,
                    os.path.basename(file_path),
                    parsed_json=json.dumps(parsed, ensure_ascii=False),
                    result_json=json.dumps(response, ensure_ascii=False) if response else None,
                    fail_stage='codex_validate_result',
                    reason=reason,
                )
            return False, 'needs_review'

        path_ok, path_reason = validate_result(response)
        if not path_ok:
            logger.warning('[MediaTriage][run] source=%s stage=validate_result reason=%s', file_path, path_reason)
            if not dry_run:
                add_failed_case(
                    MEDIA_DB,
                    file_path,
                    os.path.basename(file_path),
                    parsed_json=json.dumps(parsed, ensure_ascii=False),
                    result_json=json.dumps(response, ensure_ascii=False),
                    fail_stage='validate_result',
                    reason=path_reason,
                )
            return False, 'needs_review'

        canonical_ok, canonical_reason, canonical_path = validate_canonical_hardlink_path(response, response.get('hardlink_path'), parsed.get('extension'), MEDIA_ROOT)
        if not canonical_ok:
            if canonical_reason == 'hardlink_path is not canonical':
                response['hardlink_path'] = canonical_path
            else:
                logger.warning('[MediaTriage][run] source=%s stage=validate_canonical_path reason=%s', file_path, canonical_reason)
                if not dry_run:
                    add_failed_case(
                        MEDIA_DB,
                        file_path,
                        os.path.basename(file_path),
                        parsed_json=json.dumps(parsed, ensure_ascii=False),
                        result_json=json.dumps(response, ensure_ascii=False),
                        fail_stage='validate_canonical_path',
                        reason=canonical_reason,
                    )
                return False, 'needs_review'

        confidence = float(response.get('confidence') or 0.0)
        metadata = {
            'media_type': response.get('kind'),
            'media_tmdb_id': response.get('tmdb_id'),
            'season_tmdb_id': None,
            'episode_tmdb_id': None,
            'title_guess': parsed.get('title_guess'),
            'media_name': response.get('media_name'),
            'base_title': response.get('base_title'),
            'alt_name': response.get('alt_name'),
            'original_language': response.get('original_language'),
            'origin_country': response.get('origin_country'),
            'year': response.get('year', parsed.get('year')),
            'season': response.get('season', parsed.get('season')),
            'episode': response.get('episode', parsed.get('episode')),
            'extra_type': response.get('extra_type', parsed.get('extra_type')),
            'extra_index': response.get('extra_index', parsed.get('extra_index')),
            'extension': parsed.get('extension'),
            'confidence': confidence,
            'agent_payload_json': json.dumps(parsed, ensure_ascii=False),
            'agent_result_json': json.dumps(
                {
                    'raw_result': response.get('_agent_raw_result'),
                    'normalized_result': response,
                },
                ensure_ascii=False,
            ),
        }

        if confidence < LOW_CONFIDENCE_THRESHOLD:
            logger.warning('[MediaTriage][run] source=%s stage=low_confidence confidence=%s threshold=%s', file_path, confidence, LOW_CONFIDENCE_THRESHOLD)
            if not dry_run:
                upsert_media_link(
                    MEDIA_DB,
                    response['source_path'],
                    response['hardlink_path'],
                    **metadata,
                    status='needs_review',
                    reason=f'low confidence: {confidence}',
                )
                add_failed_case(
                    MEDIA_DB,
                    file_path,
                    os.path.basename(file_path),
                    parsed_json=json.dumps(parsed, ensure_ascii=False),
                    result_json=json.dumps(response, ensure_ascii=False),
                    fail_stage='low_confidence',
                    reason=f'low confidence: {confidence}',
                )
            return False, 'needs_review'

        logger.info('[MediaTriage][run] source=%s hardlink_target=%s confidence=%.3f', file_path, response['hardlink_path'], confidence)
        if dry_run:
            logger.info('[MediaTriage][dry-run] source=%s target=%s', file_path, response['hardlink_path'])
            return True, 'preview'

        flag, msg, actual_hardlink_path = apply_preferred_media(response['source_path'], response['hardlink_path'], metadata, MEDIA_DB)
        if not flag:
            logger.error('[MediaTriage][run] source=%s stage=create_hardlink reason=%s', file_path, msg)
            if not dry_run:
                add_failed_case(
                    MEDIA_DB,
                    file_path,
                    os.path.basename(file_path),
                    parsed_json=json.dumps(parsed, ensure_ascii=False),
                    result_json=json.dumps(response, ensure_ascii=False),
                    fail_stage='create_hardlink',
                    reason=msg,
                )
            return False, 'failed'

        if actual_hardlink_path and actual_hardlink_path != response['hardlink_path']:
            response['hardlink_path'] = actual_hardlink_path
            metadata['agent_result_json'] = json.dumps(
                {
                    'raw_result': response.get('_agent_raw_result'),
                    'normalized_result': response,
                },
                ensure_ascii=False,
            )

        if msg == 'Unlinked lower or uncertain quality':
            return True, 'unlinked'

        if msg == 'Skip hardlink':
            logger.info('[MediaMap] %s ---> %s (exists)', file_path, response['hardlink_path'])
            return True, 'exists'
        if msg == 'Overwrite hardlink':
            logger.info('[MediaMap] %s ---> %s (relinked)', file_path, response['hardlink_path'])
            return True, 'relinked'
        logger.info('[MediaMap] %s ---> %s (created)', file_path, response['hardlink_path'])
        return True, 'created'

    def run(self, file_path: str, dry_run: bool = False) -> Tuple[bool, str]:
        logger.info('[MediaTriage][run] source=%s start', file_path)
        response, parsed = self.infer(file_path)
        return self._finalize_response(file_path, response, parsed, dry_run=dry_run)

    def infer_batch(self, file_paths: list[str]) -> tuple[Dict, dict[str, Dict]]:
        parsed_by_path: dict[str, Dict] = {}
        files = []
        for file_path in file_paths:
            parsed = parse_media_filename(file_path)
            payload = parsed.to_prompt_payload()
            parsed_by_path[file_path] = payload
            files.append(payload)
        batch_payload = {
            'mode': 'media_batch',
            'batch_size': len(files),
            'files': files,
        }
        logger.debug('[MediaTriage][batch] request files=%d', len(files))
        result = self.client.classify_batch(batch_payload, user='phantom_slayer_media_batch')
        return result, parsed_by_path

    def run_batch(self, file_paths: list[str], dry_run: bool = False) -> Dict[str, str]:
        logger.info('[MediaTriage][batch] start files=%d', len(file_paths))
        try:
            batch_result, parsed_by_path = self.infer_batch(file_paths)
        except Exception as exc:
            logger.warning('[MediaTriage][batch] request_failed files=%d error=%s', len(file_paths), exc)
            return {}
        if not isinstance(batch_result, dict) or not batch_result.get('success'):
            logger.warning('[MediaTriage][batch] failed result=%s', json.dumps(batch_result, ensure_ascii=False) if isinstance(batch_result, dict) else batch_result)
            return {}
        rows = batch_result.get('results')
        if not isinstance(rows, list):
            logger.warning('[MediaTriage][batch] invalid result: missing results list')
            return {}

        results_by_path: dict[str, Dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_path = row.get('source_path')
            if source_path in parsed_by_path:
                results_by_path[source_path] = row

        actions: Dict[str, str] = {}
        for file_path in file_paths:
            parsed = parsed_by_path[file_path]
            row = results_by_path.get(file_path)
            if row is None:
                logger.warning('[MediaTriage][batch] missing result source=%s', file_path)
                continue
            normalized = normalize_result(row, parsed)
            if (not normalized.get('success')) and should_allow_non_tmdb_fallback(parse_media_filename(file_path)):
                fallback_reason = normalized.get('error') or normalized.get('error_code') or 'non_tmdb_fallback'
                normalized = self._build_non_tmdb_fallback(file_path, parsed, normalized, fallback_reason)
            normalized['_agent_raw_result'] = row
            normalized = self._finalize_title(normalized)
            normalized['source_path'] = file_path
            normalized = enforce_canonical_hardlink_path(normalized, parsed.get('extension'), MEDIA_ROOT)
            logger.debug('[MediaTriage][batch] source=%s normalized=%s', file_path, json.dumps(normalized, ensure_ascii=False))
            flag, action = self._finalize_response(file_path, normalized, parsed, dry_run=dry_run)
            actions[file_path] = action if flag else 'failed'
        logger.info('[MediaTriage][batch] done files=%d handled=%d', len(file_paths), len(actions))
        return actions
