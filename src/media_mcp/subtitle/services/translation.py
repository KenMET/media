#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from media_mcp.subtitle.services import dependencies


def _process_text_translation(
    self,
    media_link: dict[str, dependencies.Any],
    sidecars: list[dependencies.SubtitleCandidate],
    test_mode: bool = False,
    allow_online_source: bool = True,
    source_kinds: tuple[str, ...] = ("sidecar", "embedded", "online"),
    reuse_existing_output: bool = True,
) -> str | None:
    target_subtitle = self._translated_target_path(media_link)
    legacy_target = self._legacy_translated_target_path(media_link)
    if (
        reuse_existing_output
        and not dependencies.os.path.exists(target_subtitle)
        and dependencies.os.path.exists(legacy_target)
    ):
        if test_mode:
            dependencies.logger.info(
                "Action: would rename legacy bilingual subtitle %s -> %s",
                dependencies.os.path.basename(legacy_target),
                dependencies.os.path.basename(target_subtitle),
            )
        else:
            self._replace_file(legacy_target, target_subtitle)
            dependencies.logger.info(
                "Action: renamed legacy bilingual subtitle %s -> %s",
                dependencies.os.path.basename(legacy_target),
                dependencies.os.path.basename(target_subtitle),
            )
    if reuse_existing_output and dependencies.os.path.exists(target_subtitle):
        if not test_mode:
            self._cleanup_legacy_translation_sources(media_link)
        if test_mode:
            dependencies.logger.info(
                "Action: would keep existing bilingual subtitle %s",
                dependencies.os.path.basename(target_subtitle),
            )
        return "exists"

    source_path: str | None = None
    source_id: str | None = None
    source_language: str | None = None
    source_type: str | None = None
    source_sync_reason: str | None = None
    source_detail = ""
    temporary_source = False
    chinese_only_output = False

    primary_language = self._primary_translation_language(media_link)
    if not primary_language or primary_language in dependencies.CHINESE_LANGUAGES:
        dependencies.logger.info(
            "%s: skip media=%s reason=origin_language_unavailable_or_chinese",
            self._stage_label(4, "AI source origin-language"),
            self._media_display_name(media_link),
        )
    language_preferences = self._translation_source_language_preferences(media_link)
    video_path = self._video_path(media_link)
    streams: list[dependencies.EmbeddedSubtitleStream] | None = None
    rejected_embedded_text_streams: set[int] = set()
    source_kind_label = ",".join(source_kinds)
    for preferred_language in language_preferences:
        stage_index, stage_name = self._translation_stage_for_language(
            media_link, preferred_language
        )
        stage = self._stage_label(stage_index, stage_name)
        dependencies.logger.info(
            "%s: start media=%s language=%s sources=%s",
            stage,
            self._media_display_name(media_link),
            preferred_language or "any",
            source_kind_label,
        )
        for source_kind in source_kinds:
            if source_kind == "sidecar":
                sidecar = self._select_sidecar_translation_source(
                    media_link,
                    sidecars,
                    language_preferences=(preferred_language,),
                )
                if sidecar:
                    source_path = sidecar.path
                    source_id = sidecar.path
                    source_language = sidecar.language
                    source_type = "sidecar_translation"
                    source_detail = dependencies.os.path.basename(sidecar.path)
                    chinese_only_output = False
                    break
                dependencies.logger.info(
                    "%s: sidecar miss language=%s candidates=%d",
                    stage,
                    preferred_language or "any",
                    len(sidecars),
                )

            elif source_kind == "embedded":
                if streams is None:
                    try:
                        streams = dependencies.ffprobe_subtitle_streams(video_path)
                    except dependencies.EmbeddedSubtitleProbeError as exc:
                        dependencies.logger.warning(
                            "Translation source probe failed (%s)", exc
                        )
                        streams = []
                while True:
                    stream = self._select_embedded_translation_source_for_media(
                        media_link,
                        streams,
                        language_preferences=(preferred_language,),
                        exclude_stream_indexes=rejected_embedded_text_streams,
                    )
                    if not stream:
                        break
                    source_language = stream.language or stream.raw_language
                    source_type = "embedded_translation"
                    source_id = (
                        f'{media_link["source_path"]}#stream:{stream.stream_index}'
                    )
                    source_detail = f"embedded #{stream.stream_index}"
                    chinese_only_output = False
                    if test_mode:
                        dependencies.logger.info(
                            "Action: would translate %s (%s, layout=bilingual) -> %s",
                            source_detail,
                            source_language or "auto",
                            dependencies.os.path.basename(target_subtitle),
                        )
                        self._set_action_detail(
                            dependencies.translation_detail_key(
                                source_type, source_language
                            )
                        )
                        return "translated"
                    source_path = self._prepare_embedded_text_translation_source(
                        media_link,
                        video_path,
                        stream,
                        stage=stage,
                        preferred_language=preferred_language,
                    )
                    if not source_path:
                        rejected_embedded_text_streams.add(stream.stream_index)
                        source_id = None
                        source_language = None
                        source_type = None
                        source_detail = ""
                        continue
                    temporary_source = True
                    break
                if source_path:
                    break
                ocr_stream = self._select_embedded_ocr_translation_source_for_media(
                    media_link,
                    streams,
                    language_preferences=(preferred_language,),
                )
                if ocr_stream:
                    source_language = ocr_stream.language or ocr_stream.raw_language
                    source_type = "embedded_ocr_translation"
                    source_id = f'{media_link["source_path"]}#stream:{ocr_stream.stream_index}:ocr'
                    source_detail = f"embedded OCR #{ocr_stream.stream_index}"
                    chinese_only_output = False
                    if test_mode:
                        dependencies.logger.info(
                            "Action: would OCR and translate %s (%s, layout=bilingual) -> %s",
                            source_detail,
                            source_language or "auto",
                            dependencies.os.path.basename(target_subtitle),
                        )
                        self._set_action_detail(
                            dependencies.translation_detail_key(
                                source_type, source_language
                            )
                        )
                        return "translated"
                    source_path, _ = self._prepare_embedded_ocr_translation_source(
                        media_link,
                        video_path,
                        ocr_stream,
                        stage=stage,
                        preferred_language=preferred_language,
                    )
                    if source_path:
                        temporary_source = True
                        break
                    source_path = None
                    source_id = None
                    source_language = None
                    source_type = None
                    source_detail = ""
                dependencies.logger.info(
                    "%s: embedded miss language=%s streams=%d rejected=%s ocr_rejected=%s",
                    stage,
                    preferred_language or "any",
                    len(streams),
                    self._embedded_translation_rejection_summary(
                        streams, preferred_language
                    ),
                    self._embedded_ocr_rejection_summary(streams, preferred_language),
                )

            elif source_kind == "online" and allow_online_source:
                online_source = self._download_online_translation_source(
                    media_link,
                    target_subtitle,
                    test_mode=test_mode,
                    language_preferences=(preferred_language,),
                )
                if online_source:
                    source_path = online_source.get("source_path")
                    source_id = online_source.get("source_id")
                    source_language = online_source.get("source_language")
                    source_type = online_source.get("source_type")
                    source_sync_reason = online_source.get("source_sync_reason")
                    source_detail = online_source.get("source_detail") or ""
                    temporary_source = bool(online_source.get("temporary_source"))
                    chinese_only_output = False
                    break
                dependencies.logger.info(
                    "%s: online miss language=%s",
                    stage,
                    preferred_language or "any",
                )
        if source_id or source_path:
            dependencies.logger.info(
                "%s: hit source=%s language=%s",
                stage,
                source_detail or source_id or source_path,
                source_language or preferred_language or "auto",
            )
            break
        dependencies.logger.info(
            "%s: miss language=%s", stage, preferred_language or "any"
        )

    if not source_id and not source_path:
        local_fallback_kinds = [
            item for item in source_kinds if item in {"sidecar", "embedded"}
        ]
        stage = self._stage_label(6, "AI source any-foreign")
        if local_fallback_kinds:
            dependencies.logger.info(
                "%s: start media=%s language=any-local sources=%s",
                stage,
                self._media_display_name(media_link),
                ",".join(local_fallback_kinds),
            )
        for source_kind in local_fallback_kinds:
            if source_kind == "sidecar":
                sidecar = self._select_sidecar_translation_source(
                    media_link,
                    sidecars,
                    language_preferences=(None,),
                )
                if sidecar:
                    source_path = sidecar.path
                    source_id = sidecar.path
                    source_language = sidecar.language
                    source_type = "sidecar_translation"
                    source_detail = dependencies.os.path.basename(sidecar.path)
                    chinese_only_output = True
                    break
                dependencies.logger.info(
                    "%s: sidecar miss language=any candidates=%d",
                    stage,
                    len(sidecars),
                )
            elif source_kind == "embedded":
                if streams is None:
                    try:
                        streams = dependencies.ffprobe_subtitle_streams(video_path)
                    except dependencies.EmbeddedSubtitleProbeError as exc:
                        dependencies.logger.warning(
                            "Translation source probe failed (%s)", exc
                        )
                        streams = []
                while True:
                    stream = self._select_embedded_translation_source_for_media(
                        media_link,
                        streams,
                        language_preferences=(None,),
                        exclude_stream_indexes=rejected_embedded_text_streams,
                    )
                    if not stream:
                        break
                    source_language = stream.language or stream.raw_language
                    source_type = "embedded_translation"
                    source_id = (
                        f'{media_link["source_path"]}#stream:{stream.stream_index}'
                    )
                    source_detail = f"embedded #{stream.stream_index}"
                    chinese_only_output = True
                    if test_mode:
                        dependencies.logger.info(
                            "Action: would translate %s (%s, Chinese only fallback) -> %s",
                            source_detail,
                            source_language or "auto",
                            dependencies.os.path.basename(target_subtitle),
                        )
                        self._set_action_detail(
                            dependencies.translation_detail_key(
                                source_type, source_language
                            )
                        )
                        return "translated"
                    source_path = self._prepare_embedded_text_translation_source(
                        media_link,
                        video_path,
                        stream,
                        stage=stage,
                        preferred_language=None,
                    )
                    if not source_path:
                        rejected_embedded_text_streams.add(stream.stream_index)
                        source_id = None
                        source_language = None
                        source_type = None
                        source_detail = ""
                        continue
                    temporary_source = True
                    break
                if source_path:
                    break
                ocr_stream = self._select_embedded_ocr_translation_source_for_media(
                    media_link,
                    streams,
                    language_preferences=(None,),
                )
                if ocr_stream:
                    source_language = ocr_stream.language or ocr_stream.raw_language
                    source_type = "embedded_ocr_translation"
                    source_id = f'{media_link["source_path"]}#stream:{ocr_stream.stream_index}:ocr'
                    source_detail = f"embedded OCR #{ocr_stream.stream_index}"
                    chinese_only_output = True
                    if test_mode:
                        dependencies.logger.info(
                            "Action: would OCR and translate %s (%s, Chinese only fallback) -> %s",
                            source_detail,
                            source_language or "auto",
                            dependencies.os.path.basename(target_subtitle),
                        )
                        self._set_action_detail(
                            dependencies.translation_detail_key(
                                source_type, source_language
                            )
                        )
                        return "translated"
                    source_path, _ = self._prepare_embedded_ocr_translation_source(
                        media_link,
                        video_path,
                        ocr_stream,
                        stage=stage,
                        preferred_language=None,
                    )
                    if source_path:
                        temporary_source = True
                        break
                    source_path = None
                    source_id = None
                    source_language = None
                    source_type = None
                    source_detail = ""
                dependencies.logger.info(
                    "%s: embedded miss language=any streams=%d rejected=%s ocr_rejected=%s",
                    stage,
                    len(streams),
                    self._embedded_translation_rejection_summary(streams, None),
                    self._embedded_ocr_rejection_summary(streams, None),
                )
        if source_id or source_path:
            dependencies.logger.info(
                "%s: hit source=%s language=%s",
                stage,
                source_detail or source_id or source_path,
                source_language or "auto",
            )
        elif local_fallback_kinds:
            dependencies.logger.info("%s: miss language=any-local", stage)

    if (
        not source_id
        and not source_path
        and allow_online_source
        and "online" in source_kinds
    ):
        fallback_languages = self._translation_any_fallback_languages(
            language_preferences
        )
        if fallback_languages:
            stage = self._stage_label(6, "AI source any-foreign")
            dependencies.logger.info(
                "%s: start media=%s language=any-online sources=online fallback=%s",
                stage,
                self._media_display_name(media_link),
                ",".join(fallback_languages),
            )
            online_source = self._download_online_translation_source(
                media_link,
                target_subtitle,
                test_mode=test_mode,
                language_preferences=fallback_languages,
            )
            if online_source:
                source_path = online_source.get("source_path")
                source_id = online_source.get("source_id")
                source_language = online_source.get("source_language")
                source_type = online_source.get("source_type")
                source_sync_reason = online_source.get("source_sync_reason")
                source_detail = online_source.get("source_detail") or ""
                temporary_source = bool(online_source.get("temporary_source"))
                chinese_only_output = True
                dependencies.logger.info(
                    "%s: hit source=%s language=%s",
                    stage,
                    source_detail or source_id or source_path,
                    source_language or "auto",
                )
            else:
                dependencies.logger.info("%s: miss language=any-online", stage)

    if not source_id and not source_path:
        return None

    if test_mode:
        try:
            event_count = len(dependencies.parse_text_subtitle(source_path or ""))
        except dependencies.SubtitleTranslationError:
            event_count = 0
        dependencies.logger.info(
            "Action: would translate %s (%s, events=%d, layout=%s) -> %s",
            source_detail,
            source_language or "auto",
            event_count,
            "Chinese only" if chinese_only_output else "bilingual",
            dependencies.os.path.basename(target_subtitle),
        )
        self._set_action_detail(
            dependencies.translation_detail_key(source_type, source_language)
        )
        return "translated"

    try:
        events = dependencies.parse_text_subtitle(source_path or "")
        translation_profile = dependencies.validate_translation_events(
            events,
            max_events=dependencies.MAX_TRANSLATION_EVENTS,
            warn_events=dependencies.WARN_TRANSLATION_EVENTS,
            max_events_per_minute=dependencies.MAX_EVENTS_PER_MINUTE,
            warn_events_per_minute=dependencies.WARN_EVENTS_PER_MINUTE,
        )
        media_label = self._media_display_name(media_link)
        dependencies.logger.info(
            "Translation: media=%s source ready %s "
            "(%s, events=%d, density=%.1f/min, duplicates=%.1f%%)",
            media_label,
            source_detail,
            source_language or "auto",
            len(events),
            float(translation_profile["events_per_minute"]),
            float(translation_profile["duplicate_ratio"]) * 100,
        )
        if self.client is None:
            from media_mcp.subtitle.clients.codex import CodexSubtitleClient

            self.client = CodexSubtitleClient()
        media_context = self._translation_media_context(media_link)
        try:
            dependencies.logger.info(
                "Translation: media=%s building context with Codex", media_label
            )
            guide = self._call_ai_with_usage_retry(
                lambda: self.client.build_subtitle_translation_context(media_context),
                media_label=media_label,
                operation="subtitle_translation_context",
            )
        except Exception as exc:
            dependencies.logger.warning(
                "Translation: media=%s context unavailable (%s)", media_label, exc
            )
        else:
            normalized_guide = self._normalize_translation_guide(guide)
            if normalized_guide:
                media_context["translation_guide"] = normalized_guide
                dependencies.logger.info(
                    "Translation: media=%s context ready", media_label
                )
            else:
                dependencies.logger.info(
                    "Translation: media=%s context unavailable; continuing without guide",
                    media_label,
                )
        translations = dependencies.translate_events(
            events,
            lambda payload: self._call_ai_with_usage_retry(
                lambda: self.client.translate_subtitle_batch(payload),
                media_label=media_label,
                operation="subtitle_translate",
            ),
            media_context,
            source_language,
            max_events=dependencies.TRANSLATION_BATCH_EVENTS,
            max_characters=dependencies.TRANSLATION_BATCH_CHARACTERS,
            max_tokens=dependencies.TRANSLATION_BATCH_TOKENS,
            incomplete_retries=dependencies.TRANSLATION_INCOMPLETE_RETRIES,
        )
        if chinese_only_output:
            content = dependencies.render_chinese_ass(
                events,
                translations,
                chinese_font_size=dependencies.CHINESE_FONT_SIZE,
                bottom_margin=dependencies.SUBTITLE_BOTTOM_MARGIN,
            )
        else:
            content = dependencies.render_bilingual_ass(
                events,
                translations,
                chinese_font_size=dependencies.CHINESE_FONT_SIZE,
                source_font_size=dependencies.SOURCE_FONT_SIZE,
                bottom_margin=dependencies.SUBTITLE_BOTTOM_MARGIN,
            )
        dependencies.write_text_atomic(target_subtitle, content)
        self._invalidate_path_cache(target_subtitle)
    except Exception as exc:
        self._record_failed(
            media_link,
            {
                "source": source_id,
                "source_language": source_language,
                "target": target_subtitle,
            },
            "translation",
            str(exc),
        )
        return "failed"
    finally:
        if (
            temporary_source
            and source_path
            and dependencies.os.path.exists(source_path)
        ):
            try:
                self._remove_file(source_path)
                dependencies.logger.info(
                    "Translation: removed temporary source %s",
                    dependencies.os.path.basename(source_path),
                )
            except OSError as exc:
                dependencies.logger.warning(
                    "Translation: failed to remove temporary source %s (%s)",
                    dependencies.os.path.basename(source_path),
                    exc,
                )

    metadata = self._subtitle_metadata(
        media_link,
        "zh-CN" if chinese_only_output else "zh-CN-bilingual",
        "normal" if chinese_only_output else "bilingual",
        "ass",
        source_type or "translation",
    )
    layout = (
        "chinese_only" if chinese_only_output else "chinese_primary_source_secondary"
    )
    dependencies.upsert_media_subtitle(
        dependencies.MEDIA_DB,
        source_id or source_path or "",
        target_subtitle,
        **metadata,
        status="translated",
        reason=(
            f'provider=codex; source_language={source_language or "auto"}; '
            f"events={len(events)}; layout={layout}"
            + (f"; source_{source_sync_reason}" if source_sync_reason else "")
        ),
    )
    dependencies.logger.info(
        "Action: translated %s (%s, events=%d, layout=%s) -> %s",
        source_detail,
        source_language or "auto",
        len(events),
        layout,
        dependencies.os.path.basename(target_subtitle),
    )
    self._cleanup_legacy_translation_sources(media_link)
    self._set_action_detail(
        dependencies.translation_detail_key(source_type, source_language)
    )
    return "translated"


def _process_audio_transcription(
    self, media_link: dict[str, dependencies.Any], test_mode: bool = False
) -> str | None:
    if not dependencies.ENABLE_AUDIO_ASR:
        return None
    video_path = self._video_path(media_link)
    target_subtitle = self._translated_target_path(media_link)
    if test_mode:
        dependencies.logger.info(
            "Action: would transcribe audio with faster-whisper model=%s device=%s -> %s",
            dependencies.ASR_MODEL,
            dependencies.ASR_DEVICE,
            dependencies.os.path.basename(target_subtitle),
        )
        return "audio_transcribed"

    try:
        result = dependencies.transcribe_audio(
            video_path,
            model_size=dependencies.ASR_MODEL,
            language=dependencies.ASR_LANGUAGE,
            device=dependencies.ASR_DEVICE,
            compute_type=dependencies.ASR_COMPUTE_TYPE,
            beam_size=dependencies.ASR_BEAM_SIZE,
            vad_filter=dependencies.ASR_VAD_FILTER,
        )
    except dependencies.AudioTranscriptionError as exc:
        dependencies.logger.warning("Audio ASR unavailable or failed (%s)", exc)
        return None

    asr_srt = dependencies.build_asr_sidecar_path(
        media_link["target_path"], result.language
    )
    dependencies.write_srt(asr_srt, result.events)
    language = result.language or "auto"
    metadata = self._subtitle_metadata(
        media_link, language, "normal", "srt", "audio_asr"
    )
    metadata["confidence"] = min(
        0.95, max(0.5, float(result.language_probability or 0.8))
    )

    if language.startswith("zh") or self.disable_agent:
        dependencies.upsert_media_subtitle(
            dependencies.MEDIA_DB,
            f'{media_link.get("source_path")}#audio',
            asr_srt,
            **metadata,
            status="audio_transcribed",
            reason=(
                f"provider=faster-whisper; model={result.model_size}; "
                f"language={language}; events={len(result.events)}"
            ),
        )
        dependencies.logger.info(
            "Action: transcribed audio (%s, events=%d) -> %s",
            language,
            len(result.events),
            dependencies.os.path.basename(asr_srt),
        )
        return "audio_transcribed"

    if self.client is None:
        from media_mcp.subtitle.clients.codex import CodexSubtitleClient

        self.client = CodexSubtitleClient()
    try:
        translation_profile = dependencies.validate_translation_events(
            result.events,
            max_events=dependencies.MAX_TRANSLATION_EVENTS,
            warn_events=dependencies.WARN_TRANSLATION_EVENTS,
            max_events_per_minute=dependencies.MAX_EVENTS_PER_MINUTE,
            warn_events_per_minute=dependencies.WARN_EVENTS_PER_MINUTE,
        )
        dependencies.logger.info(
            "Audio ASR translation: source ready (%s, events=%d, density=%.1f/min)",
            language,
            len(result.events),
            float(translation_profile["events_per_minute"]),
        )
        translations = dependencies.translate_events(
            result.events,
            lambda payload: self._call_ai_with_usage_retry(
                lambda: self.client.translate_subtitle_batch(payload),
                media_label=self._media_display_name(media_link),
                operation="audio_asr_translate",
            ),
            self._candidate_video_payload(media_link),
            language,
            max_events=dependencies.TRANSLATION_BATCH_EVENTS,
            max_characters=dependencies.TRANSLATION_BATCH_CHARACTERS,
            max_tokens=dependencies.TRANSLATION_BATCH_TOKENS,
            incomplete_retries=dependencies.TRANSLATION_INCOMPLETE_RETRIES,
        )
        content = dependencies.render_bilingual_ass(
            result.events,
            translations,
            chinese_font_size=dependencies.CHINESE_FONT_SIZE,
            source_font_size=dependencies.SOURCE_FONT_SIZE,
            bottom_margin=dependencies.SUBTITLE_BOTTOM_MARGIN,
        )
        dependencies.write_text_atomic(target_subtitle, content)
        self._invalidate_path_cache(target_subtitle)
    except Exception as exc:
        self._record_failed(
            media_link,
            {"source": asr_srt, "language": language, "events": len(result.events)},
            "audio_asr_translation",
            str(exc),
        )
        return "failed"

    translated_metadata = self._subtitle_metadata(
        media_link, "zh-CN-bilingual", "bilingual", "ass", "audio_asr_translation"
    )
    dependencies.upsert_media_subtitle(
        dependencies.MEDIA_DB,
        asr_srt,
        target_subtitle,
        **translated_metadata,
        status="audio_translated",
        reason=(
            f"provider=faster-whisper+codex; model={result.model_size}; "
            f"source_language={language}; events={len(result.events)}; "
            "layout=chinese_primary_source_secondary"
        ),
    )
    dependencies.logger.info(
        "Action: transcribed and translated audio (%s, events=%d) -> %s",
        language,
        len(result.events),
        dependencies.os.path.basename(target_subtitle),
    )
    self._cleanup_legacy_translation_sources(media_link)
    return "audio_translated"
