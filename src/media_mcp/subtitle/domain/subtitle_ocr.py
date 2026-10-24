#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR helpers for image-based embedded subtitles."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from media_mcp.subtitle.domain.embedded_subtitle import (
    EmbeddedSubtitleStream,
    extract_embedded_subtitle,
)


PGS_CODECS = {'hdmv_pgs_subtitle'}

TESSERACT_LANGUAGE_ALIASES = {
    'en': 'eng',
    'eng': 'eng',
    'english': 'eng',
    'ja': 'jpn',
    'jp': 'jpn',
    'jpn': 'jpn',
    'japanese': 'jpn',
    'ko': 'kor',
    'kr': 'kor',
    'kor': 'kor',
    'korean': 'kor',
    'fr': 'fra',
    'fre': 'fra',
    'fra': 'fra',
    'french': 'fra',
    'de': 'deu',
    'ger': 'deu',
    'deu': 'deu',
    'german': 'deu',
    'es': 'spa',
    'spa': 'spa',
    'spanish': 'spa',
    'ru': 'rus',
    'rus': 'rus',
    'russian': 'rus',
    'it': 'ita',
    'ita': 'ita',
    'italian': 'ita',
    'pt': 'por',
    'por': 'por',
    'portuguese': 'por',
    'nl': 'nld',
    'dut': 'nld',
    'nld': 'nld',
    'dutch': 'nld',
    'pl': 'pol',
    'pol': 'pol',
    'polish': 'pol',
}


@dataclass(frozen=True)
class PgsToSrtCommand:
    args: list[str]
    cwd: str | None
    description: str


def is_ocr_supported_stream(stream: EmbeddedSubtitleStream) -> bool:
    return stream.codec in PGS_CODECS or stream.extension == '.sup'


def _normalize_tesseract_language(language: str | None) -> str | None:
    if not language:
        return None
    value = language.strip().replace('_', '-').lower()
    value = value.split('-', 1)[0]
    return TESSERACT_LANGUAGE_ALIASES.get(value, value or None)


def _resolve_pgstosrt_command() -> PgsToSrtCommand | None:
    for name in ('PgsToSrt', 'pgstosrt'):
        binary = shutil.which(name)
        if binary:
            return PgsToSrtCommand([binary], os.path.dirname(binary) or None, name)

    dll_candidates = [
        '/opt/PgsToSrt/PgsToSrt.dll',
        '/opt/pgstosrt/PgsToSrt.dll',
        '/usr/local/share/PgsToSrt/PgsToSrt.dll',
        '/usr/local/lib/PgsToSrt/PgsToSrt.dll',
        '/usr/share/PgsToSrt/PgsToSrt.dll',
    ]
    dotnet = shutil.which('dotnet')
    if not dotnet:
        return None
    for dll_path in dll_candidates:
        if os.path.isfile(dll_path):
            return PgsToSrtCommand(
                [dotnet, dll_path],
                os.path.dirname(dll_path) or None,
                f'dotnet {dll_path}',
            )
    return None


def _resolve_tesseract_data_path(command: PgsToSrtCommand) -> str | None:
    candidates = []
    if command.cwd:
        candidates.append(os.path.join(command.cwd, 'tessdata'))
    candidates.extend(
        [
            '/usr/share/tesseract-ocr/5/tessdata',
            '/usr/share/tesseract-ocr/4.00/tessdata',
            '/usr/share/tessdata',
            '/usr/local/share/tessdata',
        ]
    )
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def ocr_embedded_pgs_to_srt(
    video_path: str | None,
    stream: EmbeddedSubtitleStream,
    output_path: str,
    *,
    language: str | None = None,
    timeout_seconds: int = 1800,
) -> tuple[bool, str]:
    if not video_path or not os.path.isfile(video_path):
        return False, f'video_not_found: {video_path}'
    if not is_ocr_supported_stream(stream):
        return False, f'unsupported_ocr_codec: {stream.codec or stream.extension}'

    command = _resolve_pgstosrt_command()
    if command is None:
        return False, 'pgstosrt_missing'

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    stem, _ = os.path.splitext(output_path)
    sup_path = f'{stem}.sup'
    part_path = f'{output_path}.part'
    for path in (sup_path, part_path, output_path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            return False, f'ocr_cleanup_failed: {exc}'

    ok, reason = extract_embedded_subtitle(video_path, stream, sup_path)
    if not ok:
        return False, reason

    tesseract_language = _normalize_tesseract_language(
        language or stream.language or stream.raw_language
    )
    args = [
        *command.args,
        '--input',
        sup_path,
        '--output',
        part_path,
        '--tesseractversion',
        '5',
    ]
    if tesseract_language:
        args.extend(['--tesseractlanguage', tesseract_language])
    tesseract_data = _resolve_tesseract_data_path(command)
    if tesseract_data:
        args.extend(['--tesseractdata', tesseract_data])

    try:
        subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=command.cwd,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, f'pgstosrt_failed: {detail}'
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f'pgstosrt_failed: {exc}'
    finally:
        try:
            if os.path.exists(sup_path):
                os.remove(sup_path)
        except OSError:
            pass

    if not os.path.isfile(part_path) or os.path.getsize(part_path) <= 0:
        return False, 'pgstosrt_empty_output'
    try:
        os.replace(part_path, output_path)
    except OSError as exc:
        return False, f'pgstosrt_output_replace_failed: {exc}'
    return True, f'embedded_ocr=pgstosrt; language={tesseract_language or "auto"}'
