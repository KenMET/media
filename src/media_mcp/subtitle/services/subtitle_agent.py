#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from media_mcp.subtitle.services import dependencies
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from media_mcp.subtitle.clients.codex import CodexSubtitleClient











from media_mcp.subtitle.services import online_subtitles
from media_mcp.subtitle.services import translation

class SubtitleAgent:
    def __init__(
        self,
        client: 'CodexSubtitleClient | None' = None,
        provider_registry: dependencies.SubtitleProviderRegistry | None = None,
        disable_agent: bool = False,
        disable_opensubtitle: bool = False,
        defer_ai_usage: bool = True,
    ):
        self.defer_ai_usage = defer_ai_usage
        self.client = client
        self.provider_registry = provider_registry or dependencies.SubtitleProviderRegistry()
        self.disable_opensubtitle = disable_opensubtitle
        self.disable_agent = disable_agent or disable_opensubtitle
        self.cache = dependencies.SubtitleRunCache()
        self._provider_blocked_until: dict[str, float] = {}
        self._last_action_detail: str | None = None
        self._active_media_link = None

    def run_path_summary(self, raw_path: str, test_mode: bool = False, send_notify: bool = True) -> dict[str, dependencies.Any]:
        if test_mode:
            return self._run_path_summary_locked(raw_path,test_mode=True,send_notify=send_notify)
        from media_mcp.storage.client import DatabaseClient
        from media_mcp.runtime.state import media_mutation_lock
        with media_mutation_lock(DatabaseClient(db_name=dependencies.MEDIA_DB,connect_timeout_seconds=5,read_timeout_seconds=15)):
            return self._run_path_summary_locked(raw_path,test_mode=False,send_notify=send_notify)

    def _run_path_summary_locked(self, raw_path: str, test_mode: bool = False, send_notify: bool = True) -> dict[str, dependencies.Any]:
        self._content_verifications = []
        self._last_model_error = None
        path = self._resolve_path(raw_path)
        dependencies.logger.info('Input: resolving path=%s mode=%s', path, 'dry-run' if test_mode else 'apply')
        dependencies.logger.info('Lookup: media_link start path=%s', path)
        media_links = self._media_links_for_path(path)
        dependencies.logger.info('Lookup: media_link done path=%s matches=%d', path, len(media_links))
        dependencies.logger.info('Scan: subtitle sidecars start path=%s', path)
        subtitle_paths = dependencies.discover_subtitle_files(path)
        dependencies.logger.info('Scan: subtitle sidecars found path=%s files=%d', path, len(subtitle_paths))
        dependencies.logger.info('Scan: subtitle sidecars parse start files=%d', len(subtitle_paths))
        subtitle_candidates = [self._parse_subtitle_candidate(item) for item in subtitle_paths]
        dependencies.logger.info('Scan: subtitle sidecars parse done candidates=%d', len(subtitle_candidates))
        path_exists = dependencies.os.path.exists(path)
        if dependencies.os.path.isfile(path):
            path_kind = 'file'
        elif dependencies.os.path.isdir(path):
            path_kind = 'directory'
        else:
            path_kind = 'missing'
        dependencies.logger.info(
            'Input: %s (%s)',
            path,
            path_kind,
        )
        if not path_exists:
            dependencies.logger.warning('Action: failed (input does not exist)')
        elif not media_links:
            dependencies.logger.warning('Action: skipped (no media_link match)')

        handled = missing = review = failed = 0
        action_counts: dict[str, int] = {}
        detailed_action_counts: dict[str, int] = {}
        for media_index,media_link in enumerate(media_links):
            self._active_media_link = media_link
            self._last_action_detail = None
            try:
                from media_mcp.runtime.state import mutation_lock_is_active
                action = None
                if not test_mode and mutation_lock_is_active():
                    dependencies.assert_mutation_lock()
                    latest = dependencies.get_media_link_by_source(dependencies.MEDIA_DB,media_link['source_path'])
                    if not latest or latest.get('status') not in {'linked','source_missing','target_missing'}:
                        action = 'skipped'
                    else:
                        media_link = latest
                        self._active_media_link = latest
                if action is None:
                    action = self._process_media_link(media_link, subtitle_candidates, test_mode=test_mode)
            except Exception as exc:
                action = 'failed'
                reason = f'{type(exc).__name__}: {exc}'
                dependencies.logger.exception(
                    'Action: failed (unhandled subtitle exception) source=%s target=%s',
                    media_link.get('source_path'),
                    media_link.get('target_path'),
                )
                if not test_mode:
                    try:
                        self._record_failed(
                            media_link,
                            {'media_link': self._candidate_video_payload(media_link)},
                            'batch_exception',
                            reason,
                        )
                    except Exception:
                        dependencies.logger.exception(
                            'Action: failed to record subtitle batch exception source=%s target=%s',
                            media_link.get('source_path'),
                            media_link.get('target_path'),
                        )
                if not self._last_action_detail:
                    self._set_action_detail(dependencies.failure_detail_key('batch_exception'))
            action_counts[action] = action_counts.get(action, 0) + 1
            action_detail = self._consume_action_detail(action)
            detailed_action_counts[action_detail] = detailed_action_counts.get(action_detail, 0) + 1
            if action in dependencies.HANDLED_ACTIONS:
                handled += 1
            elif action == 'missing':
                missing += 1
            elif action == 'needs_review':
                review += 1
            elif action != 'skipped':
                failed += 1
            if not test_mode and media_index+1<len(media_links):
                from media_mcp.runtime.state import release_mutation_lock_for_io
                # Give pending ingest/deletion operations a turn between files.
                with release_mutation_lock_for_io():
                    dependencies.time.sleep(.02)
        dependencies.logger.info(
            'Summary: media=%d, sidecars=%d, handled=%d, missing=%d, review=%d, failed=%d',
            len(media_links),
            len(subtitle_candidates),
            handled,
            missing,
            review,
            failed,
        )
        if send_notify:
            self._send_subtitle_notify(path, media_links, action_counts, detailed_action_counts, test_mode=test_mode)
        return {
            'handled': handled,
            'missing': missing,
            'review': review,
            'failed': failed,
            'action_counts': action_counts,
            'detailed_action_counts': detailed_action_counts,
            'skipped': action_counts.get('skipped',0),
            'media_count': len(media_links),
            'sidecar_count': len(subtitle_candidates),
            'content_verifications': self._content_verifications,
        }

    def run_path(self, raw_path: str, test_mode: bool = False) -> tuple[int, int, int, int]:
        summary = self.run_path_summary(raw_path, test_mode=test_mode, send_notify=True)
        handled = int(summary.get('handled') or 0)
        missing = int(summary.get('missing') or 0)
        review = int(summary.get('review') or 0)
        failed = int(summary.get('failed') or 0)
        return handled, missing, review, failed

    def _parse_subtitle_candidate(self, path: str) -> dependencies.SubtitleCandidate:
        return self.cache.parse_subtitle_candidate(path)

    def _redact_sensitive_text(self, value: dependencies.Any) -> str:
        return dependencies.redact_sensitive_text(value)

    def _provider_file_ref(self, provider: str, file_id: dependencies.Any) -> str:
        return f'{provider}:{self._redact_sensitive_text(file_id)}'

    def _provider_blocked_retry_at(self, provider_name: str) -> float | None:
        retry_at = self._provider_blocked_until.get(provider_name)
        if not retry_at:
            return None
        if retry_at <= dependencies.time.time():
            self._provider_blocked_until.pop(provider_name, None)
            return None
        return retry_at

    def _mark_provider_unavailable(self, exc: dependencies.ProviderTemporarilyUnavailable) -> str:
        retry_at = exc.retry_at or (dependencies.time.time() + 900)
        self._provider_blocked_until[exc.provider] = retry_at
        return dependencies.time.strftime('%Y-%m-%d %H:%M:%S', dependencies.time.localtime(retry_at))

    def _search_provider_candidates(
        self,
        provider: dependencies.Any,
        provider_name: str,
        request: dependencies.SubtitleSearchRequest,
    ) -> list[dependencies.OnlineSubtitleCandidate]:
        search = getattr(provider, 'search', None)
        if callable(search):
            return self._external_call(lambda:search(request))

        registry_search = getattr(self.provider_registry, 'search', None)
        if not callable(registry_search):
            raise RuntimeError(f'provider search unavailable: {provider_name}')
        result = self._external_call(lambda:registry_search(request))
        if isinstance(result, tuple) and len(result) == 2:
            candidates, attempts = result
            for attempt in attempts or []:
                if getattr(attempt, 'provider', None) != provider_name:
                    continue
                if not getattr(attempt, 'success', False):
                    dependencies.logger.info(
                        'Online provider %s: failed (%s)',
                        provider_name,
                        getattr(attempt, 'error', None) or 'unknown error',
                    )
        else:
            candidates = result
        return [
            candidate
            for candidate in candidates or []
            if getattr(candidate, 'provider', None) == provider_name
        ]

    def _download_provider_candidate(self, provider: dependencies.Any, candidate: dependencies.OnlineSubtitleCandidate):
        download = getattr(provider, 'download', None)
        if callable(download):
            return self._external_call(lambda:download(candidate))

        registry_download = getattr(self.provider_registry, 'download', None)
        if callable(registry_download):
            return self._external_call(lambda:registry_download(candidate))
        raise RuntimeError(f'provider download unavailable: {candidate.provider}')

    def _is_ai_usage_retryable(self, error: dependencies.Any) -> bool:
        text = str(error or '').lower()
        retry_markers = (
            'quota',
            'rate limit',
            'ratelimit',
            'rate_limit',
            '429',
            'too many requests',
            'usage limit',
            'limit reached',
            'billing',
            'insufficient',
            'credit',
            'capacity',
            'temporarily unavailable',
        )
        return any(marker in text for marker in retry_markers)

    def _model_media_snapshot(self):
        media_link = self._active_media_link
        if not media_link:
            raise RuntimeError('media_model_scope_missing')
        files = []
        for key in ('source_path','target_path'):
            path = str(media_link.get(key) or '')
            try:
                stat = dependencies.os.stat(path,follow_symlinks=False)
                files.append((path,stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns))
            except FileNotFoundError:
                files.append((path,None))
        record = dependencies.get_media_link_by_source(dependencies.MEDIA_DB,media_link['source_path'])
        mapping = tuple(record.get(key) for key in ('id','source_path','target_path','status','updated_at')) if record else None
        return files,mapping

    def _external_call(self, call):
        from media_mcp.runtime.state import mutation_lock_is_active,release_mutation_lock_for_io
        from media_mcp.adapters.codex import CodexError
        try:
            if not mutation_lock_is_active():
                return call()
            before = self._model_media_snapshot()
            with release_mutation_lock_for_io(lambda:self._model_media_snapshot()==before):
                return call()
        except CodexError as error:
            # Lower-level subtitle fallbacks may consume the exception. The
            # durable worker still needs its actual submission certainty.
            self._last_model_error = error
            raise

    def _call_ai_with_usage_retry(self, call, *, media_label: str, operation: str):
        attempt = 0
        waited_seconds = 0
        while True:
            attempt += 1
            try:
                result = self._external_call(call)
            except Exception as exc:
                if self.defer_ai_usage or not self._is_ai_usage_retryable(exc):
                    raise
                if waited_seconds >= dependencies.AI_RETRY_MAX_WAIT_SECONDS:
                    raise RuntimeError(
                        f'AI retry exceeded max wait for {operation} media={media_label}: '
                        f'waited={waited_seconds}s max={dependencies.AI_RETRY_MAX_WAIT_SECONDS}s; '
                        f'last_error={self._redact_sensitive_text(exc)}'
                    ) from exc
                dependencies.logger.warning(
                    'AI retry: %s media=%s attempt=%d wait=%ss waited=%ss/%ss reason=%s',
                    operation,
                    media_label,
                    attempt,
                    dependencies.AI_RETRY_WAIT_SECONDS,
                    waited_seconds,
                    dependencies.AI_RETRY_MAX_WAIT_SECONDS,
                    self._redact_sensitive_text(exc),
                )
                dependencies.time.sleep(dependencies.AI_RETRY_WAIT_SECONDS)
                waited_seconds += dependencies.AI_RETRY_WAIT_SECONDS
                continue
            if (
                isinstance(result, dict)
                and result.get('success') is False
                and self._is_ai_usage_retryable(result.get('error'))
            ):
                if self.defer_ai_usage:
                    raise RuntimeError('ai_usage_deferred')
                if waited_seconds >= dependencies.AI_RETRY_MAX_WAIT_SECONDS:
                    raise RuntimeError(
                        f'AI retry exceeded max wait for {operation} media={media_label}: '
                        f'waited={waited_seconds}s max={dependencies.AI_RETRY_MAX_WAIT_SECONDS}s; '
                        f'last_error={self._redact_sensitive_text(result.get("error"))}'
                    )
                dependencies.logger.warning(
                    'AI retry: %s media=%s attempt=%d wait=%ss waited=%ss/%ss reason=%s',
                    operation,
                    media_label,
                    attempt,
                    dependencies.AI_RETRY_WAIT_SECONDS,
                    waited_seconds,
                    dependencies.AI_RETRY_MAX_WAIT_SECONDS,
                    self._redact_sensitive_text(result.get('error')),
                )
                dependencies.time.sleep(dependencies.AI_RETRY_WAIT_SECONDS)
                waited_seconds += dependencies.AI_RETRY_WAIT_SECONDS
                continue
            return result

    def _translation_any_fallback_languages(self, already_tried: tuple[str, ...]) -> tuple[str, ...]:
        tried = {self._normalize_language_code(item) or item for item in already_tried}
        return tuple(
            language
            for language in dependencies.TRANSLATION_ANY_FALLBACK_LANGUAGES
            if language not in tried and language not in dependencies.CHINESE_LANGUAGES
        )

    def _target_sidecar_candidates(
        self,
        media_link: dict[str, dependencies.Any],
        sidecars: list[dependencies.SubtitleCandidate],
    ) -> list[dependencies.SubtitleCandidate]:
        target_path = str(media_link.get('target_path') or '')
        if not target_path:
            return sidecars
        stem, _ = dependencies.os.path.splitext(target_path)
        directory = dependencies.os.path.dirname(stem)
        base_name = dependencies.os.path.basename(stem)
        if not directory or not base_name:
            return sidecars
        try:
            names = self._listdir_cached(directory)
        except OSError as exc:
            dependencies.logger.warning('Scan: target sidecars failed path=%s (%s)', target_path, exc)
            return sidecars

        existing_paths = {dependencies.os.path.abspath(item.path) for item in sidecars}
        merged = list(sidecars)
        added = 0
        for name in names:
            path = dependencies.os.path.join(directory, name)
            extension = dependencies.os.path.splitext(name)[1].lower()
            if extension not in dependencies.SUBTITLE_EXTENSIONS:
                continue
            subtitle_stem = dependencies.os.path.splitext(name)[0]
            if subtitle_stem != base_name and not subtitle_stem.startswith(f'{base_name}.'):
                continue
            absolute = dependencies.os.path.abspath(path)
            if absolute in existing_paths:
                continue
            merged.append(self._parse_subtitle_candidate(path))
            existing_paths.add(absolute)
            added += 1
        if added:
            dependencies.logger.info('Scan: target sidecars path=%s added=%d', target_path, added)
        return merged

    def _has_matching_local_sidecar(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.SubtitleCandidate],
    ) -> bool:
        source_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('source_path') or ''))[0].lower()
        target_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('target_path') or ''))[0].lower()
        media_stems = {stem for stem in (source_stem, target_stem) if stem}
        for candidate in candidates:
            if candidate.generated_by_agent:
                continue
            subtitle_stem = dependencies.os.path.splitext(dependencies.os.path.basename(candidate.path))[0].lower()
            if not any(
                subtitle_stem == media_stem or subtitle_stem.startswith(f'{media_stem}.')
                for media_stem in media_stems
            ):
                continue
            if media_link.get('media_type') == 'tv':
                expected_episode = self._optional_int(media_link.get('episode'))
                expected_season = self._optional_int(media_link.get('season'))
                if candidate.episode is not None and candidate.episode != expected_episode:
                    continue
                if candidate.season is not None and expected_season is not None and candidate.season != expected_season:
                    continue
            return True
        return False

    def _select_existing_target_sidecar(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.SubtitleCandidate],
    ) -> dependencies.SubtitleCandidate | None:
        target_path = str(media_link.get('target_path') or '')
        target_stem = dependencies.os.path.splitext(dependencies.os.path.basename(target_path))[0].lower()
        ranked: list[tuple[int, dependencies.SubtitleCandidate]] = []
        for candidate in candidates:
            if candidate.generated_by_agent:
                continue
            if not self._is_existing_target_sidecar(media_link, candidate.path):
                continue
            subtitle_stem = dependencies.os.path.splitext(dependencies.os.path.basename(candidate.path))[0].lower()
            if '.subtitle-translation-source' in subtitle_stem:
                continue
            score = candidate.preference_score
            if subtitle_stem == target_stem:
                score += 30
            if candidate.language:
                score += 5
            if candidate.subtitle_type == 'normal':
                score += 5
            elif candidate.subtitle_type in {'forced', 'commentary'}:
                score -= 40
            ranked.append((score, candidate))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1].path), reverse=True)
        selected = ranked[0][1]
        dependencies.logger.info('Selection: existing target sidecar %s', dependencies.os.path.basename(selected.path))
        return selected

    def _listdir_cached(self, directory: str) -> list[str]:
        return self.cache.listdir(directory)

    def _invalidate_path_cache(self, path: str | None) -> None:
        self.cache.invalidate_path(path)

    def _remove_file(self, path: str) -> None:
        self.cache.remove_file(path)

    def _replace_file(self, source_path: str, target_path: str) -> None:
        self.cache.replace_file(source_path, target_path)

    def _stage_label(self, index: int, name: str) -> str:
        return f'Subtitle stage {index}/6 {name}'

    def _sync_downloaded_subtitle(
        self,
        media_link: dict[str, dependencies.Any],
        subtitle_path: str,
        *,
        candidate_ref: str,
        validate_content: dependencies.Callable[[bytes, str], dependencies.Any],
    ) -> tuple[bool, str]:
        mode = dependencies.SUBTITLE_SYNC_MODE if dependencies.SUBTITLE_SYNC_MODE in {'auto', 'required', 'disabled'} else 'required'
        if mode == 'disabled':
            return True, 'subtitle_sync=disabled'

        _, extension = dependencies.os.path.splitext(subtitle_path)
        synced_path = dependencies.shorten_sidecar_path(subtitle_path, f'.synced{extension or ".srt"}')
        try:
            if dependencies.os.path.exists(synced_path):
                self._remove_file(synced_path)
        except OSError:
            pass

        try:
            result = dependencies.sync_subtitle_to_audio(
                str(self._video_path(media_link) or ''),
                subtitle_path,
                synced_path,
                binary=dependencies.SUBTITLE_SYNC_BINARY,
                timeout_seconds=dependencies.SUBTITLE_SYNC_TIMEOUT_SECONDS,
            )
            if not result.applied:
                if mode == 'required':
                    return False, result.reason
                dependencies.logger.info(
                    'Subtitle sync skipped: %s (%s)',
                    candidate_ref,
                    result.reason,
                )
                return True, f'subtitle_sync={result.reason}'
            with open(result.output_path, 'rb') as handle:
                validate_content(handle.read(), dependencies.os.path.basename(subtitle_path))
            self._replace_file(result.output_path, subtitle_path)
            self._invalidate_path_cache(subtitle_path)
            dependencies.logger.info('Subtitle sync applied: %s -> %s', candidate_ref, dependencies.os.path.basename(subtitle_path))
            return True, 'subtitle_sync=ffsubsync'
        except Exception as exc:
            reason = self._redact_sensitive_text(exc)
            dependencies.logger.warning('Subtitle sync failed: %s (%s)', candidate_ref, reason)
            return False, f'subtitle_sync_failed={reason}'
        finally:
            try:
                if dependencies.os.path.exists(synced_path):
                    self._remove_file(synced_path)
            except OSError:
                pass

    def _video_duration_seconds(self, video_path: str | None) -> float | None:
        if not video_path or not dependencies.os.path.isfile(video_path):
            return None
        try:
            completed = dependencies.subprocess.run(
                [
                    'ffprobe',
                    '-v',
                    'error',
                    '-show_entries',
                    'format=duration',
                    '-of',
                    'default=noprint_wrappers=1:nokey=1',
                    video_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float((completed.stdout or '').strip())
        except (OSError, dependencies.subprocess.SubprocessError, ValueError):
            return None
        return duration if duration > 0 else None

    def _validate_online_subtitle_timing(
        self,
        media_link: dict[str, dependencies.Any],
        subtitle_path: str,
    ) -> tuple[bool, str]:
        duration = self._video_duration_seconds(self._video_path(media_link))
        if duration is None:
            return True, 'subtitle_timing=unknown'
        try:
            events = dependencies.parse_text_subtitle(subtitle_path)
        except dependencies.SubtitleTranslationError as exc:
            return False, f'subtitle_timing_parse_failed={exc}'
        last_end = max((event.end_seconds for event in events), default=0.0)
        allowed_overrun = max(
            dependencies.ONLINE_SUBTITLE_MAX_END_OVERRUN_SECONDS,
            duration * dependencies.ONLINE_SUBTITLE_MAX_END_OVERRUN_RATIO,
        )
        if last_end > duration + allowed_overrun:
            return (
                False,
                (
                    'subtitle_timing_overrun='
                    f'last_end:{last_end:.1f},duration:{duration:.1f},allowed:{allowed_overrun:.1f}'
                ),
            )
        return True, f'subtitle_timing=ok:last_end:{last_end:.1f},duration:{duration:.1f}'

    def _online_candidate_text_fields(
        self,
        candidate: dependencies.OnlineSubtitleCandidate,
        *,
        downloaded_file_name: str | None = None,
    ) -> tuple[tuple[str, str], ...]:
        fields = [
            ('downloaded_file_name', downloaded_file_name),
            ('file_name', candidate.file_name),
            ('title', candidate.title),
            ('release', candidate.release),
            ('file_id', candidate.file_id),
        ]
        metadata = candidate.metadata or {}
        for key in ('page_url', 'videoname'):
            value = metadata.get(key)
            if value:
                fields.append((f'metadata.{key}', value))
        return tuple((label, str(value)) for label, value in fields if value)

    def _parse_explicit_episode_marker(self, text: str) -> tuple[int | None, int | None] | None:
        decoded = dependencies.unquote(str(text or '')).replace('\\', '/')
        patterns = (
            dependencies.re.compile(r'(?i)(?:^|[^a-z0-9])s(?P<season>\d{1,2})[\s._-]*e(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
            dependencies.re.compile(r'(?i)(?:^|[^a-z0-9])(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
            dependencies.re.compile(r'(?i)(?:^|[^a-z0-9])e(?:p(?:isode)?)?[\s._-]*(?P<episode>\d{1,3})(?:[^a-z0-9]|$)'),
        )
        for pattern in patterns:
            match = pattern.search(decoded)
            if not match:
                continue
            season = match.groupdict().get('season')
            episode = match.groupdict().get('episode')
            if not episode:
                continue
            return (int(season) if season else None, int(episode))
        return None

    def _online_candidate_explicit_episode_mismatch(
        self,
        media_link: dict[str, dependencies.Any],
        candidate: dependencies.OnlineSubtitleCandidate,
        *,
        downloaded_file_name: str | None = None,
    ) -> str | None:
        if str(media_link.get('media_type') or 'movie') != 'tv':
            return None
        expected_season = self._optional_int(media_link.get('season'))
        expected_episode = self._optional_int(media_link.get('episode'))
        if expected_episode is None:
            return None
        for label, text in self._online_candidate_text_fields(candidate, downloaded_file_name=downloaded_file_name):
            marker = self._parse_explicit_episode_marker(text)
            if not marker:
                continue
            season, episode = marker
            if season is not None and expected_season is not None and season != expected_season:
                return f'explicit season mismatch in {label}: S{season:02d}E{episode:02d}'
            if episode != expected_episode:
                return f'explicit episode mismatch in {label}: E{episode:02d}'
        return None

    def _online_candidate_has_explicit_episode_match(
        self,
        media_link: dict[str, dependencies.Any],
        candidate: dependencies.OnlineSubtitleCandidate,
    ) -> bool:
        if str(media_link.get('media_type') or 'movie') != 'tv':
            return False
        expected_season = self._optional_int(media_link.get('season'))
        expected_episode = self._optional_int(media_link.get('episode'))
        if expected_episode is None:
            return False
        for _, text in self._online_candidate_text_fields(candidate):
            marker = self._parse_explicit_episode_marker(text)
            if not marker:
                continue
            season, episode = marker
            if episode != expected_episode:
                continue
            if season is not None and expected_season is not None and season != expected_season:
                continue
            return True
        return False

    def _online_candidate_title_compatible(
        self,
        media_link: dict[str, dependencies.Any],
        candidate: dependencies.OnlineSubtitleCandidate,
    ) -> bool:
        haystack = ' '.join(
            text
            for _, text in self._online_candidate_text_fields(candidate)
        ).casefold()
        if not haystack:
            return True

        saw_meaningful_title = False
        for title in self._online_search_titles(media_link):
            candidate_title = dependencies.os.path.splitext(str(title or '').strip())[0]
            cjk_chars = dependencies.re.findall(r'[\u4e00-\u9fff]', candidate_title)
            if len(cjk_chars) >= 2:
                saw_meaningful_title = True
                if sum(1 for char in cjk_chars if char in haystack) >= min(2, len(cjk_chars)):
                    return True
            words = [
                word
                for word in dependencies.re.split(r'[^a-z0-9]+', candidate_title.casefold())
                if len(word) >= 3 and not word.isdigit()
            ]
            if words:
                saw_meaningful_title = True
                required = min(2, len(words))
                if sum(1 for word in words[:3] if word in haystack) >= required:
                    return True
        return not saw_meaningful_title

    def _set_action_detail(self, detail: str | None) -> None:
        self._last_action_detail = detail or None

    def _consume_action_detail(self, action: str) -> str:
        detail = self._last_action_detail or action
        self._last_action_detail = None
        return detail

    def _send_subtitle_notify(
        self,
        path: str,
        media_links: list[dict[str, dependencies.Any]],
        action_counts: dict[str, int],
        detailed_action_counts: dict[str, int] | None = None,
        test_mode: bool = False,
    ) -> None:
        if test_mode or not media_links or not action_counts:
            return

        display_name = self._subtitle_batch_display_name(path, media_links)
        if len(media_links) == 1:
            action = next(iter(action_counts))
            detail = next(iter(detailed_action_counts or action_counts))
            label = dependencies.subtitle_detail_label(detail)
            if action in dependencies.HANDLED_ACTIONS:
                content = f'{self._media_kind_label(media_links)} {display_name} 字幕按{label}处理完成'
            else:
                content = f'{self._media_kind_label(media_links)} {display_name} 字幕{label}'
        else:
            parts = dependencies.subtitle_notify_parts(detailed_action_counts or action_counts)
            content = f'字幕处理[{display_name}]：' + '，'.join(parts)

        flag_notify = dependencies.mcp_direct_call_ns('notify.send_notification', title='Media字幕通知', content=content)
        if not flag_notify:
            raise RuntimeError(f'MCP notification failed for subtitle path: {path}, {content}')

    def _subtitle_batch_display_name(self, path: str, media_links: list[dict[str, dependencies.Any]]) -> str:
        if len(media_links) == 1:
            return self._media_display_name(media_links[0])

        names = {
            str(item.get('media_name') or item.get('base_title') or '').strip()
            for item in media_links
            if str(item.get('media_name') or item.get('base_title') or '').strip()
        }
        if len(names) == 1:
            return f'{next(iter(names))} ({len(media_links)}个媒体)'

        base = dependencies.os.path.basename(path.rstrip('/')) if path else ''
        return base or 'media'

    def _media_display_name(self, media_link: dict[str, dependencies.Any]) -> str:
        title = (
            media_link.get('media_name')
            or media_link.get('base_title')
            or media_link.get('title_guess')
            or dependencies.os.path.basename(str(media_link.get('target_path') or media_link.get('source_path') or 'media'))
        )
        details = []
        if media_link.get('season') is not None:
            details.append(f'S{int(media_link["season"]):02d}')
        if media_link.get('episode') is not None:
            details.append(f'E{int(media_link["episode"]):02d}')
        if details:
            return f'{title} {"".join(details)}'
        return str(title)

    def _media_kind_label(self, media_links: list[dict[str, dependencies.Any]]) -> str:
        kinds = {str(item.get('media_type') or '') for item in media_links}
        if kinds == {'movie'}:
            return '电影'
        if kinds == {'tv'}:
            return '剧集'
        return '媒体'

    def _resolve_path(self, raw_path: str) -> str:
        if dependencies.os.path.isabs(raw_path):
            path = raw_path
        else:
            path = dependencies.os.path.join(dependencies.FULL_SCAN_ROOT, raw_path)
        return self._normalize_shell_escaped_path(path)

    def _normalize_shell_escaped_path(self, path: str) -> str:
        if dependencies.os.path.exists(path) or '\\' not in path:
            return path
        unescaped = dependencies.re.sub(r'\\([^A-Za-z0-9])', r'\1', path)
        if unescaped != path and dependencies.os.path.exists(unescaped):
            dependencies.logger.debug('Normalized shell-escaped path: %s -> %s', path, unescaped)
            return unescaped
        return path

    def _media_links_for_path(self, path: str) -> list[dict[str, dependencies.Any]]:
        if not dependencies.os.path.exists(path):
            return []
        if dependencies.os.path.isfile(path):
            prefix = path
        else:
            prefix = path.rstrip('/')
        rows = dependencies.list_media_links_by_source_prefix(dependencies.MEDIA_DB, prefix)
        rows.extend(dependencies.list_media_links_by_target_prefix(dependencies.MEDIA_DB, prefix))
        deduped: dict[dependencies.Any, dict[str, dependencies.Any]] = {}
        stale = 0
        for row in rows:
            source_path = str(row.get('source_path') or '')
            target_path = str(row.get('target_path') or '')
            source_matches = dependencies.os.path.isfile(source_path) and self._path_in_scope(source_path, path)
            target_matches = dependencies.os.path.isfile(target_path) and self._path_in_scope(target_path, path)
            if not source_matches and not target_matches:
                stale += 1
                continue
            key = row.get('id') or (row.get('source_path'), row.get('target_path'))
            deduped[key] = row
        if stale:
            dependencies.logger.info('Media links: skipped stale=%d (files no longer exist in scan scope)', stale)
        return list(deduped.values())

    def _path_in_scope(self, candidate: str, scope: str) -> bool:
        candidate = dependencies.os.path.abspath(candidate)
        scope = dependencies.os.path.abspath(scope)
        if dependencies.os.path.isfile(scope):
            return candidate == scope
        try:
            return dependencies.os.path.commonpath((candidate, scope)) == scope
        except ValueError:
            return False

    def _process_media_link(self, media_link: dict[str, dependencies.Any], sidecars: list[dependencies.SubtitleCandidate], test_mode: bool = False) -> str:
        source_path = media_link.get('source_path')
        target_path = media_link.get('target_path')
        if not source_path or not target_path:
            self._set_action_detail(dependencies.failure_detail_key('invalid_media_link'))
            return 'failed'
        media_label = dependencies.os.path.basename(target_path or source_path)
        details = [str(media_link.get('media_type') or 'media')]
        if media_link.get('season') is not None:
            details.append(f'S{int(media_link["season"]):02d}')
        if media_link.get('episode') is not None:
            details.append(f'E{int(media_link["episode"]):02d}')
        dependencies.logger.info('Media: %s (%s)', media_label, ' '.join(details))
        media_sidecars = self._target_sidecar_candidates(media_link, sidecars)

        translated_target = self._translated_target_path(media_link)
        if not test_mode and dependencies.os.path.exists(translated_target):
            self._remove_mislinked_generated_subtitle(media_link, translated_target)
        legacy_translated_target = self._legacy_translated_target_path(media_link)
        if (
            translated_target != legacy_translated_target
            and dependencies.os.path.exists(legacy_translated_target)
            and self._parse_subtitle_candidate(legacy_translated_target).generated_by_agent
        ):
            if test_mode:
                dependencies.logger.info(
                    'Action: would rename legacy bilingual subtitle %s -> %s',
                    dependencies.os.path.basename(legacy_translated_target),
                    dependencies.os.path.basename(translated_target),
                )
            else:
                self._replace_file(legacy_translated_target, translated_target)
                self._cleanup_legacy_translation_sources(media_link)
                dependencies.restyle_bilingual_ass(
                    translated_target,
                    chinese_font_size=dependencies.CHINESE_FONT_SIZE,
                    source_font_size=dependencies.SOURCE_FONT_SIZE,
                    bottom_margin=dependencies.SUBTITLE_BOTTOM_MARGIN,
                )
                dependencies.logger.info(
                    'Action: renamed legacy bilingual subtitle %s -> %s',
                    dependencies.os.path.basename(legacy_translated_target),
                    dependencies.os.path.basename(translated_target),
                )
            return self._record_existing_generated(media_link, translated_target if not test_mode else legacy_translated_target, test_mode=test_mode)
        if (
            dependencies.os.path.exists(translated_target)
            and self._parse_subtitle_candidate(translated_target).generated_by_agent
        ):
            if not test_mode:
                self._cleanup_legacy_translation_sources(media_link)
                if dependencies.restyle_bilingual_ass(
                    translated_target,
                    chinese_font_size=dependencies.CHINESE_FONT_SIZE,
                    source_font_size=dependencies.SOURCE_FONT_SIZE,
                    bottom_margin=dependencies.SUBTITLE_BOTTOM_MARGIN,
                ):
                    dependencies.logger.info(
                        'Action: updated generated subtitle style %s',
                        dependencies.os.path.basename(translated_target),
                    )
            dependencies.logger.info('Action: kept existing generated subtitle %s', dependencies.os.path.basename(translated_target))
            return self._record_existing_generated(media_link, translated_target, test_mode=test_mode)

        existing_target_sidecar = self._select_existing_target_sidecar(media_link, media_sidecars)
        if existing_target_sidecar:
            if existing_target_sidecar.extension.lower() in {'.srt', '.ass', '.ssa', '.vtt'}:
                try:
                    with open(existing_target_sidecar.path, 'rb') as handle:
                        dependencies.validate_online_subtitle(handle.read(), dependencies.os.path.basename(existing_target_sidecar.path))
                except (OSError, ValueError) as exc:
                    dependencies.logger.warning('Existing subtitle content rejected: %s', self._redact_sensitive_text(exc))
                    if test_mode or isinstance(exc, OSError):
                        return self._mark_needs_review(media_link, 'existing_subtitle_chinese_content_unverified', test_mode=test_mode)
                    rejected_path = existing_target_sidecar.path
                    backup_path = f'{rejected_path}.{dependencies.uuid.uuid4().hex}.rejected-language'
                    self._replace_file(rejected_path, backup_path)
                    self._invalidate_path_cache(rejected_path)
                    media_sidecars = [item for item in media_sidecars if item.path != rejected_path]
                    existing_target_sidecar = None
                    dependencies.logger.warning('Preserved rejected subtitle at %s; continuing Chinese acquisition', backup_path)
        if existing_target_sidecar:
            action = self._process_sidecar(media_link, existing_target_sidecar, test_mode=test_mode)
            self._cleanup_redundant_language_sidecars(media_link, test_mode=test_mode)
            return action

        stage = self._stage_label(1, 'embedded Chinese')
        dependencies.logger.info('%s: start media=%s priority=bilingual,zh-CN,zh-Hant', stage, self._media_display_name(media_link))
        embedded_action = self._process_embedded(media_link, test_mode=test_mode)
        if embedded_action in {'embedded_default_set', 'embedded_extracted', 'exists'}:
            dependencies.logger.info('%s: hit action=%s', stage, embedded_action)
            self._cleanup_redundant_language_sidecars(media_link, test_mode=test_mode)
            return embedded_action

        if embedded_action == 'needs_review':
            dependencies.logger.info('%s: needs_review reason=ambiguous_embedded_subtitles', stage)
            if test_mode:
                dependencies.logger.info('Action: needs review (ambiguous embedded subtitles)')
            return self._mark_needs_review(media_link, 'ambiguous_embedded_subtitles', test_mode=test_mode)

        if embedded_action == 'embedded_probe_failed':
            dependencies.logger.info('%s: failed reason=embedded_probe_failed', stage)
            if test_mode:
                dependencies.logger.info('Action: failed (embedded subtitle probe failed)')
            else:
                self._record_failed(media_link, {}, 'embedded_probe', 'embedded_probe_failed')
            return 'failed'
        dependencies.logger.info('%s: miss reason=%s', stage, embedded_action or 'no_embedded_chinese_subtitle')

        stage = self._stage_label(2, 'sidecar Chinese')
        dependencies.logger.info('%s: start media=%s priority=bilingual,zh-CN,zh-Hant candidates=%d', stage, self._media_display_name(media_link), len(media_sidecars))
        sidecar, sidecar_review_reason = self._select_sidecar(media_link, media_sidecars, test_mode=test_mode)
        if sidecar:
            dependencies.logger.info('%s: hit source=%s', stage, dependencies.os.path.basename(sidecar.path))
            action = self._process_sidecar(media_link, sidecar, test_mode=test_mode)
            self._cleanup_redundant_language_sidecars(media_link, test_mode=test_mode)
            return action

        if sidecar_review_reason:
            dependencies.logger.info('%s: needs_review reason=%s', stage, sidecar_review_reason)
            if test_mode:
                dependencies.logger.info('Action: needs review (%s)', sidecar_review_reason)
            return self._mark_needs_review(media_link, sidecar_review_reason, test_mode=test_mode)
        dependencies.logger.info('%s: miss reason=no_matching_chinese_sidecar', stage)

        if self.disable_opensubtitle:
            dependencies.logger.warning(
                'Action: local subtitle processing complete; '
                'online providers and AI processing skipped (opensubtitle disabled)'
            )
            return self._mark_missing(
                media_link,
                'opensubtitle_disabled_no_local_chinese_subtitle',
                test_mode=test_mode,
            )

        stage = self._stage_label(3, 'online Chinese')
        dependencies.logger.info('%s: start media=%s priority=bilingual,zh-CN,zh-Hant sync=%s', stage, self._media_display_name(media_link), dependencies.SUBTITLE_SYNC_MODE)
        online_action = self._process_online_subtitle(media_link, test_mode=test_mode)
        if online_action in {'downloaded', 'exists'}:
            dependencies.logger.info('%s: hit action=%s', stage, online_action)
            return online_action
        dependencies.logger.info('%s: miss reason=no_online_chinese_subtitle', stage)

        if self.disable_agent:
            dependencies.logger.warning(
                'Action: skipped AI subtitle processing '
                '(agent disabled and no local/online Chinese subtitle found)'
            )
            return self._mark_missing(
                media_link,
                'agent_disabled_no_local_or_online_chinese_subtitle',
                test_mode=test_mode,
            )

        translation_action = self._process_text_translation(
            media_link,
            media_sidecars,
            test_mode=test_mode,
            source_kinds=('embedded', 'sidecar', 'online'),
            reuse_existing_output=False,
        )
        if translation_action:
            return translation_action

        audio_action = self._process_audio_transcription(media_link, test_mode=test_mode)
        if audio_action:
            return audio_action

        reason = embedded_action or 'no_preferred_subtitle'
        if test_mode:
            dependencies.logger.info('Action: missing (%s)', self._display_missing_reason(reason))
        return self._mark_missing(media_link, reason, test_mode=test_mode)

    def _process_embedded(self, media_link: dict[str, dependencies.Any], test_mode: bool = False) -> str | None:
        video_path = self._video_path(media_link)
        if not dependencies.shutil.which('ffprobe'):
            dependencies.logger.warning('Candidates: embedded unavailable (ffprobe missing)')
            return 'embedded_probe_failed'
        try:
            streams = dependencies.ffprobe_subtitle_streams(video_path)
        except dependencies.EmbeddedSubtitleProbeError as exc:
            dependencies.logger.warning('Candidates: embedded probe failed (%s)', exc)
            return 'embedded_probe_failed'
        if test_mode:
            preferred_streams = [stream for stream in streams if stream.preference_score > 0]
            dependencies.logger.info('Candidates: embedded=%d, preferred=%d', len(streams), len(preferred_streams))
            show_all_streams = not preferred_streams
            for stream in streams:
                log = dependencies.logger.info if show_all_streams or stream.preference_score > 0 else dependencies.logger.debug
                language_label = stream.language or stream.raw_language or 'unknown'
                title_label = stream.title or '-'
                log(
                    '  #%s %s, %s, %s, title="%s", default=%s, forced=%s',
                    stream.stream_index,
                    language_label,
                    stream.subtitle_type,
                    stream.extension.lstrip('.'),
                    title_label,
                    stream.disposition_default,
                    stream.disposition_forced,
                )
        selected = dependencies.select_preferred_embedded(streams)
        if not selected:
            if test_mode:
                if streams:
                    dependencies.logger.info('Selection: none (no preferred Chinese embedded subtitle)')
            return 'no_preferred_embedded_subtitle' if streams else None
        ambiguous = self._ambiguous_embedded_selection(streams, selected)
        if ambiguous:
            resolved = self._resolve_ambiguous_embedded(
                media_link,
                video_path,
                ambiguous,
                test_mode=test_mode,
            )
            if resolved:
                selected = resolved
            else:
                if test_mode:
                    dependencies.logger.info(
                        'Selection: none (ambiguous embedded: %s)',
                        ', '.join(f'#{stream.stream_index} {stream.language} "{stream.title}"' for stream in ambiguous),
                    )
                return 'needs_review'
        dependencies.logger.info(
            'Selection: embedded #%s (%s, %s, title="%s")',
            selected.stream_index,
            selected.language,
            selected.subtitle_type,
            selected.title or '-',
        )
        return self._apply_embedded_stream(media_link, selected, test_mode=test_mode)

    def _apply_embedded_stream(
        self,
        media_link: dict[str, dependencies.Any],
        selected: dependencies.EmbeddedSubtitleStream,
        test_mode: bool = False,
    ) -> str:
        video_path = self._video_path(media_link)
        source_id = f'{media_link["source_path"]}#stream:{selected.stream_index}'
        target_id = f'{media_link["target_path"]}#stream:{selected.stream_index}'
        metadata = self._subtitle_metadata(media_link, selected.language, selected.subtitle_type, selected.extension.lstrip('.'), 'embedded')
        metadata.update({'stream_index': selected.stream_index, 'codec': selected.codec})

        if test_mode:
            status = 'embedded_extracted'
            reason = 'extract sidecar fallback'
            target_subtitle = dependencies.build_sidecar_path(media_link['target_path'], selected.extension, selected.language, selected.subtitle_type)
            is_mkv = dependencies.os.path.splitext(video_path)[1].lower() == '.mkv'
            can_set_default = (
                dependencies.SET_EMBEDDED_DEFAULT
                and is_mkv
                and dependencies.shutil.which('mkvpropedit')
                and dependencies.shutil.which('mkvmerge')
            )
            if can_set_default:
                status = 'embedded_default_set'
                reason = 'mkvpropedit available'
                target_subtitle = target_id
            elif not dependencies.EXTRACT_EMBEDDED_FALLBACK:
                status = 'needs_review'
                reason = 'no safe write action'
            elif dependencies.SET_EMBEDDED_DEFAULT and is_mkv:
                reason = 'safe default-track mapping unavailable, extracting sidecar fallback'
            elif dependencies.SET_EMBEDDED_DEFAULT:
                reason = 'not an mkv container, extracting sidecar fallback'
            else:
                reason = 'embedded default disabled, extracting sidecar fallback'
            action_label = {
                'embedded_default_set': 'would set embedded subtitle as default',
                'embedded_extracted': 'would extract embedded subtitle to sidecar',
                'needs_review': 'needs review',
            }.get(status, status)
            dependencies.logger.info(
                'Action: %s #%s -> %s (%s)',
                action_label,
                selected.stream_index,
                f'stream:{selected.stream_index}' if target_subtitle == target_id else dependencies.os.path.basename(target_subtitle),
                reason,
            )
            return status

        if dependencies.SET_EMBEDDED_DEFAULT:
            flag, reason = dependencies.set_mkv_default_subtitle(video_path, selected)
            if flag:
                if reason == 'embedded_default_already_set':
                    dependencies.upsert_media_subtitle(
                        dependencies.MEDIA_DB,
                        source_id,
                        target_id,
                        **metadata,
                        status='exists',
                        reason=reason,
                    )
                    dependencies.logger.info('Action: embedded #%s already default (%s)', selected.stream_index, selected.language)
                    return 'exists'
                dependencies.upsert_media_subtitle(
                    dependencies.MEDIA_DB,
                    source_id,
                    target_id,
                    **metadata,
                    status='embedded_default_set',
                    reason=reason,
                )
                dependencies.logger.info('Action: set embedded #%s as default (%s)', selected.stream_index, selected.language)
                return 'embedded_default_set'
            dependencies.logger.warning('Action fallback: default track update failed (%s)', reason)
            if not dependencies.EXTRACT_EMBEDDED_FALLBACK:
                self._record_failed(media_link, {'stream': dependencies.asdict(selected)}, 'embedded_default_set', reason)
                return 'failed'

        if not dependencies.EXTRACT_EMBEDDED_FALLBACK:
            return None

        plain_subtitle = dependencies.os.path.splitext(media_link['target_path'])[0] + selected.extension
        if dependencies.os.path.isfile(plain_subtitle):
            plain_candidate = self._parse_subtitle_candidate(plain_subtitle)
            if plain_candidate.preference_score > 0:
                if test_mode:
                    dependencies.logger.info(
                        'Action: would keep existing Chinese sidecar %s',
                        dependencies.os.path.basename(plain_subtitle),
                    )
                else:
                    dependencies.upsert_media_subtitle(
                        dependencies.MEDIA_DB,
                        plain_subtitle,
                        plain_subtitle,
                        **self._subtitle_metadata(
                            media_link,
                            plain_candidate.language,
                            plain_candidate.subtitle_type,
                            plain_candidate.extension.lstrip('.'),
                            'sidecar',
                        ),
                        status='exists',
                        reason='existing canonical Chinese sidecar; embedded extraction skipped',
                    )
                    dependencies.logger.info(
                        'Action: kept existing Chinese sidecar %s; embedded extraction skipped',
                        dependencies.os.path.basename(plain_subtitle),
                    )
                return 'exists'

        target_subtitle = dependencies.build_sidecar_path(media_link['target_path'], selected.extension, selected.language, selected.subtitle_type)
        flag, reason = dependencies.extract_embedded_subtitle(video_path, selected, target_subtitle)
        if not flag:
            self._record_failed(media_link, {'stream': dependencies.asdict(selected), 'target': target_subtitle}, 'embedded_extract', reason)
            return 'failed'
        self._invalidate_path_cache(target_subtitle)

        dependencies.upsert_media_subtitle(
            dependencies.MEDIA_DB,
            source_id,
            target_subtitle,
            **metadata,
            status='embedded_extracted',
            reason=reason,
        )
        dependencies.logger.info(
            'Action: extracted embedded #%s -> %s',
            selected.stream_index,
            dependencies.os.path.basename(target_subtitle),
        )
        return 'embedded_extracted'

    def _cleanup_redundant_language_sidecars(
        self,
        media_link: dict[str, dependencies.Any],
        *,
        test_mode: bool,
    ) -> None:
        for extension in ('.srt', '.ass', '.ssa', '.vtt'):
            plain_path = dependencies.shorten_sidecar_path(str(media_link.get('target_path') or ''), extension)
            if not dependencies.os.path.isfile(plain_path):
                continue
            plain_fingerprint = self._subtitle_semantic_fingerprint(plain_path)
            if plain_fingerprint is None:
                continue
            for language in ('zh-CN', 'zh-Hant', 'zh', 'zh-CN-bilingual'):
                tagged_path = dependencies.shorten_sidecar_path(str(media_link.get('target_path') or ''), f'.{language}{extension}')
                if not dependencies.os.path.isfile(tagged_path):
                    continue
                if self._subtitle_semantic_fingerprint(tagged_path) != plain_fingerprint:
                    continue
                if not test_mode:
                    try:
                        self._remove_file(tagged_path)
                    except OSError as exc:
                        dependencies.logger.warning(
                            'Action: failed to remove redundant sidecar %s (%s)',
                            dependencies.os.path.basename(tagged_path),
                            exc,
                        )
                        continue
                dependencies.logger.info(
                    'Action: %s redundant sidecar %s',
                    'would remove' if test_mode else 'removed',
                    dependencies.os.path.basename(tagged_path),
                )

    def _subtitle_semantic_fingerprint(self, path: str) -> tuple[tuple[dependencies.Any, ...], ...] | None:
        try:
            events = dependencies.parse_text_subtitle(path)
        except dependencies.SubtitleTranslationError:
            return None
        return tuple(
            (
                round(event.start_seconds, 2),
                round(event.end_seconds, 2),
                dependencies.re.sub(r'\s+', ' ', event.source_text).strip(),
            )
            for event in events
        )

    def _video_path(self, media_link: dict[str, dependencies.Any]) -> str | None:
        target_path = media_link.get('target_path')
        if dependencies.os.path.isfile(target_path or ''):
            return target_path
        return media_link.get('source_path')


    def _ambiguous_embedded_selection(
        self,
        streams: list[dependencies.EmbeddedSubtitleStream],
        selected: dependencies.EmbeddedSubtitleStream,
    ) -> list[dependencies.EmbeddedSubtitleStream]:
        if selected.preference_score <= 0:
            return []
        same_priority = [
            stream
            for stream in streams
            if stream.preference_score == selected.preference_score
        ]
        # Generic "zh" metadata cannot distinguish simplified from traditional
        # Chinese. Analyze every equivalent Chinese track before considering
        # the existing default flag.
        if selected.language == 'zh' and len(same_priority) > 1:
            return same_priority
        selected_default_rank = 1 if selected.disposition_default else 0
        tied = [
            stream
            for stream in same_priority
            if (1 if stream.disposition_default else 0) == selected_default_rank
        ]
        return tied if len(tied) > 1 else []

    def _resolve_ambiguous_embedded(
        self,
        media_link: dict[str, dependencies.Any],
        video_path: str,
        streams: list[dependencies.EmbeddedSubtitleStream],
        test_mode: bool = False,
    ) -> dependencies.EmbeddedSubtitleStream | None:
        analyzed: list[tuple[dependencies.EmbeddedSubtitleStream, list[str], dict[str, dependencies.Any]]] = []
        for stream in streams:
            sample = dependencies.sample_embedded_subtitle(video_path, stream, limit=720)
            profile = dependencies.analyze_subtitle_sample(sample)
            language = profile.get('language') or dependencies.detect_language(
                ' '.join(str(item or '') for item in (stream.raw_language, stream.title)),
                sample,
            )
            subtitle_type = (
                'bilingual'
                if profile.get('subtitle_type') == 'bilingual'
                else stream.subtitle_type
            )
            updated = dependencies.replace(stream, language=language, subtitle_type=subtitle_type)
            analyzed.append((updated, sample, profile))
            if test_mode:
                dependencies.logger.info(
                    '  Analysis #%s: %s, %s, confidence=%.2f, quality=%.1f, events=%d, span=%.0fs',
                    stream.stream_index,
                    language or 'unknown',
                    subtitle_type,
                    float(profile.get('confidence') or 0.0),
                    float(profile.get('quality_score') or 0.0),
                    int(profile.get('subtitle_events') or 0),
                    float(profile.get('span_seconds') or 0.0),
                )
        ranked = sorted(
            analyzed,
            key=lambda item: self._embedded_analysis_rank(item[0], item[2]),
            reverse=True,
        )
        if ranked:
            top_stream, _, top_profile = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None
            language_is_clear = float(top_profile.get('confidence') or 0.0) >= 0.7
            preference_wins = (
                runner_up is None
                or top_stream.preference_score > runner_up[0].preference_score
            )
            quality_wins = (
                runner_up is None
                or float(top_profile.get('quality_score') or 0.0)
                >= float(runner_up[2].get('quality_score') or 0.0) + 8.0
            )
            if language_is_clear and (preference_wins or quality_wins):
                dependencies.logger.info(
                    'Resolution: local analysis selected #%s (%s)',
                    top_stream.stream_index,
                    self._embedded_selection_reason(
                        top_stream,
                        top_profile,
                        runner_up[0] if runner_up else None,
                        runner_up[2] if runner_up else None,
                    ),
                )
                return top_stream

        ai_selected = self._classify_embedded_with_codex(media_link, analyzed)
        if ai_selected:
            dependencies.logger.info('Resolution: Codex selected #%s', ai_selected.stream_index)
            return ai_selected

        if ranked:
            selected, _, selected_profile = ranked[0]
            runner_up = ranked[1] if len(ranked) > 1 else None
            dependencies.logger.info(
                'Resolution: deterministic fallback selected #%s (%s)',
                selected.stream_index,
                self._embedded_selection_reason(
                    selected,
                    selected_profile,
                    runner_up[0] if runner_up else None,
                    runner_up[2] if runner_up else None,
                ),
            )
            return selected
        return None

    def _embedded_analysis_rank(
        self,
        stream: dependencies.EmbeddedSubtitleStream,
        profile: dict[str, dependencies.Any],
    ) -> tuple[int, float, int, int]:
        return (
            stream.preference_score,
            float(profile.get('quality_score') or 0.0),
            1 if stream.disposition_default else 0,
            -stream.subtitle_ordinal,
        )

    def _embedded_selection_reason(
        self,
        selected: dependencies.EmbeddedSubtitleStream,
        selected_profile: dict[str, dependencies.Any],
        runner_up: dependencies.EmbeddedSubtitleStream | None,
        runner_up_profile: dict[str, dependencies.Any] | None,
    ) -> str:
        if runner_up is None:
            return 'only viable candidate'

        if selected.preference_score != runner_up.preference_score:
            return (
                f'language priority: #{selected.stream_index} '
                f'{selected.language or "unknown"}={selected.preference_score} > '
                f'#{runner_up.stream_index} '
                f'{runner_up.language or "unknown"}={runner_up.preference_score}'
            )

        selected_quality = float(selected_profile.get('quality_score') or 0.0)
        runner_up_quality = float((runner_up_profile or {}).get('quality_score') or 0.0)
        if selected_quality != runner_up_quality:
            return (
                f'quality score: #{selected.stream_index} {selected_quality:.1f} > '
                f'#{runner_up.stream_index} {runner_up_quality:.1f}'
            )

        if selected.disposition_default != runner_up.disposition_default:
            return (
                f'default flag: #{selected.stream_index} default=true > '
                f'#{runner_up.stream_index} default=false'
            )

        return (
            f'stable track order: #{selected.stream_index} ordinal={selected.subtitle_ordinal} < '
            f'#{runner_up.stream_index} ordinal={runner_up.subtitle_ordinal}'
        )

    def _classify_embedded_with_codex(
        self,
        media_link: dict[str, dependencies.Any],
        analyzed: list[tuple[dependencies.EmbeddedSubtitleStream, list[str], dict[str, dependencies.Any]]],
    ) -> dependencies.EmbeddedSubtitleStream | None:
        if not analyzed:
            return None
        if self.disable_agent:
            dependencies.logger.warning('Resolution: Codex skipped (agent disabled)')
            return None
        source_ids = {
            f'{media_link.get("source_path")}#stream:{stream.stream_index}'
            for stream, _, _ in analyzed
        }
        payload = {
            'mode': 'subtitle_classify',
            'candidate_videos': [self._candidate_video_payload(media_link)],
            'embedded_streams': [
                {
                    'source_subtitle_path': f'{media_link.get("source_path")}#stream:{stream.stream_index}',
                    'stream_index': stream.stream_index,
                    'codec': stream.codec,
                    'format': stream.extension.lstrip('.'),
                    'language': stream.language,
                    'raw_language': stream.raw_language,
                    'title': stream.title,
                    'subtitle_type': stream.subtitle_type,
                    'disposition_default': stream.disposition_default,
                    'disposition_forced': stream.disposition_forced,
                    'content_profile': profile,
                    'subtitle_sample': sample[:120],
                }
                for stream, sample, profile in analyzed
            ],
        }
        try:
            if self.client is None:
                from media_mcp.subtitle.clients.codex import CodexSubtitleClient

                self.client = CodexSubtitleClient()
            result = self._external_call(lambda:self.client.classify_subtitle(payload,user='phantom_slayer_subtitle'))
        except Exception as exc:
            dependencies.logger.warning('Resolution: Codex failed (%s)', exc)
            return None

        normalized = dependencies.normalize_subtitle_result(
            result,
            {
                'matched_video_target_path': media_link.get('target_path'),
                'source_type': 'embedded',
            },
        )
        ok, reason = dependencies.validate_subtitle_result(
            normalized,
            {media_link.get('target_path')},
            candidate_sources=source_ids,
            expected_media=media_link,
            expected_source_type='embedded',
            allowed_stream_indices={stream.stream_index for stream, _, _ in analyzed},
            low_confidence_threshold=dependencies.LOW_CONFIDENCE_THRESHOLD,
        )
        if not ok:
            dependencies.logger.warning('Resolution: Codex rejected (%s)', reason)
            return None

        selected_index = int(normalized.get('stream_index'))
        for stream, _, _ in analyzed:
            if stream.stream_index == selected_index:
                return dependencies.replace(
                    stream,
                    language=normalized.get('language') or stream.language,
                    subtitle_type=normalized.get('subtitle_type') or stream.subtitle_type,
                )
        return None

    def _select_embedded_translation_source(self, streams: list[dependencies.EmbeddedSubtitleStream]) -> dependencies.EmbeddedSubtitleStream | None:
        return self._select_embedded_translation_source_for_media({}, streams)

    def _select_embedded_translation_source_for_media(
        self,
        media_link: dict[str, dependencies.Any],
        streams: list[dependencies.EmbeddedSubtitleStream],
        language_preferences: tuple[str, ...] | None = None,
        exclude_stream_indexes: set[int] | None = None,
    ) -> dependencies.EmbeddedSubtitleStream | None:
        if language_preferences is None:
            language_preferences = self._translation_source_language_preferences(media_link) if media_link else (None,)
        excluded = exclude_stream_indexes or set()
        for preferred_language in language_preferences or (None,):
            candidates: list[tuple[int, dependencies.EmbeddedSubtitleStream]] = []
            for stream in streams:
                if stream.stream_index in excluded:
                    continue
                if stream.extension not in {'.srt', '.ass', '.ssa', '.vtt'}:
                    continue
                raw_language = (stream.raw_language or '').lower()
                title = (stream.title or '').lower()
                if stream.language in dependencies.CHINESE_LANGUAGES:
                    continue
                if raw_language in {'chi', 'zho', 'zh', 'chs', 'cht'} or 'chinese' in title:
                    continue
                stream_language = self._normalize_language_code(stream.language or stream.raw_language)
                if preferred_language and stream_language != preferred_language:
                    continue
                if stream.subtitle_type in {'forced', 'commentary'}:
                    continue
                score = 50
                if stream.subtitle_type == 'normal':
                    score += 20
                if stream.subtitle_type == 'sdh':
                    score -= 10
                if stream.disposition_default:
                    score += 5
                if stream.language:
                    score += 10
                if preferred_language is None:
                    score -= 15
                candidates.append((score, stream))
            if candidates:
                candidates.sort(key=lambda item: (item[0], -item[1].subtitle_ordinal), reverse=True)
                return candidates[0][1]
        return None

    def _prepare_embedded_text_translation_source(
        self,
        media_link: dict[str, dependencies.Any],
        video_path: str | None,
        stream: dependencies.EmbeddedSubtitleStream,
        *,
        stage: str,
        preferred_language: str | None,
    ) -> str | None:
        source_path = dependencies.shorten_sidecar_path(
            media_link['target_path'],
            f'.subtitle-translation-source-{stream.stream_index}{stream.extension}',
        )
        flag, reason = dependencies.extract_embedded_subtitle(video_path, stream, source_path)
        if not flag:
            try:
                if dependencies.os.path.exists(source_path):
                    self._remove_file(source_path)
            except OSError:
                pass
            dependencies.logger.info(
                '%s: embedded text source rejected language=%s stream=#%s reason=%s',
                stage,
                preferred_language or 'any',
                stream.stream_index,
                self._redact_sensitive_text(reason),
            )
            return None
        self._invalidate_path_cache(source_path)
        try:
            events = dependencies.parse_text_subtitle(source_path)
            dependencies.validate_translation_events(
                events,
                max_events=dependencies.MAX_TRANSLATION_EVENTS,
                warn_events=dependencies.WARN_TRANSLATION_EVENTS,
                max_events_per_minute=dependencies.MAX_EVENTS_PER_MINUTE,
                warn_events_per_minute=dependencies.WARN_EVENTS_PER_MINUTE,
            )
        except Exception as exc:
            try:
                if dependencies.os.path.exists(source_path):
                    self._remove_file(source_path)
            except OSError:
                pass
            dependencies.logger.info(
                '%s: embedded text source rejected language=%s stream=#%s reason=%s',
                stage,
                preferred_language or 'any',
                stream.stream_index,
                self._redact_sensitive_text(exc),
            )
            return None
        return source_path

    def _select_embedded_ocr_translation_source_for_media(
        self,
        media_link: dict[str, dependencies.Any],
        streams: list[dependencies.EmbeddedSubtitleStream],
        language_preferences: tuple[str, ...] | None = None,
    ) -> dependencies.EmbeddedSubtitleStream | None:
        if language_preferences is None:
            language_preferences = self._translation_source_language_preferences(media_link) if media_link else (None,)
        for preferred_language in language_preferences or (None,):
            candidates: list[tuple[int, dependencies.EmbeddedSubtitleStream]] = []
            for stream in streams:
                if not dependencies.is_ocr_supported_stream(stream):
                    continue
                raw_language = (stream.raw_language or '').lower()
                title = (stream.title or '').lower()
                if stream.language in dependencies.CHINESE_LANGUAGES:
                    continue
                if raw_language in {'chi', 'zho', 'zh', 'chs', 'cht'} or 'chinese' in title:
                    continue
                stream_language = self._normalize_language_code(stream.language or stream.raw_language)
                if preferred_language and stream_language != preferred_language:
                    continue
                if stream.subtitle_type in {'forced', 'commentary'}:
                    continue
                score = 45
                if stream.subtitle_type == 'normal':
                    score += 20
                if stream.subtitle_type == 'sdh':
                    score -= 10
                if stream.disposition_default:
                    score += 5
                if stream.language:
                    score += 10
                if preferred_language is None:
                    score -= 15
                candidates.append((score, stream))
            if candidates:
                candidates.sort(key=lambda item: (item[0], -item[1].subtitle_ordinal), reverse=True)
                return candidates[0][1]
        return None

    def _embedded_translation_rejection_summary(
        self,
        streams: list[dependencies.EmbeddedSubtitleStream],
        preferred_language: str | None,
    ) -> str:
        counts: dict[str, int] = {}
        for stream in streams:
            reason = None
            if stream.extension not in {'.srt', '.ass', '.ssa', '.vtt'}:
                reason = f'non-text codec {stream.codec or stream.extension}'
            else:
                raw_language = (stream.raw_language or '').lower()
                title = (stream.title or '').lower()
                if stream.language in dependencies.CHINESE_LANGUAGES:
                    reason = 'Chinese subtitle'
                elif raw_language in {'chi', 'zho', 'zh', 'chs', 'cht'} or 'chinese' in title:
                    reason = 'Chinese metadata'
                else:
                    stream_language = self._normalize_language_code(stream.language or stream.raw_language)
                    if preferred_language and stream_language != preferred_language:
                        reason = f'language mismatch:{stream_language or "unknown"}'
                    elif stream.subtitle_type in {'forced', 'commentary'}:
                        reason = f'{stream.subtitle_type} subtitle'
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return '-'
        return ', '.join(
            f'{reason}:{count}'
            for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        )

    def _embedded_ocr_rejection_summary(
        self,
        streams: list[dependencies.EmbeddedSubtitleStream],
        preferred_language: str | None,
    ) -> str:
        counts: dict[str, int] = {}
        for stream in streams:
            reason = None
            if not dependencies.is_ocr_supported_stream(stream):
                reason = f'unsupported OCR codec {stream.codec or stream.extension}'
            else:
                raw_language = (stream.raw_language or '').lower()
                title = (stream.title or '').lower()
                if stream.language in dependencies.CHINESE_LANGUAGES:
                    reason = 'Chinese subtitle'
                elif raw_language in {'chi', 'zho', 'zh', 'chs', 'cht'} or 'chinese' in title:
                    reason = 'Chinese metadata'
                else:
                    stream_language = self._normalize_language_code(stream.language or stream.raw_language)
                    if preferred_language and stream_language != preferred_language:
                        reason = f'language mismatch:{stream_language or "unknown"}'
                    elif stream.subtitle_type in {'forced', 'commentary'}:
                        reason = f'{stream.subtitle_type} subtitle'
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return '-'
        return ', '.join(
            f'{reason}:{count}'
            for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        )

    def _prepare_embedded_ocr_translation_source(
        self,
        media_link: dict[str, dependencies.Any],
        video_path: str | None,
        stream: dependencies.EmbeddedSubtitleStream,
        *,
        stage: str,
        preferred_language: str | None,
    ) -> tuple[str | None, str]:
        source_path = dependencies.shorten_sidecar_path(
            media_link['target_path'],
            f'.subtitle-translation-source-{stream.stream_index}.ocr.srt',
        )
        ok, reason = dependencies.ocr_embedded_pgs_to_srt(
            video_path,
            stream,
            source_path,
            language=preferred_language or stream.language or stream.raw_language,
        )
        if not ok:
            try:
                if dependencies.os.path.exists(source_path):
                    self._remove_file(source_path)
            except OSError:
                pass
            dependencies.logger.info(
                '%s: embedded OCR miss language=%s stream=#%s reason=%s',
                stage,
                preferred_language or 'any',
                stream.stream_index,
                self._redact_sensitive_text(reason),
            )
            return None, reason

        try:
            events = dependencies.parse_text_subtitle(source_path)
            dependencies.validate_translation_events(
                events,
                max_events=dependencies.MAX_TRANSLATION_EVENTS,
                warn_events=dependencies.WARN_TRANSLATION_EVENTS,
                max_events_per_minute=dependencies.MAX_EVENTS_PER_MINUTE,
                warn_events_per_minute=dependencies.WARN_EVENTS_PER_MINUTE,
            )
        except Exception as exc:
            try:
                if dependencies.os.path.exists(source_path):
                    self._remove_file(source_path)
            except OSError:
                pass
            reason = f'embedded_ocr_invalid_output: {exc}'
            dependencies.logger.info(
                '%s: embedded OCR miss language=%s stream=#%s reason=%s',
                stage,
                preferred_language or 'any',
                stream.stream_index,
                self._redact_sensitive_text(reason),
            )
            return None, reason

        self._invalidate_path_cache(source_path)
        dependencies.logger.info(
            '%s: embedded OCR ready stream=#%s target=%s reason=%s',
            stage,
            stream.stream_index,
            dependencies.os.path.basename(source_path),
            reason,
        )
        return source_path, reason

    def _select_sidecar_translation_source(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.SubtitleCandidate],
        language_preferences: tuple[str, ...] | None = None,
    ) -> dependencies.SubtitleCandidate | None:
        source_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('source_path') or ''))[0].lower()
        target_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('target_path') or ''))[0].lower()
        if language_preferences is None:
            language_preferences = self._translation_source_language_preferences(media_link) if media_link else (None,)
        for preferred_language in language_preferences or (None,):
            ranked: list[tuple[int, dependencies.SubtitleCandidate]] = []
            for candidate in candidates:
                if candidate.generated_by_agent:
                    continue
                if candidate.language in dependencies.CHINESE_LANGUAGES:
                    continue
                if candidate.subtitle_type in {'forced', 'commentary'}:
                    continue
                candidate_language = self._normalize_language_code(candidate.language)
                language_unknown = candidate_language is None
                if preferred_language and candidate_language != preferred_language:
                    continue
                score = 20
                if candidate.subtitle_type == 'normal':
                    score += 20
                elif candidate.subtitle_type == 'sdh':
                    score -= 10
                if candidate.language:
                    score += 10
                elif preferred_language == dependencies.TRANSLATION_FALLBACK_LANGUAGE or preferred_language is None:
                    score += 5
                context_stems = self._sidecar_context_stems(candidate.path)
                if media_link.get('media_type') == 'tv':
                    expected_episode = self._optional_int(media_link.get('episode'))
                    expected_season = self._optional_int(media_link.get('season'))
                    candidate_season, candidate_episode = self._sidecar_episode_markers(candidate)
                    if candidate_episode is None or candidate_episode != expected_episode:
                        continue
                    if candidate_season is not None and expected_season is not None and candidate_season != expected_season:
                        continue
                    score += 50
                else:
                    score += 20
                stem_matches = bool(
                    any(
                        media_stem
                        and (
                            context_stem == media_stem
                            or context_stem.startswith(f'{media_stem}.')
                            or media_stem in context_stem
                        )
                        for media_stem in (source_stem, target_stem)
                        for context_stem in context_stems
                    )
                )
                if not stem_matches:
                    continue
                if language_unknown:
                    score -= 5
                if preferred_language is None:
                    score -= 15
                score += 30
                ranked.append((score, candidate))
            if ranked:
                ranked.sort(key=lambda item: (item[0], item[1].path), reverse=True)
                return ranked[0][1]
        return None

    def _translation_source_language_preferences(self, media_link: dict[str, dependencies.Any]) -> tuple[str, ...]:
        preferred_language = self._primary_translation_language(media_link)
        preferences: list[str] = []
        if preferred_language and preferred_language not in dependencies.CHINESE_LANGUAGES:
            preferences.append(preferred_language)
        if dependencies.TRANSLATION_FALLBACK_LANGUAGE not in preferences:
            preferences.append(dependencies.TRANSLATION_FALLBACK_LANGUAGE)
        return tuple(preferences)

    def _primary_translation_language(self, media_link: dict[str, dependencies.Any]) -> str | None:
        return self._origin_country_language(media_link) or self._media_original_language(media_link)

    def _translation_stage_for_language(
        self,
        media_link: dict[str, dependencies.Any],
        language: str | None,
    ) -> tuple[int, str]:
        primary_language = self._primary_translation_language(media_link)
        if language and primary_language and language == primary_language and language not in dependencies.CHINESE_LANGUAGES:
            return 4, 'AI source origin-language'
        if language == dependencies.TRANSLATION_FALLBACK_LANGUAGE:
            return 5, 'AI source English'
        return 6, 'AI source any-foreign'

    def _origin_country_language(self, media_link: dict[str, dependencies.Any]) -> str | None:
        value = media_link.get('origin_country') or self._media_agent_field(media_link, 'origin_country')
        if not value:
            return None
        countries: list[str]
        if isinstance(value, (list, tuple)):
            countries = [str(item or '').strip() for item in value]
        else:
            countries = dependencies.re.split(r'[,/| ]+', str(value or '').strip())
        for country in countries:
            if not country:
                continue
            language = dependencies.COUNTRY_LANGUAGE_ALIASES.get(country.upper())
            if language:
                return language
        return None

    def _online_translation_candidate_score(
        self,
        media_link: dict[str, dependencies.Any],
        candidate: dependencies.OnlineSubtitleCandidate,
        expected_language: str | None,
    ) -> tuple[float, str]:
        media_type = str(media_link.get('media_type') or 'movie')
        expected_tmdb = self._optional_int(media_link.get('media_tmdb_id'))
        expected_season = self._optional_int(media_link.get('season'))
        expected_episode = self._optional_int(media_link.get('episode'))
        candidate_language = self._normalize_language_code(candidate.language)
        if expected_language and candidate_language != expected_language:
            return 0.0, 'language mismatch'
        if candidate_language in dependencies.CHINESE_LANGUAGES:
            return 0.0, 'translation source is Chinese'
        if candidate.media_type and candidate.media_type != media_type:
            return 0.0, 'media type mismatch'
        if candidate.subtitle_type in {'forced', 'commentary'}:
            return 0.0, f'{candidate.subtitle_type} subtitle'

        score = 80.0 if expected_language != dependencies.TRANSLATION_FALLBACK_LANGUAGE else 60.0
        if expected_language is None:
            score = 45.0
        identity = 'title fallback'
        if media_type == 'tv':
            if expected_season is not None and candidate.season != expected_season:
                return 0.0, 'season mismatch'
            if expected_episode is not None and candidate.episode != expected_episode:
                return 0.0, 'episode mismatch'
            if expected_tmdb is not None and candidate.parent_tmdb_id is not None:
                if candidate.parent_tmdb_id != expected_tmdb:
                    return 0.0, 'parent TMDB mismatch'
                score += 50
                identity = 'parent TMDB + season/episode'
            else:
                score += 30
                identity = 'season/episode'
        elif expected_tmdb is not None and candidate.tmdb_id is not None:
            if candidate.tmdb_id != expected_tmdb:
                return 0.0, 'TMDB mismatch'
            score += 50
            identity = 'TMDB'
        else:
            score += 20

        if candidate.subtitle_type == 'normal':
            score += 20
        elif candidate.subtitle_type == 'sdh':
            score -= 10
        if candidate.trusted:
            score += 10
        if candidate.machine_translated:
            score -= 15
        if expected_language is None:
            identity = f'{identity}; any foreign language fallback'
        score += min(15.0, dependencies.math.log10(max(1, candidate.download_count)) * 4)
        score += min(5.0, max(0.0, candidate.rating) / 2)
        return score, identity

    def _rank_online_translation_candidates(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.OnlineSubtitleCandidate],
        expected_language: str | None,
    ) -> list[tuple[float, dependencies.OnlineSubtitleCandidate, str]]:
        ranked = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate.provider, str(candidate.file_id))
            if key in seen:
                continue
            seen.add(key)
            score, reason = self._online_translation_candidate_score(
                media_link,
                candidate,
                expected_language,
            )
            if score > 0:
                ranked.append((score, candidate, reason))
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1].download_count,
                item[1].rating,
                str(item[1].file_id),
            ),
            reverse=True,
        )
        return ranked

    def _online_translation_rejection_summary(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.OnlineSubtitleCandidate],
        expected_language: str | None,
    ) -> str:
        counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate.provider, str(candidate.file_id))
            if key in seen:
                continue
            seen.add(key)
            score, reason = self._online_translation_candidate_score(
                media_link,
                candidate,
                expected_language,
            )
            if score <= 0:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return '-'
        return ', '.join(
            f'{reason}:{count}'
            for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
        )

    def _download_online_translation_source(self, media_link: dict[str, dependencies.Any], target_subtitle: str, test_mode: bool=False, language_preferences: tuple[str, ...] | None=None) -> dict[str, dependencies.Any] | None:
        return online_subtitles._download_online_translation_source(self, media_link, target_subtitle, test_mode, language_preferences)

    def _process_text_translation(self, media_link: dict[str, dependencies.Any], sidecars: list[dependencies.SubtitleCandidate], test_mode: bool=False, allow_online_source: bool=True, source_kinds: tuple[str, ...]=('sidecar', 'embedded', 'online'), reuse_existing_output: bool=True) -> str | None:
        return translation._process_text_translation(self, media_link, sidecars, test_mode, allow_online_source, source_kinds, reuse_existing_output)

    def _process_audio_transcription(self, media_link: dict[str, dependencies.Any], test_mode: bool=False) -> str | None:
        return translation._process_audio_transcription(self, media_link, test_mode)

    def _translated_target_path(self, media_link: dict[str, dependencies.Any]) -> str:
        plain_target = dependencies.shorten_sidecar_path(media_link['target_path'], '.ass')
        if dependencies.os.path.exists(plain_target):
            try:
                if not self._parse_subtitle_candidate(plain_target).generated_by_agent:
                    return dependencies.shorten_sidecar_path(media_link['target_path'], '.zh-CN-bilingual.ass')
            except Exception:
                return dependencies.shorten_sidecar_path(media_link['target_path'], '.zh-CN-bilingual.ass')
        return plain_target

    def _remove_mislinked_generated_subtitle(
        self,
        media_link: dict[str, dependencies.Any],
        target_subtitle: str,
    ) -> bool:
        try:
            records = dependencies.list_media_subtitles_by_video(dependencies.MEDIA_DB, media_link['target_path'])
        except Exception as exc:
            dependencies.logger.warning('Subtitle integrity check unavailable (%s)', exc)
            return False
        target_stem = dependencies.os.path.splitext(dependencies.os.path.basename(target_subtitle))[0]
        for record in records:
            if record.get('status') != 'linked':
                continue
            source_path = str(record.get('source_subtitle_path') or '')
            if not source_path or not dependencies.os.path.isfile(source_path):
                continue
            source_stem = dependencies.os.path.splitext(dependencies.os.path.basename(source_path))[0]
            if source_stem == target_stem:
                continue
            try:
                same_file = dependencies.os.path.samefile(source_path, target_subtitle)
            except OSError:
                continue
            if not same_file or not self._parse_subtitle_candidate(source_path).generated_by_agent:
                continue
            try:
                self._remove_file(target_subtitle)
            except OSError as exc:
                dependencies.logger.warning(
                    'Action: failed to remove mislinked generated subtitle %s (%s)',
                    dependencies.os.path.basename(target_subtitle),
                    exc,
                )
                return False
            dependencies.logger.warning(
                'Action: removed mislinked generated subtitle %s (source=%s)',
                dependencies.os.path.basename(target_subtitle),
                dependencies.os.path.basename(source_path),
            )
            return True
        return False

    def _legacy_translated_target_path(self, media_link: dict[str, dependencies.Any]) -> str:
        return dependencies.shorten_sidecar_path(media_link['target_path'], '.zh-CN-bilingual.ass')

    def _cleanup_legacy_translation_sources(self, media_link: dict[str, dependencies.Any]) -> None:
        # Names do not establish ownership. Temporary extraction/download files
        # are removed by their creating operation's finally block. Existing
        # sidecars (including the active bilingual output) must be preserved.
        return

    def _translation_media_context(self, media_link: dict[str, dependencies.Any]) -> dict[str, dependencies.Any]:
        return {
            'kind': media_link.get('media_type'),
            'tmdb_id': media_link.get('media_tmdb_id'),
            'title': media_link.get('base_title') or media_link.get('media_name'),
            'alternate_title': media_link.get('alt_name'),
            'original_language': self._media_original_language(media_link),
            'origin_country': media_link.get('origin_country') or self._media_agent_field(media_link, 'origin_country'),
            'year': media_link.get('year'),
            'season': media_link.get('season'),
            'episode': media_link.get('episode'),
        }

    def _media_original_language(self, media_link: dict[str, dependencies.Any]) -> str | None:
        return self._normalize_language_code(
            media_link.get('original_language')
            or self._media_agent_field(media_link, 'original_language')
        )

    def _media_agent_field(self, media_link: dict[str, dependencies.Any], field: str) -> dependencies.Any:
        payload = media_link.get('agent_result_json')
        if not payload:
            return None
        try:
            data = dependencies.json.loads(payload) if isinstance(payload, str) else payload
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        for container in (
            data,
            data.get('raw_result'),
            data.get('normalized_result'),
            data.get('series_result'),
            data.get('episode_entry'),
        ):
            if isinstance(container, dict) and container.get(field):
                return container.get(field)
        return None

    def _normalize_language_code(self, value: dependencies.Any) -> str | None:
        if value is None:
            return None
        language = str(value).strip().replace('_', '-')
        if not language:
            return None
        lowered = language.lower()
        normalized = dependencies.LANGUAGE_ALIASES.get(lowered, lowered)
        normalized_lower = normalized.lower()
        if normalized_lower.startswith('zh-cn') or normalized_lower.startswith('zh-hans'):
            return 'zh-CN'
        if (
            normalized_lower.startswith('zh-tw')
            or normalized_lower.startswith('zh-hk')
            or normalized_lower.startswith('zh-hant')
        ):
            return 'zh-Hant'
        return normalized.split('-', 1)[0] if '-' in normalized else normalized

    def _normalize_translation_guide(self, guide: dependencies.Any) -> dict[str, dependencies.Any] | None:
        if not isinstance(guide, dict) or not guide.get('success'):
            return None
        characters = guide.get('characters')
        if not isinstance(characters, list):
            characters = []
        glossary = guide.get('glossary')
        if not isinstance(glossary, list):
            glossary = []
        normalized = {
            'overview': str(guide.get('overview') or '')[:800],
            'tone': str(guide.get('tone') or '')[:400],
            'characters': [
                {
                    'source': str(item.get('source') or '')[:120],
                    'zh': str(item.get('zh') or '')[:120],
                    'note': str(item.get('note') or '')[:240],
                }
                for item in characters[:30]
                if isinstance(item, dict) and (item.get('source') or item.get('zh'))
            ],
            'glossary': [
                {
                    'source': str(item.get('source') or '')[:160],
                    'zh': str(item.get('zh') or '')[:160],
                }
                for item in glossary[:50]
                if isinstance(item, dict) and (item.get('source') or item.get('zh'))
            ],
        }
        return normalized

    def _display_missing_reason(self, reason: str) -> str:
        return {
            'no_preferred_subtitle': 'no preferred Chinese subtitle; next phase: external subtitle or translation',
            'no_preferred_embedded_subtitle': 'no preferred Chinese embedded subtitle; next phase: external subtitle or translation',
            'opensubtitle_disabled_no_local_chinese_subtitle': (
                'no local Chinese subtitle; online providers and AI processing disabled'
            ),
        }.get(reason, reason)

    def _select_sidecar(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.SubtitleCandidate],
        test_mode: bool = False,
    ) -> tuple[dependencies.SubtitleCandidate | None, str | None]:
        scored: list[tuple[int, dependencies.SubtitleCandidate]] = []
        for candidate in candidates:
            if candidate.generated_by_agent:
                continue
            score = self._sidecar_match_score(media_link, candidate)
            if test_mode:
                dependencies.logger.debug(
                    'Score: %s=%d (%s, %s, season=%s, episode=%s)',
                    dependencies.os.path.basename(candidate.path),
                    score,
                    candidate.language,
                    candidate.subtitle_type,
                    candidate.season,
                    candidate.episode,
                )
            if score > 0:
                scored.append((score, candidate))
        if not scored:
            if test_mode:
                dependencies.logger.info('Candidates: matching sidecars=0')
            return None, None
        unique_scored: dict[tuple[dependencies.Any, ...], tuple[int, dependencies.SubtitleCandidate]] = {}
        for score, candidate in scored:
            try:
                stat = dependencies.os.stat(candidate.path)
                key = ('inode', stat.st_dev, stat.st_ino)
            except OSError:
                key = ('path', dependencies.os.path.abspath(candidate.path))
            existing = unique_scored.get(key)
            if existing is None or len(candidate.path) < len(existing[1].path):
                unique_scored[key] = (score, candidate)
        scored = list(unique_scored.values())
        scored.sort(key=lambda item: (item[0], item[1].preference_score), reverse=True)
        top_score = scored[0][0]
        top = [item for score, item in scored if score == top_score]
        if len(top) == 1:
            return top[0], None
        if self.disable_agent:
            selected = min(top, key=lambda item: item.path)
            dependencies.logger.warning(
                'Selection: agent disabled; deterministic sidecar selected %s',
                dependencies.os.path.basename(selected.path),
            )
            return selected, None
        if test_mode:
            dependencies.logger.info(
                'Selection: none (ambiguous sidecars: %s)',
                ', '.join(dependencies.os.path.basename(item.path) for item in top),
            )
            return None, 'ambiguous_sidecar_subtitles'

        ai_choice, review_reason = self._classify_sidecar_with_codex(media_link, top)
        if ai_choice:
            return ai_choice, None
        return None, review_reason or 'ambiguous_sidecar_subtitles'

    def _sidecar_match_score(self, media_link: dict[str, dependencies.Any], candidate: dependencies.SubtitleCandidate) -> int:
        if candidate.preference_score <= 0 or candidate.generated_by_agent:
            return 0
        score = candidate.preference_score
        source_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('source_path') or ''))[0].lower()
        target_stem = dependencies.os.path.splitext(dependencies.os.path.basename(media_link.get('target_path') or ''))[0].lower()
        context_stems = self._sidecar_context_stems(candidate.path)
        stem_matches = any(
            media_stem and (
                context_stem == media_stem
                or context_stem.startswith(f'{media_stem}.')
            )
            for media_stem in {source_stem, target_stem}
            for context_stem in context_stems
        )
        if not stem_matches:
            return 0

        media_type = media_link.get('media_type')
        if media_type == 'tv':
            season = media_link.get('season')
            episode = media_link.get('episode')
            candidate_season, candidate_episode = self._sidecar_episode_markers(candidate)
            if candidate_episode is None:
                return 0
            if int(candidate_episode) != int(episode or -1):
                return 0
            if candidate_season is not None and season is not None and int(candidate_season) != int(season):
                return 0
            score += 40
        else:
            score += 20

        score += 30
        if candidate.subtitle_type == 'commentary':
            score -= 40
        if candidate.subtitle_type == 'sdh':
            score -= 10
        return max(score, 0)

    def _sidecar_context_stems(self, path: str) -> tuple[str, ...]:
        stems: list[str] = []
        filename = dependencies.os.path.basename(path)
        file_stem, _ = dependencies.os.path.splitext(filename)
        if file_stem:
            stems.append(file_stem.lower())
        current = dependencies.os.path.dirname(path)
        for _ in range(3):
            name = dependencies.os.path.basename(current)
            if not name:
                break
            stems.append(name.lower())
            current = dependencies.os.path.dirname(current)
        return tuple(stems)

    def _sidecar_episode_markers(self, candidate: dependencies.SubtitleCandidate) -> tuple[int | None, int | None]:
        if candidate.episode is not None:
            return candidate.season, candidate.episode
        for stem in self._sidecar_context_stems(candidate.path):
            season, episode = dependencies.parse_episode_markers(stem)
            if episode is not None:
                return season, episode
        return None, None

    def _classify_sidecar_with_codex(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.SubtitleCandidate],
    ) -> tuple[dependencies.SubtitleCandidate | None, str | None]:
        if self.disable_agent:
            dependencies.logger.warning('Selection: Codex skipped (agent disabled)')
            return None, 'agent_disabled'
        payload = {
            'mode': 'subtitle_classify',
            'candidate_videos': [self._candidate_video_payload(media_link)],
            'sidecar_subtitles': [
                {
                    'source_subtitle_path': item.path,
                    'filename': dependencies.os.path.basename(item.path),
                    'extension': item.extension,
                    'language_guess': item.language,
                    'subtitle_type_guess': item.subtitle_type,
                    'season': item.season,
                    'episode': item.episode,
                    'subtitle_sample': item.sample,
                }
                for item in candidates
            ],
        }
        try:
            if self.client is None:
                from media_mcp.subtitle.clients.codex import CodexSubtitleClient

                self.client = CodexSubtitleClient()
            result = self._external_call(lambda:self.client.classify_subtitle(payload,user='phantom_slayer_subtitle'))
        except Exception as exc:
            dependencies.logger.warning('Selection: Codex failed (%s)', exc)
            return None, 'codex_failed'

        candidate_targets = {media_link.get('target_path')}
        candidate_sources = {item.path for item in candidates}
        normalized = dependencies.normalize_subtitle_result(result, {'matched_video_target_path': media_link.get('target_path')})
        ok, reason = dependencies.validate_subtitle_result(
            normalized,
            candidate_targets,
            candidate_sources=candidate_sources,
            expected_media=media_link,
            expected_source_type='sidecar',
            low_confidence_threshold=dependencies.LOW_CONFIDENCE_THRESHOLD,
        )
        if not ok:
            dependencies.logger.warning('Selection: Codex rejected (%s)', reason)
            return None, f'codex_{reason.replace(" ", "_")}'
        source_path = normalized.get('source_subtitle_path')
        for item in candidates:
            if item.path == source_path:
                return item, None
        return None, 'codex_source_not_candidate'

    def _process_online_subtitle(self, media_link: dict[str, dependencies.Any], test_mode: bool=False) -> str | None:
        return online_subtitles._process_online_subtitle(self, media_link, test_mode)

    def _online_search_titles(self, media_link: dict[str, dependencies.Any]) -> tuple[str, ...]:
        values = [
            media_link.get('base_title') or media_link.get('media_name'),
            media_link.get('alt_name'),
            media_link.get('title_guess'),
            media_link.get('filename'),
            dependencies.os.path.basename(str(media_link.get('source_path') or '')),
        ]
        titles: list[str] = []
        seen: set[str] = set()
        for value in values:
            title = dependencies.os.path.splitext(str(value or '').strip())[0].strip()
            if not title:
                continue
            key = dependencies.re.sub(r'\s+', ' ', title).casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
        return tuple(titles)

    def _rank_online_candidates(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.OnlineSubtitleCandidate],
    ) -> list[tuple[float, dependencies.OnlineSubtitleCandidate, str]]:
        ranked = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate.provider, str(candidate.file_id))
            if key in seen:
                continue
            seen.add(key)
            score, reason = self._online_candidate_score(media_link, candidate)
            if score > 0:
                ranked.append((score, candidate, reason))
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1].download_count,
                item[1].rating,
                str(item[1].file_id),
            ),
            reverse=True,
        )
        return ranked

    def _online_rejection_summary(
        self,
        media_link: dict[str, dependencies.Any],
        candidates: list[dependencies.OnlineSubtitleCandidate],
    ) -> str:
        counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate.provider, str(candidate.file_id))
            if key in seen:
                continue
            seen.add(key)
            score, reason = self._online_candidate_score(media_link, candidate)
            if score <= 0:
                counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return '-'
        return ', '.join(
            f'{reason}:{count}'
            for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
        )

    def _online_candidate_score(
        self,
        media_link: dict[str, dependencies.Any],
        candidate: dependencies.OnlineSubtitleCandidate,
    ) -> tuple[float, str]:
        media_type = str(media_link.get('media_type') or 'movie')
        expected_tmdb = self._optional_int(media_link.get('media_tmdb_id'))
        expected_season = self._optional_int(media_link.get('season'))
        expected_episode = self._optional_int(media_link.get('episode'))

        if candidate.media_type and candidate.media_type != media_type:
            return 0.0, 'media type mismatch'
        score = {
            'zh-CN-bilingual': 100.0,
            'zh-CN': 90.0,
            'zh-Hant': 70.0,
            'zh': 60.0,
        }.get(candidate.language, 0.0)
        if score <= 0:
            return 0.0, 'unsupported language'

        identity = 'title fallback'
        if media_type == 'tv':
            if not self._online_candidate_title_compatible(media_link, candidate):
                return 0.0, 'title mismatch'
            explicit_mismatch = self._online_candidate_explicit_episode_mismatch(media_link, candidate)
            if explicit_mismatch:
                return 0.0, explicit_mismatch.split(':', 1)[0]
            explicit_episode_match = self._online_candidate_has_explicit_episode_match(media_link, candidate)
            candidate_season = self._optional_int(candidate.season)
            candidate_episode = self._optional_int(candidate.episode)
            candidate_parent_tmdb = self._optional_int(candidate.parent_tmdb_id)
            if (
                expected_tmdb is not None
                and candidate_parent_tmdb is not None
                and candidate_parent_tmdb != expected_tmdb
            ):
                return 0.0, 'parent TMDB mismatch'
            if expected_season is not None and candidate_season is not None and candidate_season != expected_season:
                return 0.0, 'season mismatch'
            if expected_episode is not None and candidate_episode is not None and candidate_episode != expected_episode:
                return 0.0, 'episode mismatch'
            if explicit_episode_match:
                score += 60
                identity = 'explicit filename episode'
            elif expected_episode is not None and candidate_episode is None:
                return 0.0, 'episode missing'
            elif expected_tmdb is not None and candidate_parent_tmdb is not None:
                score += 50
                identity = 'parent TMDB + season/episode'
            else:
                score += 30
                identity = 'season/episode'
        elif expected_tmdb is not None and candidate.tmdb_id is not None:
            if candidate.tmdb_id != expected_tmdb:
                return 0.0, 'TMDB mismatch'
            score += 50
            identity = 'TMDB'
        else:
            score += 20

        if candidate.subtitle_type == 'normal':
            score += 20
        elif candidate.subtitle_type == 'sdh':
            score -= 10
        elif candidate.subtitle_type == 'forced':
            score -= 50
        if candidate.trusted:
            score += 10
        if candidate.machine_translated:
            score -= 10
        score += min(15.0, dependencies.math.log10(max(1, candidate.download_count)) * 4)
        score += min(5.0, max(0.0, candidate.rating) / 2)
        return score, identity

    def _optional_int(self, value: dependencies.Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _process_sidecar(self, media_link: dict[str, dependencies.Any], candidate: dependencies.SubtitleCandidate, test_mode: bool = False) -> str:
        candidate = self._canonicalize_numbered_sidecar(candidate, test_mode=test_mode)
        if self._is_existing_target_sidecar(media_link, candidate.path):
            target_subtitle = candidate.path
        else:
            target_subtitle = dependencies.build_sidecar_path(
                media_link['target_path'],
                candidate.extension,
                candidate.language,
                candidate.subtitle_type,
            )
        metadata = self._subtitle_metadata(media_link, candidate.language, candidate.subtitle_type, candidate.extension.lstrip('.'), 'sidecar')
        if dependencies.os.path.exists(target_subtitle):
            status, reason = 'exists', 'target subtitle exists'
        elif test_mode:
            status, reason = 'linked', 'dry_run'
        else:
            flag, reason = dependencies.create_hardlink(candidate.path, target_subtitle)
            if flag:
                status = 'linked'
            elif dependencies.ALLOW_COPY_FALLBACK and "跨设备" in str(reason):
                temporary_copy = f"{target_subtitle}.{dependencies.uuid.uuid4().hex}.copy"
                try:
                    dependencies.os.makedirs(dependencies.os.path.dirname(target_subtitle), exist_ok=True)
                    dependencies.shutil.copy2(candidate.path, temporary_copy)
                    dependencies.assert_mutation_lock()
                    dependencies.os.link(temporary_copy,target_subtitle)
                    status, reason = 'copied', reason or 'copy fallback'
                except OSError as exc:
                    self._record_failed(media_link, {'subtitle': candidate.path, 'target': target_subtitle}, 'sidecar_copy', str(exc))
                    return 'failed'
                finally:
                    if dependencies.os.path.lexists(temporary_copy):
                        dependencies.os.unlink(temporary_copy)
            else:
                self._record_failed(media_link, {'subtitle': candidate.path, 'target': target_subtitle}, 'sidecar_link', reason)
                return 'failed'

        if test_mode:
            action_label = {
                'exists': 'would keep existing sidecar',
                'linked': 'would link sidecar',
                'copied': 'would copy sidecar',
            }.get(status, status)
            dependencies.logger.info(
                'Action: %s %s -> %s (%s)',
                action_label,
                dependencies.os.path.basename(candidate.path),
                dependencies.os.path.basename(target_subtitle),
                reason,
            )
        else:
            dependencies.upsert_media_subtitle(
                dependencies.MEDIA_DB,
                candidate.path,
                target_subtitle,
                **metadata,
                status=status,
                reason=reason,
            )
            action_label = {
                'exists': 'kept existing sidecar',
                'linked': 'linked sidecar',
                'copied': 'copied sidecar',
            }.get(status, status)
            dependencies.logger.info(
                'Action: %s %s -> %s',
                action_label,
                dependencies.os.path.basename(candidate.path),
                dependencies.os.path.basename(target_subtitle),
            )
        return status

    def _is_existing_target_sidecar(self, media_link: dict[str, dependencies.Any], subtitle_path: str) -> bool:
        target_path = str(media_link.get('target_path') or '')
        if dependencies.os.path.dirname(dependencies.os.path.abspath(subtitle_path)) != dependencies.os.path.dirname(dependencies.os.path.abspath(target_path)):
            return False
        media_stem = dependencies.os.path.splitext(dependencies.os.path.basename(target_path))[0].lower()
        subtitle_stem = dependencies.os.path.splitext(dependencies.os.path.basename(subtitle_path))[0].lower()
        return subtitle_stem == media_stem or subtitle_stem.startswith(f'{media_stem}.')

    def _canonicalize_numbered_sidecar(
        self,
        candidate: dependencies.SubtitleCandidate,
        *,
        test_mode: bool,
    ) -> dependencies.SubtitleCandidate:
        stem, extension = dependencies.os.path.splitext(candidate.path)
        match = dependencies.re.match(r'^(?P<base>.+)\.(?P<number>\d+)$', stem)
        if not match:
            self._cleanup_numbered_sidecar_duplicates(candidate.path, test_mode=test_mode)
            return candidate
        canonical_path = f'{match.group("base")}{extension}'
        try:
            same_file = dependencies.os.path.isfile(canonical_path) and dependencies.os.path.samefile(candidate.path, canonical_path)
        except OSError:
            same_file = False
        if not same_file:
            return candidate
        self._cleanup_numbered_sidecar_duplicates(canonical_path, test_mode=test_mode)
        return dependencies.replace(candidate, path=canonical_path)

    def _cleanup_numbered_sidecar_duplicates(self, canonical_path: str, *, test_mode: bool) -> None:
        stem, extension = dependencies.os.path.splitext(canonical_path)
        directory = dependencies.os.path.dirname(canonical_path)
        prefix = f'{dependencies.os.path.basename(stem)}.'
        try:
            names = self._listdir_cached(directory)
        except OSError:
            return
        removed = 0
        for name in names:
            if not name.startswith(prefix) or not name.endswith(extension):
                continue
            numbered_stem = dependencies.os.path.splitext(name)[0]
            suffix = numbered_stem[len(dependencies.os.path.basename(stem)) + 1:]
            if not suffix.isdigit():
                continue
            duplicate_path = dependencies.os.path.join(directory, name)
            try:
                if not dependencies.os.path.samefile(canonical_path, duplicate_path):
                    continue
                if not test_mode:
                    self._remove_file(duplicate_path)
                removed += 1
            except OSError:
                continue
        if removed:
            dependencies.logger.info(
                'Action: %s numbered sidecar duplicates count=%d',
                'would remove' if test_mode else 'removed',
                removed,
            )

    def _record_existing_generated(self, media_link, path, *, test_mode=False):
        # Generated markers alone do not prove that dialogue is valid Chinese.
        try:
            with open(path,'rb') as handle:
                dependencies.validate_online_subtitle(handle.read(),dependencies.os.path.basename(path))
        except (OSError,ValueError):
            return self._mark_needs_review(media_link,'existing_subtitle_chinese_content_unverified',test_mode=test_mode)
        if not test_mode:
            candidate=self._parse_subtitle_candidate(path)
            metadata=self._subtitle_metadata(media_link,candidate.language or 'zh-CN',candidate.subtitle_type,
                candidate.extension.lstrip('.'),'translated')
            dependencies.upsert_media_subtitle(dependencies.MEDIA_DB,path,path,**metadata,status='exists',
                reason='existing_generated_subtitle_content_validated')
        return 'exists'

    def _mark_missing(self, media_link: dict[str, dependencies.Any], reason: str, test_mode: bool = False) -> str:
        source_id = f'{media_link.get("source_path")}#subtitle:missing'
        target_id = f'{media_link.get("target_path")}#subtitle:missing'
        metadata = self._subtitle_metadata(media_link, None, None, None, 'missing')
        if test_mode:
            dependencies.logger.debug('Missing subtitle record would be written: %s', reason)
            return 'missing'
        dependencies.upsert_media_subtitle(
            dependencies.MEDIA_DB,
            source_id,
            target_id,
            **metadata,
            status='missing',
            reason=reason,
        )
        dependencies.logger.info('Action: marked missing (%s)', self._display_missing_reason(reason))
        return 'missing'

    def _mark_needs_review(self, media_link: dict[str, dependencies.Any], reason: str, test_mode: bool = False) -> str:
        source_id = f'{media_link.get("source_path")}#subtitle:review'
        target_id = f'{media_link.get("target_path")}#subtitle:review'
        metadata = self._subtitle_metadata(media_link, None, None, None, 'embedded')
        metadata['confidence'] = 0.0
        if test_mode:
            dependencies.logger.debug('Review record would be written: %s', reason)
            return 'needs_review'
        dependencies.upsert_media_subtitle(
            dependencies.MEDIA_DB,
            source_id,
            target_id,
            **metadata,
            status='needs_review',
            reason=reason,
        )
        dependencies.logger.info('Action: marked for review (%s)', reason)
        return 'needs_review'

    def _subtitle_metadata(
        self,
        media_link: dict[str, dependencies.Any],
        language: str | None,
        subtitle_type: str | None,
        subtitle_format: str | None,
        source_type: str,
    ) -> dict[str, dependencies.Any]:
        return {
            'matched_video_source_path': media_link.get('source_path'),
            'matched_video_target_path': media_link.get('target_path'),
            'source_type': source_type,
            'media_type': media_link.get('media_type'),
            'media_tmdb_id': media_link.get('media_tmdb_id'),
            'season': media_link.get('season'),
            'episode': media_link.get('episode'),
            'language': language,
            'subtitle_type': subtitle_type or 'normal',
            'format': subtitle_format,
            'confidence': 0.95 if language else 0.0,
        }

    def _candidate_video_payload(self, media_link: dict[str, dependencies.Any]) -> dict[str, dependencies.Any]:
        return {
            'source_path': media_link.get('source_path'),
            'target_path': media_link.get('target_path'),
            'media_type': media_link.get('media_type'),
            'media_name': media_link.get('media_name'),
            'base_title': media_link.get('base_title'),
            'original_language': self._media_original_language(media_link),
            'origin_country': media_link.get('origin_country') or self._media_agent_field(media_link, 'origin_country'),
            'year': media_link.get('year'),
            'season': media_link.get('season'),
            'episode': media_link.get('episode'),
            'extension': media_link.get('extension'),
        }

    def _record_failed(self, media_link: dict[str, dependencies.Any], payload: dict[str, dependencies.Any], stage: str, reason: str | None):
        self._set_action_detail(dependencies.failure_detail_key(stage))
        dependencies.add_failed_case(
            dependencies.MEDIA_DB,
            media_link.get('source_path'),
            dependencies.os.path.basename(media_link.get('source_path') or ''),
            parsed_json=dependencies.json.dumps(payload, ensure_ascii=False),
            result_json=None,
            fail_stage=f'subtitle_{stage}',
            reason=reason,
        )
        metadata = self._subtitle_metadata(media_link, None, None, None, 'failed')
        metadata['confidence'] = 0.0
        dependencies.upsert_media_subtitle(
            dependencies.MEDIA_DB,
            f'{media_link.get("source_path")}#subtitle:failed:{stage}',
            f'{media_link.get("target_path")}#subtitle:failed:{stage}',
            **metadata,
            status='failed',
            reason=reason or stage,
        )
        dependencies.logger.error('Action: failed at %s (%s)', stage, reason or 'unknown error')
