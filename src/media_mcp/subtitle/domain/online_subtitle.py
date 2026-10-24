#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validation and decoding for downloaded online subtitles."""

from __future__ import annotations

import gzip
import io
import os
import zipfile
import re
from dataclasses import dataclass

from media_mcp.subtitle.domain.subtitle_file import analyze_subtitle_sample
from media_mcp.subtitle.domain.translation import parse_text_subtitle_content


MAX_SUBTITLE_BYTES = 10 * 1024 * 1024
TEXT_SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt'}


@dataclass(frozen=True)
class ValidatedOnlineSubtitle:
    content: bytes
    extension: str
    encoding: str
    profile: dict


def _chinese_character_count(content: bytes) -> int:
    try:
        text, _ = _decode_text(content)
    except ValueError:
        return 0
    return sum('\u3400' <= char <= '\u9fff' for char in text)


def _extract_archive(content: bytes, file_name: str, *, prefer_chinese: bool = True) -> tuple[bytes, str]:
    if content.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and os.path.splitext(item.filename)[1].lower() in TEXT_SUBTITLE_EXTENSIONS
                and item.file_size <= MAX_SUBTITLE_BYTES
            ]
            if not members:
                raise ValueError('archive contains no supported subtitle file')
            if len(members)>100 or sum(item.file_size for item in members)>MAX_SUBTITLE_BYTES*4:
                raise ValueError('subtitle archive exceeds aggregate extraction limit')
            extracted_members: list[tuple[int, int, str, bytes]] = []
            for member in members:
                with archive.open(member) as handle:
                    extracted = handle.read(MAX_SUBTITLE_BYTES + 1)
                if len(extracted) > MAX_SUBTITLE_BYTES:
                    continue
                priority = _chinese_character_count(extracted) if prefer_chinese else 0
                extracted_members.append(
                    (
                        priority,
                        member.file_size,
                        member.filename,
                        extracted,
                    )
                )
            if not extracted_members:
                raise ValueError('archive contains no readable subtitle file')
            extracted_members.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            _, _, selected_name, extracted = extracted_members[0]
            if len(extracted) > MAX_SUBTITLE_BYTES:
                raise ValueError('archived subtitle exceeds size limit')
            return extracted, selected_name
    if content.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as handle:
            extracted = handle.read(MAX_SUBTITLE_BYTES + 1)
        if len(extracted) > MAX_SUBTITLE_BYTES:
            raise ValueError('compressed subtitle exceeds size limit')
        return extracted, os.path.splitext(file_name)[0]
    return content, file_name


def _decode_text(content: bytes) -> tuple[str, str]:
    if content.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        encodings = ('utf-32', 'utf-8-sig', 'utf-8', 'gb18030', 'big5')
    elif content.startswith((b'\xff\xfe', b'\xfe\xff')):
        encodings = ('utf-16', 'utf-8-sig', 'utf-8', 'gb18030', 'big5')
    else:
        encodings = ('utf-8-sig', 'utf-8', 'utf-16', 'gb18030', 'big5')
    for encoding in encodings:
        try:
            return content.decode(encoding), encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError('subtitle text encoding is unsupported')


def _validate_text_subtitle_payload(
    content: bytes,
    file_name: str,
    *,
    require_chinese: bool,
) -> ValidatedOnlineSubtitle:
    content, extracted_name = _extract_archive(content, file_name, prefer_chinese=require_chinese)
    if not content:
        raise ValueError('downloaded subtitle is empty')
    if len(content) > MAX_SUBTITLE_BYTES:
        raise ValueError('downloaded subtitle exceeds size limit')

    extension = os.path.splitext(extracted_name)[1].lower()
    if extension not in TEXT_SUBTITLE_EXTENSIONS:
        extension = '.srt'
    text, encoding = _decode_text(content)
    events = parse_text_subtitle_content(text, extension)
    lines = [event.source_text for event in events]
    profile = analyze_subtitle_sample(lines)
    chinese_events = sum(bool(re.search(r'[\u3400-\u9fff]', line)) for line in lines)
    coverage = chinese_events / len(lines) if lines else 0.0
    profile.update(dialogue_events=len(lines), chinese_dialogue_events=chinese_events,
                   chinese_dialogue_coverage=round(coverage, 4))
    if require_chinese and int(profile.get('chinese_chars') or 0) < 10:
        raise ValueError(
            'downloaded subtitle does not contain enough Chinese text '
            f'(file={extracted_name}, encoding={encoding}, bytes={len(content)}, '
            f'chinese_chars={profile.get("chinese_chars") or 0}, '
            f'dialogue_lines={profile.get("dialogue_lines") or 0})'
        )
    if require_chinese and coverage < 0.3:
        raise ValueError(f'Chinese dialogue coverage too low: {chinese_events}/{len(lines)}')
    if int(profile.get('dialogue_lines') or 0) < 5:
        raise ValueError('downloaded subtitle has too few dialogue lines')
    normalized = text.encode('utf-8')
    return ValidatedOnlineSubtitle(
        content=normalized,
        extension=extension,
        encoding=encoding,
        profile=profile,
    )


def validate_online_subtitle(content: bytes, file_name: str) -> ValidatedOnlineSubtitle:
    return _validate_text_subtitle_payload(content, file_name, require_chinese=True)


def validate_online_translation_source(content: bytes, file_name: str) -> ValidatedOnlineSubtitle:
    return _validate_text_subtitle_payload(content, file_name, require_chinese=False)
