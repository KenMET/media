#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py
Media ingestion entrypoint for selected paths, full scans, rebuilds and cleanup.

Use media_mcp.monitor.qbittorrent to monitor qBittorrent download completion events.
"""

import os
import sys
import time
import argparse
import logging
import json
from multiprocessing import Queue

if __package__ in {None, ''}:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

py_dir = os.path.dirname(os.path.realpath(__file__))
from media_mcp import logging_utils as log
from media_mcp.ingest.domain.file_utils import get_main_media, create_hardlink_with_target, same_recorded_source
from media_mcp.ingest.services.triage_agent import BATCH_SIZE, CodexMediaTriageAgent
from media_mcp.ingest.services.tv_batch_service import TvBatchProcessor
from media_mcp.ingest.domain.canonical_path import validate_canonical_hardlink_path
from media_mcp.ingest.domain.classifier import parse_media_filename, build_tv_group_key
from media_mcp.ingest.domain.path_builder import MEDIA_ROOT
from media_mcp.storage.media import (
    delete_media_links_by_keyword,
    delete_media_links_by_ids,
    list_media_links_by_keyword,
    list_failed_cases,
    get_media_link_by_source,
    upsert_media_link,
)
from media_mcp.adapters.dispatch import mcp_direct_call_ns
from media_mcp.subtitle.domain.notify_summary import subtitle_notify_parts

log_name = 'MediaMonitor'
SIZE_RATIO = 10
MEDIA_DB = os.environ.get('MEDIA_DB_NAME') or 'media'
FULL_SCAN_ROOT = '/data/downloads'

g_logger = None


def logger():
    global g_logger
    return g_logger


def set_logger(logger_obj):
    global g_logger
    g_logger = logger_obj


def _json_object(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _link_record_agent_field(link_record: dict, field: str):
    payload = _json_object(link_record.get('agent_result_json'))
    for container in (
        payload,
        payload.get('normalized_result'),
        payload.get('episode_entry'),
        payload.get('series_result'),
        payload.get('raw_result'),
    ):
        if isinstance(container, dict) and container.get(field) is not None:
            return container.get(field)
    return None


def _link_record_episode_title(link_record: dict):
    value = _link_record_agent_field(link_record, 'episode_title')
    if isinstance(value, dict):
        if value.get('base') or value.get('zh') or value.get('original'):
            return value
        return None
    if isinstance(value, str) and value.strip():
        return {'base': value.strip()}
    return None


def _upsert_restored_media_link(file_path: str, target_path: str, link_record: dict, reason: str):
    upsert_media_link(
        MEDIA_DB,
        file_path,
        target_path,
        media_type=link_record.get('media_type'),
        media_tmdb_id=link_record.get('media_tmdb_id'),
        season_tmdb_id=link_record.get('season_tmdb_id'),
        episode_tmdb_id=link_record.get('episode_tmdb_id'),
        title_guess=link_record.get('title_guess'),
        media_name=link_record.get('media_name'),
        base_title=link_record.get('base_title'),
        alt_name=link_record.get('alt_name'),
        original_language=link_record.get('original_language'),
        origin_country=link_record.get('origin_country'),
        year=link_record.get('year'),
        season=link_record.get('season'),
        episode=link_record.get('episode'),
        extra_type=link_record.get('extra_type'),
        extra_index=link_record.get('extra_index'),
        extension=link_record.get('extension'),
        confidence=link_record.get('confidence'),
        agent_payload_json=link_record.get('agent_payload_json'),
        agent_result_json=link_record.get('agent_result_json'),
        status='linked',
        reason=reason,
    )


def _remove_stale_duplicate_target(old_target: str | None, canonical_target: str):
    if not old_target:
        return
    old_path = os.path.normpath(str(old_target))
    new_path = os.path.normpath(str(canonical_target))
    if old_path == new_path:
        return
    media_root = os.path.normpath(MEDIA_ROOT)
    try:
        if os.path.commonpath((old_path, media_root)) != media_root:
            return
        if os.path.commonpath((new_path, media_root)) != media_root:
            return
    except ValueError:
        return
    if not os.path.isfile(old_path) or not os.path.isfile(new_path):
        return
    try:
        if not os.path.samefile(old_path, new_path):
            return
        os.remove(old_path)
        logger().info('[RestoreFix] removed stale duplicate target: %s', old_path)
        _safe_remove_empty_parent_dirs(old_path, MEDIA_ROOT)
    except OSError as exc:
        logger().warning('[RestoreFix] failed to remove stale duplicate target %s (%s)', old_path, exc)


def _requires_human_review(record: dict) -> bool:
    return record.get('status')=='needs_review' and not str(record.get('reason') or '').lower().startswith('codex_request_failed:')


def restore_link_from_db(file_path: str, dry_run: bool = False, recheck_unlinked: bool = False, recheck_review: bool = True) -> tuple[bool, str]:
    logger().debug('[RestoreCheck] source=%s', file_path)
    if dry_run:
        logger().debug('[RestoreCheck][dry-run] bypass existing mappings and run full triage: %s', file_path)
        return False, 'not_found'

    link_record = get_media_link_by_source(MEDIA_DB, file_path)
    if not link_record:
        logger().debug('[RestoreCheck] no media_link record for source=%s', file_path)
        return False, 'not_found'
    if link_record.get('status') == 'deleted':
        return (True,'unlinked') if same_recorded_source(link_record,file_path) else (False,'not_found')
    if link_record.get('status') == 'unlinked':
        unchanged = same_recorded_source(link_record,file_path)
        if unchanged and not recheck_unlinked:
            return True, 'unlinked'
        return False, 'not_found'
    if _requires_human_review(link_record) and not recheck_review and same_recorded_source(link_record,file_path):
        return True, 'needs_review'
    if link_record.get('status') in {'failed', 'needs_review'}:
        logger().debug('[RestoreCheck] media_link status requires triage source=%s status=%s', file_path, link_record.get('status'))
        return False, 'not_found'

    target_path = link_record.get('target_path')
    if not target_path:
        logger().warning('[RestoreCheck] media_link record missing target_path for source=%s', file_path)
        return False, 'not_found'

    validation_result = {
        'kind': link_record.get('media_type'),
        'title': {
            'zh': link_record.get('media_name'),
            'original': link_record.get('alt_name'),
            'base': link_record.get('base_title'),
        },
        'year': link_record.get('year'),
        'season': link_record.get('season'),
        'episode': link_record.get('episode'),
        'episode_title': _link_record_episode_title(link_record) if link_record.get('media_type') == 'tv' else None,
        'extra_type': link_record.get('extra_type'),
        'extra_index': link_record.get('extra_index'),
    }
    canonical_ok, canonical_reason, canonical_path = validate_canonical_hardlink_path(
        validation_result,
        target_path,
        link_record.get('extension') or os.path.splitext(target_path)[1],
    )
    if not canonical_ok and canonical_reason != 'hardlink_path is not canonical':
        logger().warning(f'Skip non-canonical media link restore<{target_path}>: {canonical_reason}')
        return False, 'not_found'
    target_path = canonical_path

    from media_mcp.ingest.services.linking import apply_preferred_media
    fields = ('media_type','media_tmdb_id','season_tmdb_id','episode_tmdb_id','title_guess','media_name',
              'base_title','alt_name','original_language','origin_country','year','season','episode',
              'extra_type','extra_index','extension','confidence','agent_payload_json','agent_result_json')
    metadata = {key:link_record.get(key) for key in fields}
    flag, message, actual = apply_preferred_media(file_path,target_path,metadata,MEDIA_DB)
    if not flag:
        logger().warning('Mapped media restore requires review: %s', message)
        return False, 'not_found'
    if message == 'Unlinked lower or uncertain quality':
        return True, 'unlinked'
    return True, 'exists' if message == 'Skip hardlink' else 'relinked'


def _format_subtitle_notify_summary(subtitle_summary: dict | None) -> str | None:
    if not subtitle_summary:
        return None

    action_counts = subtitle_summary.get('detailed_action_counts') or subtitle_summary.get('action_counts') or {}
    parts = subtitle_notify_parts(action_counts, ignored_noop_actions={'exists'})

    if False and not parts and int(subtitle_summary.get('media_count') or 0) <= 0:
        return 'Subtitles: no matching media'
    if not parts:
        return None
    return 'Subtitles: ' + ', '.join(parts)


def _run_subtitle_for_batch(folder_path: str, test_mode: bool = False, dry_run: bool = False) -> dict | None:
    logger().info('[SubtitleBatch] start path=%s mode=%s', folder_path, 'dry-run' if test_mode or dry_run else 'apply')
    started_at = time.time()
    try:
        from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent

        _attach_child_logger('SubtitleAgent')
        agent = SubtitleAgent()
        summary = agent.run_path_summary(
            folder_path,
            test_mode=test_mode or dry_run,
            send_notify=False,
        )
        logger().info(
            '[SubtitleBatch] done path=%s media=%s sidecars=%s handled=%s missing=%s review=%s failed=%s elapsed=%.2fs',
            folder_path,
            summary.get('media_count'),
            summary.get('sidecar_count'),
            summary.get('handled'),
            summary.get('missing'),
            summary.get('review'),
            summary.get('failed'),
            time.time() - started_at,
        )
        return summary
    except Exception as exc:
        logger().exception('[SubtitleBatch] failed path=%s error=%s', folder_path, exc)
        return {'action_counts': {'failed': 1}, 'failed': 1}


def _attach_child_logger(child_name: str):
    parent = logger()
    child = logging.getLogger(child_name)
    child.handlers = list(parent.handlers)
    child.setLevel(parent.level)
    child.propagate = False


def send_batch_notify(
    folder_path: str,
    created: int,
    relinked: int,
    failed: int,
    test_mode: bool = False,
    summary: dict | None = None,
    subtitle_summary: dict | None = None,
):
    if test_mode:
        return
    subtitle_text = _format_subtitle_notify_summary(subtitle_summary)
    if created <= 0 and relinked <= 0 and failed <= 0 and not subtitle_text:
        return

    summary = summary or {}
    media_kind = summary.get('media_kind')
    display_name = (
        summary.get('display_name')
        or (os.path.basename(folder_path.rstrip('/')) if folder_path else 'media')
    )
    success_count = created + relinked
    content = None
    if created <= 0 and relinked <= 0 and failed <= 0:
        if media_kind == 'movie':
            content = f'Movie {display_name}\n{subtitle_text}'
        elif media_kind == 'tv':
            content = f'Series {display_name}\n{subtitle_text}'
        else:
            content = f'{display_name}\n{subtitle_text}'
        flag_notify = mcp_direct_call_ns('notify.send_notification', title='Media ingestion notification', content=content)
        if not flag_notify:
            raise RuntimeError(f'MCP notification failed for: {folder_path}, {content}')
        return

    if os.path.isfile(folder_path):
        if created > 0:
            content = f'Ingestion completed: {display_name}'
        elif relinked > 0:
            content = f'Recovery completed: {display_name}'
        else:
            content = f'Ingestion failed (1 item; review required): {display_name}'
    elif media_kind == 'movie' and display_name:
        if success_count > 0:
            content = f'Movie {display_name}: ingestion completed'
            if failed > 0:
                content += f'; {failed} additional items failed'
        else:
            content = f'Movie {display_name}: ingestion failed ({failed} items; review required)'
    elif media_kind == 'tv' and display_name:
        if success_count > 0:
            content = f'Series {display_name}: ingestion completed ({success_count} episodes)'
            if failed > 0:
                content += f'; {failed} additional episodes failed'
        else:
            content = f'Series {display_name}: ingestion failed ({failed} episodes; review required)'
    else:
        parts = []
        if created > 0:
            parts.append(f'created {created}')
        if relinked > 0:
            parts.append(f'relinked {relinked}')
        if failed > 0:
            parts.append(f'failed {failed} (review required)')
        content = f'Batch ingestion [{display_name}]: ' + ', '.join(parts)
    if subtitle_text:
        content = f'{content}\n{subtitle_text}'
    flag_notify = mcp_direct_call_ns('notify.send_notification', title='Media ingestion notification', content=content)
    if not flag_notify:
        raise RuntimeError(f'MCP notification failed for: {folder_path}, {content}')


def _media_link_display_name(link: dict, *, single_file: bool = False) -> str | None:
    media_type = link.get('media_type')
    target_path = link.get('target_path')
    if single_file and target_path:
        return os.path.splitext(os.path.basename(str(target_path)))[0]
    if media_type == 'tv':
        return (
            link.get('base_title')
            or link.get('media_name')
            or (os.path.splitext(os.path.basename(str(target_path)))[0] if target_path else None)
        )
    if target_path:
        return os.path.splitext(os.path.basename(str(target_path)))[0]
    return link.get('base_title') or link.get('media_name')


def full_scan_triage(
    media_triage: CodexMediaTriageAgent,
    folder_path: str = None,
    test_mode: bool = False,
    dry_run: bool = False,
    run_subtitles: bool = True,
    recheck_unlinked: bool = False,
    recheck_review: bool = True,
) -> tuple[int, int, int, int]:
    batch_processor = TvBatchProcessor(media_triage.client, dry_run=dry_run)
    started_at = time.time()
    summary = {'media_kind': None, 'display_name': None}

    def triage_media(file_path: str):
        logger().info('[TriageStart] source=%s', file_path)
        restored, restore_action = restore_link_from_db(file_path, dry_run=dry_run, recheck_unlinked=recheck_unlinked, recheck_review=recheck_review)
        if restored:
            logger().info('[TriageSkip] source=%s action=%s reason=restored_from_db', file_path, restore_action)
            return restore_action

        logger().debug('[TriageInfer] source=%s attempt=1', file_path)
        flag, action = media_triage.run(file_path, dry_run=dry_run)
        logger().info('[TriageResult] source=%s attempt=1 success=%s action=%s', file_path, flag, action)
        if not flag:
            if action == 'needs_review':
                logger().warning('[TriageStop] source=%s reason=needs_review_first_attempt', file_path)
                return 'failed'
            logger().debug('[TriageInfer] source=%s attempt=2', file_path)
            flag, action = media_triage.run(file_path, dry_run=dry_run)
            logger().info('[TriageResult] source=%s attempt=2 success=%s action=%s', file_path, flag, action)
        if flag:
            return action
        logger().error('[TriageFail] source=%s action=%s', file_path, action)
        return 'failed'

    def update_summary_from_file(file_path: str):
        nonlocal summary
        try:
            parsed = parse_media_filename(file_path)
        except Exception:
            return
        if not summary.get('media_kind'):
            summary['media_kind'] = parsed.media_type
        if summary.get('media_kind') == 'tv' and not summary.get('display_name'):
            summary['display_name'] = build_tv_group_key(file_path, parsed)
        elif summary.get('media_kind') == 'movie' and not summary.get('display_name'):
            summary['display_name'] = parsed.title_guess or os.path.basename(file_path)

    def update_summary_from_media_link(file_path: str, *, single_file: bool = False) -> None:
        nonlocal summary
        link = get_media_link_by_source(MEDIA_DB, file_path)
        if not link:
            return
        media_type = link.get('media_type')
        display_name = _media_link_display_name(link, single_file=single_file)
        if media_type:
            summary['media_kind'] = media_type
        if display_name:
            summary['display_name'] = display_name

    def accumulate(action: str, counters: dict[str, int]):
        if action == 'created':
            counters['created'] += 1
        elif action == 'relinked':
            counters['relinked'] += 1
        elif action == 'exists':
            counters['existed'] += 1
        elif action in {'preview', 'unlinked'}:
            counters['preview'] += 1
        else:
            counters['failed'] += 1

    if os.path.isfile(folder_path):
        logger().info('[BatchSubmit] %s files=1 mode=single_file', folder_path)
        logger().info('[BatchFile] %s', folder_path)
        update_summary_from_file(folder_path)
        action = triage_media(folder_path)
        if action in {'created', 'relinked', 'exists', 'preview'}:
            update_summary_from_media_link(folder_path, single_file=True)
        created = 1 if action == 'created' else 0
        relinked = 1 if action == 'relinked' else 0
        existed = 1 if action == 'exists' else 0
        failed = 1 if action in {'failed','needs_review'} else 0
        preview = 1 if action == 'preview' else 0
        subtitle_summary = _run_subtitle_for_batch(folder_path, test_mode=test_mode, dry_run=dry_run) if run_subtitles else None
        send_batch_notify(folder_path, created, relinked, failed, test_mode or dry_run, summary=summary, subtitle_summary=subtitle_summary)
        elapsed = time.time() - started_at
        logger().info('[BatchDone] %s created=%d relinked=%d existed=%d preview=%d failed=%d elapsed=%.2fs', folder_path, created, relinked, existed, preview, failed, elapsed)
        return created, relinked, existed, failed

    media_list = get_main_media(folder_path, SIZE_RATIO)
    logger().info('[BatchSubmit] %s files=%d mode=directory_scan', folder_path, len(media_list))
    if not media_list:
        logger().warning('[BatchEmpty] %s no candidate media files found', folder_path)
    for index in media_list:
        file_path = index.get('path')
        if file_path:
            logger().info('[BatchFile] %s', file_path)
            update_summary_from_file(file_path)
    counters = {'created': 0, 'relinked': 0, 'existed': 0, 'preview': 0, 'failed': 0}
    pending_tv_files = []

    for index in media_list:
        file_path = index.get('path')
        if file_path is None:
            continue
        restored, restore_action = restore_link_from_db(file_path, dry_run=dry_run, recheck_unlinked=recheck_unlinked, recheck_review=recheck_review)
        if restored:
            logger().info(f'[MediaMap] {file_path} ---> restored_from_db ({restore_action})')
            accumulate(restore_action, counters)
            if restore_action in {'created', 'relinked', 'exists', 'preview'}:
                update_summary_from_media_link(file_path)
            continue
        pending_tv_files.append(file_path)

    logger().info('[BatchPending] path=%s pending_tv_candidates=%d', folder_path, len(pending_tv_files))
    batch_results = batch_processor.process(pending_tv_files)
    logger().info('[BatchTVResult] path=%s processed_by_tv_batch=%d', folder_path, len(batch_results))
    processed_tv_files = set(batch_results.keys())
    for file_path, action in batch_results.items():
        accumulate(action, counters)
        if action in {'created', 'relinked', 'exists', 'preview'}:
            update_summary_from_media_link(file_path)

    fallback_files = [file_path for file_path in pending_tv_files if file_path not in processed_tv_files]
    logger().info('[BatchFallback] path=%s ai_batch_candidates=%d batch_size=%d', folder_path, len(fallback_files), BATCH_SIZE)
    batch_handled: set[str] = set()
    for start in range(0, len(fallback_files), max(1, BATCH_SIZE)):
        batch = fallback_files[start:start + max(1, BATCH_SIZE)]
        if not batch:
            continue
        logger().info('[BatchFallback][AI] path=%s batch=%d files=%d', folder_path, start // max(1, BATCH_SIZE) + 1, len(batch))
        batch_actions = media_triage.run_batch(batch, dry_run=dry_run)
        for file_path, action in batch_actions.items():
            batch_handled.add(file_path)
            accumulate(action, counters)
            if action in {'created', 'relinked', 'exists', 'preview'}:
                update_summary_from_media_link(file_path)

    single_files = [file_path for file_path in fallback_files if file_path not in batch_handled]
    logger().info('[BatchFallback] path=%s single_file_triage=%d', folder_path, len(single_files))
    for file_path in single_files:
        action = triage_media(file_path)
        accumulate(action, counters)
        if action in {'created', 'relinked', 'exists', 'preview'}:
            update_summary_from_media_link(file_path)

    logger().info('[BatchSubtitle] path=%s start', folder_path)
    subtitle_summary = _run_subtitle_for_batch(folder_path, test_mode=test_mode, dry_run=dry_run) if run_subtitles else None
    send_batch_notify(
        folder_path,
        counters['created'],
        counters['relinked'],
        counters['failed'],
        test_mode or dry_run,
        summary=summary,
        subtitle_summary=subtitle_summary,
    )
    elapsed = time.time() - started_at
    logger().info(
        '[BatchDone] %s created=%d relinked=%d existed=%d preview=%d failed=%d elapsed=%.2fs',
        folder_path,
        counters['created'],
        counters['relinked'],
        counters['existed'],
        counters['preview'],
        counters['failed'],
        elapsed,
    )
    return counters['created'], counters['relinked'], counters['existed'], counters['failed']


def _log_failed_case_summary(scan_label: str, total_failed: int, scan_started_at: str):
    if total_failed <= 0:
        return
    failed_rows = list_failed_cases(MEDIA_DB, limit=max(total_failed, 2000), since=scan_started_at)
    if not failed_rows:
        logger().warning('[%s][FailedFiles] failed=%d but no failed_case rows found since=%s', scan_label, total_failed, scan_started_at)
        return
    logger().info('[%s][FailedFiles] total=%d', scan_label, len(failed_rows))
    for row in reversed(failed_rows):
        source_path = row.get('source_path')
        filename = row.get('filename')
        fail_stage = row.get('fail_stage')
        reason = row.get('reason')
        created_at = row.get('created_at')
        raw_name = filename or os.path.basename(source_path) or source_path
        logger().info('[%s][FailedFile] %s | stage=%s | reason=%s | created_at=%s', scan_label, raw_name, fail_stage or '-', reason or '-', created_at)


def _is_agent_blocking_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        'codex app-server authentication rejected',
        'codex app-server token is empty',
        '401 unauthorized',
        '403 forbidden',
        'quota',
        'rate limit',
        'rate_limit',
        'too many requests',
        '429',
        'usage limit',
        'insufficient',
        'credit',
        'billing',
    )
    return any(marker in message for marker in markers)


def full_scan_downloads(
    media_triage: CodexMediaTriageAgent,
    root_folder: str = FULL_SCAN_ROOT,
    test_mode: bool = False,
    dry_run: bool = False,
):
    total_created = total_relinked = total_existed = total_failed = 0
    scan_started_at = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    if not os.path.exists(root_folder):
        logger().error(f'Full scan root not found: {root_folder}')
        return

    stopped_reason = None
    for name in sorted(os.listdir(root_folder)):
        full_path = os.path.join(root_folder, name)
        try:
            c, r, e, f = full_scan_triage(media_triage, full_path, test_mode, dry_run)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if _is_agent_blocking_error(exc):
                stopped_reason = str(exc)
                logger().error('[FullScan] stop: agent quota/auth/rate-limit error path=%s error=%s', full_path, exc)
                break
            logger().exception('[FullScan] path failed; continuing path=%s error=%s', full_path, exc)
            c, r, e, f = 0, 0, 0, 1
        total_created += c
        total_relinked += r
        total_existed += e
        total_failed += f

    if stopped_reason:
        logger().warning(
            'Full scan stopped early. created=%d, relinked=%d, existed=%d, failed=%d, reason=%s',
            total_created,
            total_relinked,
            total_existed,
            total_failed,
            stopped_reason,
        )
    else:
        logger().info(f'Full scan finished. created={total_created}, relinked={total_relinked}, existed={total_existed}, failed={total_failed}')
    _log_failed_case_summary('FullScan', total_failed, scan_started_at)


def scan_selected_paths(
    media_triage: CodexMediaTriageAgent,
    paths: list[str],
    test_mode: bool = False,
    dry_run: bool = False,
):
    total_created = total_relinked = total_existed = total_failed = 0
    scan_started_at = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
    logger().info('[SelectedScan] start paths=%s test_mode=%s dry_run=%s', paths, test_mode, dry_run)
    stopped_reason = None
    for raw_path in paths:
        full_path = raw_path if os.path.isabs(raw_path) else os.path.join(FULL_SCAN_ROOT, raw_path)
        logger().info('[SelectedScan] raw_path=%s resolved_path=%s', raw_path, full_path)
        if not os.path.exists(full_path):
            logger().error(f'Selected path not found: {full_path}')
            continue
        if os.path.isdir(full_path) and os.path.normpath(full_path) == os.path.normpath(FULL_SCAN_ROOT):
            logger().warning('[SelectedScan] /data/downloads selected via --path; delegating to --full behavior to avoid global size filtering')
            full_scan_downloads(media_triage, FULL_SCAN_ROOT, test_mode, dry_run)
            continue
        try:
            c, r, e, f = full_scan_triage(media_triage, full_path, test_mode, dry_run)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if _is_agent_blocking_error(exc):
                stopped_reason = str(exc)
                logger().error('[SelectedScan] stop: agent quota/auth/rate-limit error path=%s error=%s', full_path, exc)
                break
            logger().exception('[SelectedScan] path failed; continuing path=%s error=%s', full_path, exc)
            c, r, e, f = 0, 0, 0, 1
        total_created += c
        total_relinked += r
        total_existed += e
        total_failed += f

    if stopped_reason:
        logger().warning(
            'Selected scan stopped early. created=%d, relinked=%d, existed=%d, failed=%d, reason=%s',
            total_created,
            total_relinked,
            total_existed,
            total_failed,
            stopped_reason,
        )
    else:
        logger().info(f'Selected scan finished. created={total_created}, relinked={total_relinked}, existed={total_existed}, failed={total_failed}')
    _log_failed_case_summary('SelectedScan', total_failed, scan_started_at)


def process_media(q: Queue, test_mode: bool, dry_run: bool) -> None:
    media_triage = CodexMediaTriageAgent()
    batch_seq = 0
    while True:
        folder_path = q.get()
        batch_seq += 1
        try:
            try:
                pending_after_get = q.qsize()
            except (NotImplementedError, AttributeError):
                pending_after_get = -1
            logger().info('[BatchQueue] start seq=%d pending_after_get=%d path=%s', batch_seq, pending_after_get, folder_path)
            full_scan_triage(media_triage, folder_path, test_mode, dry_run)
            try:
                pending_after_done = q.qsize()
            except (NotImplementedError, AttributeError):
                pending_after_done = -1
            logger().info('[BatchQueue] done seq=%d pending_after_done=%d path=%s', batch_seq, pending_after_done, folder_path)
            logger().info(f'✅ Media Triage Finished:{folder_path}')
        except Exception as exc:
            logger().exception('[BatchQueue] failed seq=%d path=%s error=%s', batch_seq, folder_path, exc)
        time.sleep(1)


def rebuild_by_keyword(keyword: str):
    deleted_links = delete_media_links_by_keyword(MEDIA_DB, keyword)
    logger().info(f'Rebuild cleanup finished for keyword={keyword}, media_link={deleted_links}')


def _safe_remove_empty_parent_dirs(path: str, stop_at: str):
    current = os.path.dirname(path)
    stop_at = os.path.normpath(stop_at)
    while current and os.path.commonpath((os.path.realpath(current),os.path.realpath(stop_at)))==os.path.realpath(stop_at):
        normalized = os.path.normpath(current)
        if normalized == stop_at:
            break
        try:
            os.rmdir(current)
            logger().info('[CleanupDir] removed empty dir: %s', current)
        except OSError:
            break
        current = os.path.dirname(current)


def purge_hardlinks_by_keyword(keyword: str, dry_run: bool = False):
    if dry_run:
        return _purge_hardlinks_by_keyword(keyword,dry_run=True)
    from media_mcp.storage.media import _client
    from media_mcp.runtime.state import media_mutation_lock
    with media_mutation_lock(_client(MEDIA_DB)):
        return _purge_hardlinks_by_keyword(keyword,dry_run=False)


def _purge_hardlinks_by_keyword(keyword: str, dry_run: bool = False):
    matched_links = list_media_links_by_keyword(MEDIA_DB, keyword)
    target_paths = sorted({row.get('target_path') for row in matched_links if row.get('target_path')})
    if not dry_run:
        from pathlib import Path
        root = os.path.realpath(MEDIA_ROOT)
        for path in target_paths:
            resolved = os.path.realpath(path)
            if resolved==root or os.path.commonpath((resolved,root))!=root or any(part.is_symlink() for part in (Path(path),*Path(path).parents)):
                raise RuntimeError('purge_target_outside_media_root_or_symlink')

    removed_files = 0
    missing_files = 0
    failed_files = 0

    for target_path in target_paths:
        if dry_run:
            logger().info('[PurgePreview] hardlink match: %s', target_path)
            continue
        if os.path.isfile(target_path):
            try:
                os.remove(target_path)
                removed_files += 1
                logger().info('[PurgeHardlink] removed: %s', target_path)
                _safe_remove_empty_parent_dirs(target_path, MEDIA_ROOT)
            except OSError as exc:
                failed_files += 1
                logger().error('[PurgeHardlink] failed: %s error=%s', target_path, exc)
        else:
            missing_files += 1
            logger().info('[PurgeHardlink] missing: %s', target_path)

    if dry_run:
        logger().info('[PurgePreview] keyword=%s media_link_matches=%d unique_targets=%d', keyword, len(matched_links), len(target_paths))
        return

    if failed_files:
        raise RuntimeError('purge_incomplete_database_records_preserved')
    deleted_links = delete_media_links_by_ids(MEDIA_DB,[int(row['id']) for row in matched_links])
    logger().info(
        '[PurgeDone] keyword=%s removed_files=%d missing_files=%d failed_files=%d deleted_media_link=%d',
        keyword,
        removed_files,
        missing_files,
        failed_files,
        deleted_links,
    )


def main(args):
    log_level = 'debug' if args.debug else 'info'
    log.init('%s/../../log' % (py_dir), log_name, log_mode='a', log_level=log_level, console_enable=True)
    log.get(log_name).info('Logger Create Success')
    log.get(log_name).info(f'Logger level set to {log_level}')
    set_logger(log.get(log_name))

    if args.notify:
        content = args.notify if isinstance(args.notify, str) else 'Media monitor test notification'
        flag_notify = mcp_direct_call_ns('notify.send_notification', title='Media notification test', content=content)
        if not flag_notify:
            raise RuntimeError(f'MCP notification test failed: {content}')
        logger().info('Notify test sent: %s', content)
        return

    if args.rebuild:
        rebuild_by_keyword(args.rebuild)

    if args.purge:
        purge_hardlinks_by_keyword(args.purge, args.dry_run)
        return

    if args.path:
        media_triage = CodexMediaTriageAgent()
        scan_selected_paths(media_triage, args.path, args.test, args.dry_run)
        return

    if args.full:
        media_triage = CodexMediaTriageAgent()
        full_scan_downloads(media_triage, FULL_SCAN_ROOT, args.test, args.dry_run)
        return

    logger().info('No one-shot task specified, exiting. Use apps/media/monitor/run.py for continuous monitoring.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Media agent')
    parser.add_argument('--test', action='store_true', default=False, help='Append this will enable test mode')
    parser.add_argument('--debug', action='store_true', default=False, help='Enable debug logging, default log level is info')
    parser.add_argument('--notify', nargs='?', const='Media monitor test notification', default=None, help='Send a test notification and exit, optional custom content')
    parser.add_argument('--full', action='store_true', default=False, help='Full scan all entries under /data/downloads')
    parser.add_argument('--rebuild', type=str, default=None, help='Delete cached media_link records by keyword before processing')
    parser.add_argument('--purge', type=str, default=None, help='Delete hardlink files and related media_link records by keyword')
    parser.add_argument('--dry-run', action='store_true', default=False, help='Run inference and validation without creating hardlinks, writing database records, or sending notifications')
    parser.add_argument('--path', action='append', default=None, help='Scan only the specified file/folder path. Relative paths are resolved under /data/downloads. Can be passed multiple times.')
    args = parser.parse_args()
    main(args)
