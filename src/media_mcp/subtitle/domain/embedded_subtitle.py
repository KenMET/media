#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embedded subtitle stream probing and container operations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from media_mcp.subtitle.domain.subtitle_file import detect_language, detect_subtitle_type, LANGUAGE_PRIORITY


CODEC_EXTENSION = {
    'subrip': '.srt',
    'ass': '.ass',
    'ssa': '.ssa',
    'webvtt': '.vtt',
    'hdmv_pgs_subtitle': '.sup',
}


class EmbeddedSubtitleProbeError(RuntimeError):
    """Raised when embedded subtitle streams cannot be inspected reliably."""


@dataclass(frozen=True)
class EmbeddedSubtitleStream:
    stream_index: int
    subtitle_ordinal: int
    codec: str
    language: str | None
    raw_language: str | None
    title: str | None
    subtitle_type: str | None
    disposition_default: bool
    disposition_forced: bool

    @property
    def preference_score(self) -> int:
        score = LANGUAGE_PRIORITY.get(self.language or '', 0)
        if self.subtitle_type == 'sdh':
            score -= 10
        if self.subtitle_type == 'commentary':
            score -= 40
        return score

    @property
    def extension(self) -> str:
        return CODEC_EXTENSION.get(self.codec, '.srt')


def ffprobe_subtitle_streams(video_path: str | None) -> list[EmbeddedSubtitleStream]:
    if not video_path or not os.path.isfile(video_path):
        raise EmbeddedSubtitleProbeError(f'video_not_found: {video_path}')
    cmd = [
        'ffprobe',
        '-v',
        'error',
        '-print_format',
        'json',
        '-show_streams',
        video_path,
    ]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise EmbeddedSubtitleProbeError(f'ffprobe_failed: {detail}') from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise EmbeddedSubtitleProbeError(f'ffprobe_failed: {exc}') from exc

    try:
        payload = json.loads(completed.stdout or '{}')
    except json.JSONDecodeError as exc:
        raise EmbeddedSubtitleProbeError(f'ffprobe_invalid_json: {exc}') from exc

    streams: list[EmbeddedSubtitleStream] = []
    subtitle_ordinal = 0
    for stream in payload.get('streams') or []:
        if stream.get('codec_type') != 'subtitle':
            continue
        subtitle_ordinal += 1
        tags = stream.get('tags') or {}
        disposition = stream.get('disposition') or {}
        raw_language = tags.get('language')
        title = tags.get('title')
        language = detect_language(' '.join(str(x or '') for x in (raw_language, title)))
        subtitle_type = detect_subtitle_type(str(title or ''), language)
        if disposition.get('forced'):
            subtitle_type = 'forced'
        streams.append(
            EmbeddedSubtitleStream(
                stream_index=int(stream.get('index')),
                subtitle_ordinal=subtitle_ordinal,
                codec=str(stream.get('codec_name') or ''),
                language=language,
                raw_language=raw_language,
                title=title,
                subtitle_type=subtitle_type,
                disposition_default=bool(disposition.get('default')),
                disposition_forced=bool(disposition.get('forced')),
            )
        )
    return streams


def _mkv_track_uids(
    video_path: str,
    selected: EmbeddedSubtitleStream,
) -> tuple[list[int], int | None, str]:
    if not shutil.which('mkvmerge'):
        return [], None, 'mkvmerge_missing'
    try:
        completed = subprocess.run(
            ['mkvmerge', '-J', video_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload = json.loads(completed.stdout or '{}')
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return [], None, f'mkvmerge_failed: {detail}'
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return [], None, f'mkvmerge_failed: {exc}'

    subtitle_tracks = [track for track in payload.get('tracks') or [] if track.get('type') == 'subtitles']
    all_uids = [
        int(item.get('properties', {}).get('uid'))
        for item in subtitle_tracks
        if item.get('properties', {}).get('uid') is not None
    ]
    if len(all_uids) != len(subtitle_tracks):
        return [], None, 'track_uid_missing'

    ordinal_index = selected.subtitle_ordinal - 1
    if 0 <= ordinal_index < len(subtitle_tracks):
        track_uid = subtitle_tracks[ordinal_index].get('properties', {}).get('uid')
        if track_uid is not None:
            return all_uids, int(track_uid), 'track_mapped_by_ordinal'

    matches = []
    for track in subtitle_tracks:
        properties = track.get('properties') or {}
        track_language = detect_language(
            ' '.join(
                str(value or '')
                for value in (
                    properties.get('language'),
                    properties.get('language_ietf'),
                    properties.get('track_name'),
                )
            )
        )
        if selected.language and track_language != selected.language:
            continue
        if selected.title and properties.get('track_name') != selected.title:
            continue
        matches.append(track)
    if len(matches) != 1:
        return [], None, 'track_mapping_ambiguous'
    track_uid = matches[0].get('properties', {}).get('uid')
    return all_uids, int(track_uid), 'track_mapped'


def select_preferred_embedded(streams: list[EmbeddedSubtitleStream]) -> EmbeddedSubtitleStream | None:
    valid = [stream for stream in streams if stream.preference_score > 0]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda item: (
            item.preference_score,
            1 if item.disposition_default else 0,
            -item.subtitle_ordinal,
        ),
        reverse=True,
    )[0]


def set_mkv_default_subtitle(video_path: str, selected: EmbeddedSubtitleStream) -> tuple[bool, str]:
    # In-place edits change every hardlink, including a torrent's payload.
    # Extract a sidecar instead whenever a file is shared with another path.
    try:
        if os.path.islink(video_path) or os.stat(video_path).st_nlink > 1:
            return False, 'shared_inode_must_not_be_modified'
    except OSError as exc:
        return False, f'video_stat_failed:{type(exc).__name__}'
    if os.path.splitext(video_path)[1].lower() != '.mkv':
        return False, 'container_not_mkv'
    if not shutil.which('mkvpropedit'):
        return False, 'mkvpropedit_missing'

    try:
        streams = ffprobe_subtitle_streams(video_path)
    except EmbeddedSubtitleProbeError as exc:
        return False, str(exc)
    if not streams:
        return False, 'no_subtitle_streams'
    selected_is_default = False
    other_defaults = False
    for stream in streams:
        if stream.subtitle_ordinal == selected.subtitle_ordinal:
            selected_is_default = stream.disposition_default
        elif stream.disposition_default:
            other_defaults = True
    if selected_is_default and not other_defaults:
        return True, 'embedded_default_already_set'

    subtitle_uids, selected_uid, mapping_reason = _mkv_track_uids(video_path, selected)
    if selected_uid is None:
        return False, mapping_reason

    args = ['mkvpropedit', video_path]
    for track_uid in subtitle_uids:
        args.extend(['--edit', f'track:={track_uid}', '--set', 'flag-default=0'])
    args.extend(['--edit', f'track:={selected_uid}', '--set', 'flag-default=1'])

    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=60)
    except subprocess.CalledProcessError as exc:
        return False, f'mkvpropedit_failed: {(exc.stderr or exc.stdout or str(exc)).strip()}'
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f'mkvpropedit_failed: {exc}'

    try:
        verified = ffprobe_subtitle_streams(video_path)
    except EmbeddedSubtitleProbeError as exc:
        return False, f'default_flag_verify_failed: {exc}'
    for stream in verified:
        if stream.subtitle_ordinal == selected.subtitle_ordinal and stream.disposition_default:
            return True, 'embedded_default_set'
    return False, 'default_flag_verify_failed'


def extract_embedded_subtitle(video_path: str, stream: EmbeddedSubtitleStream, target_path: str) -> tuple[bool, str]:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    extension = os.path.splitext(target_path)[1]
    output_format = {'.srt':'srt','.ass':'ass','.ssa':'ass','.vtt':'webvtt','.sup':'sup'}.get(extension.lower())
    if not output_format:
        return False, 'unsupported_subtitle_output_format'
    try:
        with tempfile.TemporaryDirectory(prefix='.subtitle-',dir=os.path.dirname(target_path)) as staging:
            temporary = os.path.join(staging,'output.part')
            cmd = ['ffmpeg','-y','-i',video_path,'-map',f'0:{stream.stream_index}','-c:s','copy','-f',output_format,temporary]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            if not os.path.isfile(temporary) or os.path.getsize(temporary)==0:
                return False, 'ffmpeg_extract_missing_or_empty_target'
            # Publish only complete output without overwriting an existing sidecar.
            from media_mcp.runtime.state import assert_mutation_lock
            assert_mutation_lock()
            os.link(temporary,target_path)
            return True, 'embedded_extracted'
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f'ffmpeg_extract_failed:{type(exc).__name__}'


def sample_embedded_subtitle(video_path: str, stream: EmbeddedSubtitleStream, limit: int = 40) -> list[str]:
    if not video_path or not os.path.isfile(video_path):
        return []
    cmd = [
        'ffmpeg',
        '-v',
        'error',
        '-i',
        video_path,
        '-map',
        f'0:{stream.stream_index}',
        '-f',
        'srt',
        '-',
    ]
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []

    lines: list[str] = []
    for line in (completed.stdout or '').splitlines():
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    if len(lines) <= limit:
        return lines
    if limit <= 1:
        return lines[:limit]

    # Sample across the whole subtitle so credits or an unusual opening do not
    # decide between otherwise similar tracks.
    indices = {
        round(position * (len(lines) - 1) / (limit - 1))
        for position in range(limit)
    }
    return [lines[index] for index in sorted(indices)]
