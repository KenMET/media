#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio speech recognition helpers for subtitle generation."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from typing import Iterable

from media_mcp.subtitle.domain.translation import SubtitleEvent
from media_mcp.subtitle.domain.path_builder import shorten_sidecar_path


class AudioTranscriptionError(RuntimeError):
    """Raised when audio transcription cannot be completed."""


@dataclass(frozen=True)
class AudioTranscriptionResult:
    events: list[SubtitleEvent]
    language: str | None
    language_probability: float | None
    duration: float | None
    model_size: str


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}'


def render_srt(events: Iterable[SubtitleEvent]) -> str:
    blocks = []
    for index, event in enumerate(events, start=1):
        text = re.sub(r'\s+', ' ', event.source_text).strip()
        if not text:
            continue
        blocks.append(
            '\n'.join(
                [
                    str(index),
                    f'{_srt_time(event.start_seconds)} --> {_srt_time(event.end_seconds)}',
                    text,
                ]
            )
        )
    return '\n\n'.join(blocks) + ('\n' if blocks else '')


def write_srt(path: str, events: Iterable[SubtitleEvent]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f'{path}.part'
    try:
        with open(temporary_path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(render_srt(events))
        os.replace(temporary_path, path)
    except OSError as exc:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        raise AudioTranscriptionError(f'failed to write srt: {exc}') from exc


def build_asr_sidecar_path(video_path: str, language: str | None = None) -> str:
    suffix = _safe_language_suffix(language)
    if suffix:
        return shorten_sidecar_path(video_path, f'.asr.{suffix}.srt')
    return shorten_sidecar_path(video_path, '.asr.srt')


def _safe_language_suffix(language: str | None) -> str:
    value = (language or '').strip().replace('_', '-')
    value = re.sub(r'[^A-Za-z0-9-]+', '', value)
    return value[:24]


def normalize_asr_language(language: str | None) -> str | None:
    value = (language or '').strip().lower()
    if not value:
        return None
    if value in {'zh', 'zho', 'chi', 'cmn', 'yue'}:
        return 'zh-CN'
    return value


def transcribe_audio(
    media_path: str,
    *,
    model_size: str = 'small',
    language: str | None = None,
    device: str = 'cpu',
    compute_type: str = 'int8',
    beam_size: int = 5,
    vad_filter: bool = True,
    ffmpeg_path: str = 'ffmpeg',
) -> AudioTranscriptionResult:
    if not os.path.exists(media_path):
        raise AudioTranscriptionError(f'media path not found: {media_path}')

    try:
        _ensure_pkg_resources_compat()
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise AudioTranscriptionError(
            'faster-whisper is not installed; ASR is optional, install it with: '
            'pip install faster-whisper'
        ) from exc

    with tempfile.TemporaryDirectory(prefix='phantom-asr-') as tmp_dir:
        audio_path = os.path.join(tmp_dir, 'audio.wav')
        _extract_audio(media_path, audio_path, ffmpeg_path=ffmpeg_path)
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            audio_path,
            task='transcribe',
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=float(segment.start),
                end_seconds=max(float(segment.end), float(segment.start) + 0.1),
                source_text=str(segment.text or '').strip(),
            )
            for index, segment in enumerate(segments, start=1)
            if str(segment.text or '').strip()
        ]
    if not events:
        raise AudioTranscriptionError('audio transcription produced no subtitle events')
    detected_language = normalize_asr_language(getattr(info, 'language', None))
    return AudioTranscriptionResult(
        events=events,
        language=detected_language,
        language_probability=getattr(info, 'language_probability', None),
        duration=getattr(info, 'duration', None),
        model_size=model_size,
    )


def _extract_audio(media_path: str, audio_path: str, *, ffmpeg_path: str) -> None:
    command = [
        ffmpeg_path,
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-i',
        media_path,
        '-vn',
        '-ac',
        '1',
        '-ar',
        '16000',
        '-f',
        'wav',
        audio_path,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=None)
    except FileNotFoundError as exc:
        raise AudioTranscriptionError('ffmpeg not found; install ffmpeg or pass --ffmpeg-path') from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise AudioTranscriptionError(f'ffmpeg audio extraction failed: {detail}') from exc
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= 44:
        raise AudioTranscriptionError('ffmpeg audio extraction produced no audio')


def _ensure_pkg_resources_compat() -> None:
    if 'pkg_resources' in sys.modules:
        return
    try:
        import pkg_resources  # noqa: F401
        return
    except ImportError:
        pass

    module = types.ModuleType('pkg_resources')

    def resource_filename(package_or_requirement: str, resource_name: str) -> str:
        package_name = str(package_or_requirement).split('[', 1)[0]
        package = __import__(package_name)
        package_path = os.path.dirname(os.path.abspath(package.__file__))
        return os.path.join(package_path, resource_name) if resource_name else package_path

    module.resource_filename = resource_filename
    sys.modules['pkg_resources'] = module
