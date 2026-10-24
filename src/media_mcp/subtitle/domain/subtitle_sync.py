#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio-referenced subtitle synchronization helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


class SubtitleSyncError(RuntimeError):
    """Raised when subtitle synchronization was attempted but failed."""


@dataclass(frozen=True)
class SubtitleSyncResult:
    applied: bool
    output_path: str
    reason: str


def sync_subtitle_to_audio(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    *,
    binary: str = 'ffsubsync',
    timeout_seconds: int = 600,
) -> SubtitleSyncResult:
    executable = shutil.which(binary)
    if not executable:
        return SubtitleSyncResult(False, subtitle_path, 'ffsubsync_unavailable')
    if not os.path.isfile(video_path):
        raise SubtitleSyncError(f'video_not_found: {video_path}')
    if not os.path.isfile(subtitle_path):
        raise SubtitleSyncError(f'subtitle_not_found: {subtitle_path}')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    command = [
        executable,
        video_path,
        '-i',
        subtitle_path,
        '-o',
        output_path,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubtitleSyncError(f'ffsubsync_timeout_after_{timeout_seconds}s') from exc
    except OSError as exc:
        raise SubtitleSyncError(f'ffsubsync_start_failed: {exc}') from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        raise SubtitleSyncError(f'ffsubsync_failed: {detail or completed.returncode}')
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise SubtitleSyncError('ffsubsync_output_missing')
    return SubtitleSyncResult(True, output_path, 'ffsubsync')
