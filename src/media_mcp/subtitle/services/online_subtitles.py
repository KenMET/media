#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from media_mcp.subtitle.services import dependencies


def _download_online_translation_source(
    self,
    media_link: dict[str, dependencies.Any],
    target_subtitle: str,
    test_mode: bool = False,
    language_preferences: tuple[str, ...] | None = None,
) -> dict[str, dependencies.Any] | None:
    language_preferences = (
        language_preferences
        or self._translation_source_language_preferences(media_link)
    )
    if not language_preferences:
        return None

    request_base = {
        "media_type": str(media_link.get("media_type") or "movie"),
        "tmdb_id": self._optional_int(media_link.get("media_tmdb_id")),
        "title": media_link.get("base_title") or media_link.get("media_name"),
        "year": self._optional_int(media_link.get("year")),
        "season": self._optional_int(media_link.get("season")),
        "episode": self._optional_int(media_link.get("episode")),
    }
    media_label = self._media_display_name(media_link)
    providers_by_name = {
        provider.name: provider for provider in self.provider_registry.providers
    }
    provider_statuses = getattr(self.provider_registry, "provider_statuses", None) or [
        {"provider": provider.name, "configured": True}
        for provider in self.provider_registry.providers
    ]
    dependencies.logger.debug(
        "Translation source search: media=%s languages=%s",
        media_label,
        ",".join(language_preferences),
    )
    if not providers_by_name:
        for status in provider_statuses:
            dependencies.logger.info(
                "Translation source provider %s: skipped (not configured)",
                status.get("provider"),
            )
        dependencies.logger.info(
            "Translation source search: skipped media=%s (no configured providers)",
            media_label,
        )
        return None

    searched: list[str] = []
    for language in language_preferences:
        request = dependencies.SubtitleSearchRequest(
            **request_base, languages=(language,)
        )
        for status in provider_statuses:
            provider_name = str(status.get("provider") or "")
            provider = providers_by_name.get(provider_name)
            if provider is None:
                dependencies.logger.info(
                    "Translation source provider %s language=%s: skipped (not configured)",
                    provider_name,
                    language,
                )
                continue
            blocked_retry_at = self._provider_blocked_retry_at(provider_name)
            if blocked_retry_at:
                dependencies.logger.info(
                    "Translation source provider %s language=%s: skipped (blocked, retry_at=%s)",
                    provider_name,
                    language,
                    dependencies.time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        dependencies.time.localtime(blocked_retry_at),
                    ),
                )
                continue
            searched.append(f"{provider_name}:{language}")
            try:
                candidates = self._search_provider_candidates(
                    provider, provider_name, request
                )
            except dependencies.ProviderTemporarilyUnavailable as exc:
                retry_at = self._mark_provider_unavailable(exc)
                dependencies.logger.info(
                    "Translation source provider %s language=%s: skipped (%s, retry_at=%s)",
                    exc.provider,
                    language,
                    exc.reason,
                    retry_at,
                )
                continue
            except Exception as exc:
                dependencies.logger.info(
                    "Translation source provider %s language=%s: failed (%s)",
                    provider_name,
                    language,
                    exc,
                )
                continue

            ranked = self._rank_online_translation_candidates(
                media_link, candidates, language
            )
            attempt_ranked = ranked[
                : max(1, dependencies.ONLINE_CANDIDATES_PER_PROVIDER)
            ]
            rejected = (
                "-"
                if ranked
                else self._online_translation_rejection_summary(
                    media_link, candidates, language
                )
            )
            dependencies.logger.info(
                "Translation source provider %s language=%s: candidates=%d qualified=%d attempts=%d rejected=%s",
                provider_name,
                language,
                len(candidates),
                len(ranked),
                len(attempt_ranked),
                rejected,
            )
            if not attempt_ranked:
                continue

            top_score, top, top_reason = attempt_ranked[0]
            if test_mode:
                safe_file_id = self._redact_sensitive_text(top.file_id)
                dependencies.logger.info(
                    "Action: would download translation source %s:%s (%s, score=%.1f; %s) -> %s",
                    top.provider,
                    safe_file_id,
                    top.language,
                    top_score,
                    top_reason,
                    dependencies.os.path.basename(target_subtitle),
                )
                return {
                    "source_path": None,
                    "source_id": f"provider://{top.provider}/{safe_file_id}",
                    "source_language": top.language,
                    "source_type": "provider_translation",
                    "source_detail": f"online {top.provider}:{safe_file_id}",
                    "temporary_source": False,
                }

            for score, candidate, reason in attempt_ranked:
                safe_file_id = self._redact_sensitive_text(candidate.file_id)
                try:
                    downloaded = self._download_provider_candidate(provider, candidate)
                    validated = dependencies.validate_online_translation_source(
                        downloaded.content,
                        downloaded.file_name,
                    )
                except dependencies.ProviderTemporarilyUnavailable as exc:
                    retry_at = self._mark_provider_unavailable(exc)
                    dependencies.logger.warning(
                        "Translation source provider %s circuit opened (%s, retry_at=%s)",
                        exc.provider,
                        exc.reason,
                        retry_at,
                    )
                    break
                except Exception as exc:
                    dependencies.logger.warning(
                        "Translation source candidate rejected: %s:%s (%s)",
                        candidate.provider,
                        safe_file_id,
                        self._redact_sensitive_text(exc),
                    )
                    continue

                safe_language = (
                    dependencies.re.sub(
                        r"[^A-Za-z0-9-]+", "-", candidate.language or language
                    ).strip("-")
                    or language
                )
                source_path = dependencies.shorten_sidecar_path(
                    media_link["target_path"],
                    f".subtitle-translation-source.{candidate.provider}.{safe_language}{validated.extension}",
                )
                temporary_path = f"{source_path}.part"
                try:
                    dependencies.os.makedirs(
                        dependencies.os.path.dirname(source_path), exist_ok=True
                    )
                    with open(temporary_path, "xb") as handle:
                        handle.write(validated.content)
                    self._replace_file(temporary_path, source_path)
                except OSError as exc:
                    try:
                        if dependencies.os.path.exists(temporary_path):
                            self._remove_file(temporary_path)
                    except OSError:
                        pass
                    dependencies.logger.warning(
                        "Translation source write failed: %s:%s (%s)",
                        candidate.provider,
                        safe_file_id,
                        exc,
                    )
                    continue
                self._invalidate_path_cache(source_path)
                sync_ok, sync_reason = self._sync_downloaded_subtitle(
                    media_link,
                    source_path,
                    candidate_ref=f"{candidate.provider}:{safe_file_id}",
                    validate_content=dependencies.validate_online_translation_source,
                )
                if not sync_ok:
                    try:
                        if dependencies.os.path.exists(source_path):
                            self._remove_file(source_path)
                    except OSError:
                        pass
                    dependencies.logger.warning(
                        "Translation source candidate rejected after sync: %s:%s (%s)",
                        candidate.provider,
                        safe_file_id,
                        sync_reason,
                    )
                    continue
                dependencies.logger.info(
                    "Translation: downloaded source %s:%s (%s, score=%.1f; %s)",
                    candidate.provider,
                    safe_file_id,
                    candidate.language,
                    score,
                    reason,
                )
                return {
                    "source_path": source_path,
                    "source_id": f"provider://{candidate.provider}/{safe_file_id}",
                    "source_language": candidate.language,
                    "source_type": "provider_translation",
                    "source_detail": f"online {candidate.provider}:{safe_file_id}",
                    "source_sync_reason": sync_reason,
                    "temporary_source": True,
                }

    dependencies.logger.debug(
        "Translation: no online source found (languages=%s, providers=%s)",
        ",".join(language_preferences),
        ",".join(searched) or "-",
    )
    return None


def _process_online_subtitle(
    self,
    media_link: dict[str, dependencies.Any],
    test_mode: bool = False,
) -> str | None:
    request_base = dict(
        media_type=str(media_link.get("media_type") or "movie"),
        tmdb_id=self._optional_int(media_link.get("media_tmdb_id")),
        year=self._optional_int(media_link.get("year")),
        season=self._optional_int(media_link.get("season")),
        episode=self._optional_int(media_link.get("episode")),
    )
    search_titles = self._online_search_titles(media_link)
    media_label = self._media_display_name(media_link)
    dependencies.logger.debug(
        "Online search: media=%s target=Chinese languages=%s queries=%s",
        media_label,
        ",".join(dependencies.ONLINE_SEARCH_LANGUAGES),
        " | ".join(search_titles) or "-",
    )
    providers_by_name = {
        provider.name: provider for provider in self.provider_registry.providers
    }
    provider_statuses = getattr(self.provider_registry, "provider_statuses", None) or [
        {"provider": provider.name, "configured": True}
        for provider in self.provider_registry.providers
    ]
    if not providers_by_name:
        for status in provider_statuses:
            dependencies.logger.info(
                "Online provider %s: skipped (not configured)", status.get("provider")
            )
        dependencies.logger.warning(
            "Online search: skipped media=%s (no configured providers)", media_label
        )
        return None

    searched_providers: list[str] = []
    total_candidates = 0
    total_qualified = 0
    total_attempts = 0
    for status in provider_statuses:
        provider_name = str(status.get("provider") or "")
        provider = providers_by_name.get(provider_name)
        if provider is None:
            dependencies.logger.info(
                "Online provider %s: skipped (not configured)", provider_name
            )
            continue
        blocked_retry_at = self._provider_blocked_retry_at(provider_name)
        if blocked_retry_at:
            dependencies.logger.info(
                "Online provider %s: skipped (blocked, retry_at=%s)",
                provider_name,
                dependencies.time.strftime(
                    "%Y-%m-%d %H:%M:%S", dependencies.time.localtime(blocked_retry_at)
                ),
            )
            continue
        searched_providers.append(provider_name)
        provider_blocked = False
        for search_title in search_titles:
            request = dependencies.SubtitleSearchRequest(
                **request_base,
                title=search_title,
                languages=dependencies.ONLINE_SEARCH_LANGUAGES,
            )
            try:
                candidates = self._search_provider_candidates(
                    provider, provider_name, request
                )
            except dependencies.ProviderTemporarilyUnavailable as exc:
                retry_at = self._mark_provider_unavailable(exc)
                dependencies.logger.info(
                    "Online provider %s: skipped (%s, retry_at=%s)",
                    exc.provider,
                    exc.reason,
                    retry_at,
                )
                provider_blocked = True
                break
            except Exception as exc:
                dependencies.logger.info(
                    "Online provider %s query=%s: failed (%s)",
                    provider_name,
                    search_title,
                    exc,
                )
                continue

            total_candidates += len(candidates)
            ranked = self._rank_online_candidates(media_link, candidates)
            total_qualified += len(ranked)
            attempt_ranked = ranked[
                : max(1, dependencies.ONLINE_CANDIDATES_PER_PROVIDER)
            ]
            total_attempts += len(attempt_ranked)
            rejected = (
                "-"
                if ranked
                else self._online_rejection_summary(media_link, candidates)
            )
            dependencies.logger.info(
                "Online provider %s: searched query=%s languages=%s candidates=%d qualified=%d attempts=%d rejected=%s",
                provider_name,
                search_title,
                ",".join(request.languages),
                len(candidates),
                len(ranked),
                len(attempt_ranked),
                rejected,
            )
            if not attempt_ranked:
                continue

            top_score, top, top_reason = attempt_ranked[0]
            top_file_id = self._redact_sensitive_text(top.file_id)
            dependencies.logger.info(
                "Selection: online media=%s provider=%s file=%s (%s, %s, score=%.1f; %s)",
                media_label,
                top.provider,
                top_file_id,
                top.language,
                top.subtitle_type,
                top_score,
                top_reason,
            )
            target_path = dependencies.build_sidecar_path(
                media_link["target_path"],
                f".{top.format}",
                top.language,
                top.subtitle_type,
            )
            if test_mode:
                dependencies.logger.info(
                    "Action: would download online subtitle %s:%s -> %s",
                    top.provider,
                    top_file_id,
                    dependencies.os.path.basename(target_path),
                )
                self._set_action_detail("downloaded:online")
                return "downloaded"

            for score, candidate, reason in attempt_ranked:
                safe_file_id = self._redact_sensitive_text(candidate.file_id)
                try:
                    downloaded = self._download_provider_candidate(provider, candidate)
                    episode_mismatch = self._online_candidate_explicit_episode_mismatch(
                        media_link,
                        candidate,
                        downloaded_file_name=downloaded.file_name,
                    )
                    if episode_mismatch:
                        raise ValueError(episode_mismatch)
                    validated = dependencies.validate_online_subtitle(
                        downloaded.content, downloaded.file_name
                    )
                except dependencies.ProviderTemporarilyUnavailable as exc:
                    retry_at = self._mark_provider_unavailable(exc)
                    dependencies.logger.warning(
                        "Online provider %s circuit opened (%s, retry_at=%s)",
                        exc.provider,
                        exc.reason,
                        retry_at,
                    )
                    provider_blocked = True
                    break
                except Exception as exc:
                    dependencies.logger.warning(
                        "Online candidate rejected: %s:%s (%s)",
                        candidate.provider,
                        safe_file_id,
                        self._redact_sensitive_text(exc),
                    )
                    continue

                target_path = dependencies.build_sidecar_path(
                    media_link["target_path"],
                    validated.extension,
                    candidate.language,
                    candidate.subtitle_type,
                )
                sync_reason = "subtitle_sync=existing"
                if dependencies.os.path.exists(target_path):
                    status = "exists"
                else:
                    temporary_path = f"{target_path}.{dependencies.uuid.uuid4().hex}.part"
                    try:
                        dependencies.os.makedirs(
                            dependencies.os.path.dirname(target_path), exist_ok=True
                        )
                        with open(temporary_path, "xb") as handle:
                            handle.write(validated.content)
                        self._replace_file(temporary_path, target_path)
                        status = "downloaded"
                    except OSError as exc:
                        try:
                            if dependencies.os.path.exists(temporary_path):
                                self._remove_file(temporary_path)
                        except OSError:
                            pass
                        dependencies.logger.warning(
                            "Online candidate write failed: %s:%s (%s)",
                            candidate.provider,
                            safe_file_id,
                            exc,
                        )
                        continue
                    sync_ok, sync_reason = self._sync_downloaded_subtitle(
                        media_link,
                        target_path,
                        candidate_ref=f"{candidate.provider}:{safe_file_id}",
                        validate_content=dependencies.validate_online_subtitle,
                    )
                    if not sync_ok:
                        try:
                            if dependencies.os.path.exists(target_path):
                                self._remove_file(target_path)
                        except OSError:
                            pass
                        dependencies.logger.warning(
                            "Online candidate rejected after sync: %s:%s (%s)",
                            candidate.provider,
                            safe_file_id,
                            sync_reason,
                        )
                        continue

                # Validate the actual final file, including an already-existing target.
                try:
                    with open(target_path, 'rb') as handle:
                        final_validated = dependencies.validate_online_subtitle(
                            handle.read(), dependencies.os.path.basename(target_path))
                except (OSError, ValueError) as exc:
                    dependencies.logger.warning('Online final subtitle rejected: %s', self._redact_sensitive_text(exc))
                    continue

                timing_ok, timing_reason = self._validate_online_subtitle_timing(
                    media_link, target_path
                )
                if not timing_ok:
                    try:
                        if status == "downloaded" and dependencies.os.path.exists(
                            target_path
                        ):
                            self._remove_file(target_path)
                    except OSError:
                        pass
                    dependencies.logger.warning(
                        "Online candidate rejected after timing QA: %s:%s (%s)",
                        candidate.provider,
                        safe_file_id,
                        timing_reason,
                    )
                    continue

                source_id = f"provider://{candidate.provider}/{safe_file_id}"
                metadata = self._subtitle_metadata(
                    media_link,
                    final_validated.profile.get('language') or candidate.language,
                    candidate.subtitle_type,
                    validated.extension.lstrip("."),
                    "provider",
                )
                metadata["confidence"] = min(0.99, max(0.75, score / 200.0))
                dependencies.upsert_media_subtitle(
                    dependencies.MEDIA_DB,
                    source_id,
                    target_path,
                    **metadata,
                    status=status,
                    reason=(
                        f"provider={candidate.provider}; candidate={candidate.candidate_id}; "
                        f"file={safe_file_id}; score={score:.1f}; {reason}; {sync_reason}; {timing_reason}; "
                        f"chinese_dialogue_coverage={final_validated.profile.get('chinese_dialogue_coverage')}"
                    ),
                )
                dependencies.logger.info(
                    "Action: %s online subtitle %s:%s -> %s",
                    "kept existing" if status == "exists" else "downloaded",
                    candidate.provider,
                    safe_file_id,
                    dependencies.os.path.basename(target_path),
                )
                if status == "downloaded":
                    self._set_action_detail(
                        "downloaded:online_synced"
                        if sync_reason == "subtitle_sync=ffsubsync"
                        else "downloaded:online"
                    )
                if hasattr(self, '_content_verifications'):
                    self._content_verifications.append({
                        'target_path': target_path, 'language': metadata.get('language'),
                        **{key: final_validated.profile.get(key) for key in (
                            'dialogue_events', 'chinese_dialogue_events', 'chinese_dialogue_coverage')}})
                return status
            if provider_blocked:
                break
        if provider_blocked:
            continue

    dependencies.logger.debug(
        "Online search: no Chinese subtitle media=%s candidates=%d qualified=%d attempts=%d providers=%s",
        media_label,
        total_candidates,
        total_qualified,
        total_attempts,
        ",".join(searched_providers) or "-",
    )
    return None
