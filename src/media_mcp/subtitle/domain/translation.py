#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse text subtitles, translate dialogue in batches, and render bilingual ASS."""

from __future__ import annotations

import html
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_BATCH_EVENTS = 160
DEFAULT_BATCH_CHARACTERS = 12000
DEFAULT_BATCH_TOKENS = 0
DEFAULT_WARN_TRANSLATION_EVENTS = 4000
DEFAULT_MAX_TRANSLATION_EVENTS = 12000
DEFAULT_WARN_EVENTS_PER_MINUTE = 65.0
DEFAULT_MAX_EVENTS_PER_MINUTE = 120.0
DEFAULT_INCOMPLETE_RETRIES = 2

logger = logging.getLogger('SubtitleAgent')


class SubtitleTranslationError(RuntimeError):
    """Raised when a subtitle cannot be parsed or translated safely."""


@dataclass(frozen=True)
class SubtitleEvent:
    index: int
    start_seconds: float
    end_seconds: float
    source_text: str


def _decode_subtitle(path: str) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'shift_jis', 'latin-1'):
        try:
            with open(path, 'r', encoding=encoding, errors='strict') as handle:
                return handle.read()
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise SubtitleTranslationError(f'failed to read subtitle: {exc}') from exc
    raise SubtitleTranslationError('unsupported subtitle encoding')


def _timestamp_seconds(value: str) -> float:
    normalized = value.strip().replace(',', '.')
    parts = normalized.split(':')
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f'invalid timestamp: {value}')
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace('\\N', '\n').replace('\\n', '\n').replace('\\h', ' ')
    value = re.sub(r'\{[^}]*\}', '', value)
    value = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    value = re.sub(r'<[^>]+>', '', value)
    lines = [re.sub(r'\s+', ' ', line).strip() for line in value.splitlines()]
    return '\n'.join(line for line in lines if line).strip()


def _parse_srt_or_vtt(content: str) -> list[SubtitleEvent]:
    timestamp = re.compile(
        r'(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*'
        r'(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})'
    )
    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    events: list[SubtitleEvent] = []
    position = 0
    while position < len(lines):
        match = timestamp.search(lines[position])
        if not match:
            position += 1
            continue
        position += 1
        text_lines: list[str] = []
        while position < len(lines) and lines[position].strip():
            text_lines.append(lines[position])
            position += 1
        text = _clean_text('\n'.join(text_lines))
        if text:
            events.append(
                SubtitleEvent(
                    index=len(events) + 1,
                    start_seconds=_timestamp_seconds(match.group('start')),
                    end_seconds=_timestamp_seconds(match.group('end')),
                    source_text=text,
                )
            )
        position += 1
    return events


def _parse_ass(content: str) -> list[SubtitleEvent]:
    parsed: list[tuple[float, float, str]] = []
    in_events = False
    format_fields: list[str] = []
    for raw_line in content.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw_line.strip()
        if line.startswith('['):
            in_events = line.lower() == '[events]'
            continue
        if not in_events:
            continue
        if line.lower().startswith('format:'):
            format_fields = [item.strip().lower() for item in line.split(':', 1)[1].split(',')]
            continue
        if not line.lower().startswith('dialogue:'):
            continue
        fields = format_fields or [
            'layer', 'start', 'end', 'style', 'name',
            'marginl', 'marginr', 'marginv', 'effect', 'text',
        ]
        values = line.split(':', 1)[1].lstrip().split(',', len(fields) - 1)
        if len(values) != len(fields):
            continue
        row = dict(zip(fields, values))
        try:
            start = _timestamp_seconds(row['start'])
            end = _timestamp_seconds(row['end'])
        except (KeyError, ValueError):
            continue
        style = str(row.get('style') or '').strip().lower()
        effect = str(row.get('effect') or '').strip().lower()
        if any(
            marker in style
            for marker in ('sign', 'title', 'credit', 'logo', 'karaoke', 'song', 'opening', 'ending')
        ):
            continue
        if re.search(r'(?:^|[^a-z0-9])(?:op|ed|fx)(?:$|[^a-z0-9])', style):
            continue
        if effect and any(marker in effect for marker in ('karaoke', 'scroll', 'banner')):
            continue
        text = _clean_text(row.get('text', ''))
        if text:
            parsed.append((start, end, text))

    parsed.sort(key=lambda item: (item[0], item[1], item[2]))
    deduped: list[tuple[float, float, str]] = []
    last_by_text: dict[str, tuple[float, float]] = {}
    for start, end, text in parsed:
        normalized = re.sub(r'\s+', ' ', text).strip().lower()
        previous = last_by_text.get(normalized)
        if previous:
            overlap = max(0.0, min(end, previous[1]) - max(start, previous[0]))
            shorter_duration = min(max(end - start, 0.01), max(previous[1] - previous[0], 0.01))
            if overlap / shorter_duration >= 0.8:
                continue
        deduped.append((start, end, text))
        last_by_text[normalized] = (start, end)

    return [
        SubtitleEvent(
            index=index,
            start_seconds=start,
            end_seconds=end,
            source_text=text,
        )
        for index, (start, end, text) in enumerate(deduped, start=1)
    ]


def parse_text_subtitle(path: str) -> list[SubtitleEvent]:
    extension = os.path.splitext(path)[1].lower()
    content = _decode_subtitle(path)
    return parse_text_subtitle_content(content, extension)


def parse_text_subtitle_content(content: str, extension: str) -> list[SubtitleEvent]:
    """Parse dialogue only, excluding headers, styles and credit-only ASS tracks."""
    if extension in {'.srt', '.vtt'}:
        events = _parse_srt_or_vtt(content)
    elif extension in {'.ass', '.ssa'}:
        events = _parse_ass(content)
    else:
        raise SubtitleTranslationError(f'unsupported text subtitle format: {extension}')
    if not events:
        raise SubtitleTranslationError('subtitle contains no parseable dialogue events')
    return events


def validate_translation_events(
    events: list[SubtitleEvent],
    *,
    max_events: int = DEFAULT_MAX_TRANSLATION_EVENTS,
    warn_events: int = DEFAULT_WARN_TRANSLATION_EVENTS,
    max_events_per_minute: float = DEFAULT_MAX_EVENTS_PER_MINUTE,
    warn_events_per_minute: float = DEFAULT_WARN_EVENTS_PER_MINUTE,
) -> dict[str, float | int | bool]:
    event_count = len(events)
    first_start = min((event.start_seconds for event in events), default=0.0)
    last_end = max((event.end_seconds for event in events), default=0.0)
    span_seconds = max(0.0, last_end - first_start)
    span_minutes = max(span_seconds / 60.0, 1.0)
    events_per_minute = event_count / span_minutes
    event_characters = [len(event.source_text) for event in events]
    event_durations = [max(0.0, event.end_seconds - event.start_seconds) for event in events]
    average_characters = sum(event_characters) / event_count if event_count else 0.0
    max_characters = max(event_characters, default=0)
    long_event_count = sum(1 for characters in event_characters if characters > 300)
    average_duration = sum(event_durations) / event_count if event_count else 0.0
    short_event_ratio = (
        sum(1 for duration in event_durations if duration < 0.75) / event_count
        if event_count
        else 0.0
    )
    unique_events = {
        (
            round(event.start_seconds, 2),
            round(event.end_seconds, 2),
            re.sub(r'\s+', ' ', event.source_text).strip().lower(),
        )
        for event in events
    }
    duplicate_ratio = 1.0 - len(unique_events) / event_count if event_count else 0.0
    profile: dict[str, float | int | bool] = {
        'events': event_count,
        'span_seconds': round(span_seconds, 2),
        'events_per_minute': round(events_per_minute, 2),
        'duplicate_ratio': round(duplicate_ratio, 4),
        'avg_chars_per_event': round(average_characters, 2),
        'max_chars_per_event': max_characters,
        'long_event_count': long_event_count,
        'avg_duration_seconds': round(average_duration, 2),
        'short_event_ratio': round(short_event_ratio, 4),
    }
    count_warning = event_count > warn_events
    density_warning = events_per_minute > warn_events_per_minute
    profile['count_warning'] = count_warning
    profile['density_warning'] = density_warning
    if event_count > max_events:
        raise SubtitleTranslationError(
            f'translation source has implausible event count: {event_count} > {max_events}; '
            f'profile={profile}'
        )
    if events_per_minute > max_events_per_minute:
        raise SubtitleTranslationError(
            f'translation source has implausible event density: '
            f'{events_per_minute:.1f}/min > {max_events_per_minute:.1f}/min; '
            f'profile={profile}'
        )
    if density_warning:
        logger.warning(
            'Translation source has high event density: %.1f/min > %.1f/min; profile=%s',
            events_per_minute,
            warn_events_per_minute,
            profile,
        )
    if count_warning:
        logger.warning(
            'Translation source has high event count: %d > %d; profile=%s',
            event_count,
            warn_events,
            profile,
        )
    return profile


def _batch_events(
    events: list[SubtitleEvent],
    max_events: int,
    max_characters: int,
    max_tokens: int = DEFAULT_BATCH_TOKENS,
) -> list[list[SubtitleEvent]]:
    batches: list[list[SubtitleEvent]] = []
    current: list[SubtitleEvent] = []
    character_count = 0
    token_count = 0
    for event in events:
        event_characters = len(event.source_text)
        event_tokens = _estimate_event_payload_tokens(event)
        if current and (
            len(current) >= max_events
            or character_count + event_characters > max_characters
            or (max_tokens > 0 and token_count + event_tokens > max_tokens)
        ):
            batches.append(current)
            current = []
            character_count = 0
            token_count = 0
        current.append(event)
        character_count += event_characters
        token_count += event_tokens
    if current:
        batches.append(current)
    return batches


def _estimate_event_payload_tokens(event: SubtitleEvent) -> int:
    # Approximate source text tokens plus JSON/id overhead. This is deliberately
    # conservative and tokenizer-free; exact tokenization is model dependent.
    return max(1, (len(event.source_text) + 3) // 4) + 12


def _media_context_label(media_context: dict[str, Any]) -> str:
    title = (
        media_context.get('title')
        or media_context.get('media_name')
        or media_context.get('base_title')
        or 'media'
    )
    details = []
    if media_context.get('season') is not None:
        details.append(f'S{int(media_context["season"]):02d}')
    if media_context.get('episode') is not None:
        details.append(f'E{int(media_context["episode"]):02d}')
    return f'{title} {" ".join(details)}'.strip()


def translate_events(
    events: list[SubtitleEvent],
    translate_batch: Callable[[dict[str, Any]], dict[str, Any]],
    media_context: dict[str, Any],
    source_language: str | None,
    *,
    max_events: int = DEFAULT_BATCH_EVENTS,
    max_characters: int = DEFAULT_BATCH_CHARACTERS,
    max_tokens: int = DEFAULT_BATCH_TOKENS,
    incomplete_retries: int = DEFAULT_INCOMPLETE_RETRIES,
) -> list[str]:
    translations: dict[int, str] = {}
    previous_context: list[dict[str, str]] = []
    batches = _batch_events(
        events,
        max_events=max_events,
        max_characters=max_characters,
        max_tokens=max_tokens,
    )
    media_label = _media_context_label(media_context)
    event_limited_batch_count = (len(events) + max_events - 1) // max_events if max_events > 0 else len(batches)
    batch_events = [len(batch) for batch in batches]
    batch_characters = [sum(len(event.source_text) for event in batch) for batch in batches]
    batch_tokens = [sum(_estimate_event_payload_tokens(event) for event in batch) for batch in batches]
    logger.info(
        'Translation: media=%s prepared events=%d batches=%d '
        'event_limited_batches=%d token_budget=%d source_language=%s',
        media_label,
        len(events),
        len(batches),
        event_limited_batch_count,
        max_tokens,
        source_language or 'auto',
    )
    if batches:
        logger.info(
            'Translation: media=%s batch profile avg_events=%.1f max_events=%d '
            'avg_characters=%.0f max_characters=%d avg_tokens=%.0f max_tokens=%d split_by=%s',
            media_label,
            sum(batch_events) / len(batch_events),
            max(batch_events),
            sum(batch_characters) / len(batch_characters),
            max(batch_characters),
            sum(batch_tokens) / len(batch_tokens),
            max(batch_tokens),
            'content' if len(batches) > event_limited_batch_count else 'events',
        )
    completed_events = 0
    for batch_number, batch in enumerate(batches, start=1):
        batch_characters = sum(len(event.source_text) for event in batch)
        logger.info(
            'Translation: media=%s batch %d/%d started (events=%d characters=%d)',
            media_label,
            batch_number,
            len(batches),
            len(batch),
            batch_characters,
        )
        payload = {
            'mode': 'subtitle_translate',
            'target_language': 'zh-CN',
            'source_language': source_language or 'auto',
            'media': media_context,
            'batch': {
                'number': batch_number,
                'total': len(batches),
                'entries': [
                    {'id': event.index, 'source': event.source_text}
                    for event in batch
                ],
            },
            'previous_context': previous_context,
        }
        batch_results: dict[int, str] = {}
        expected_ids = {event.index for event in batch}
        pending = list(batch)
        for retry_number in range(incomplete_retries + 1):
            request_payload = payload
            if retry_number:
                request_payload = {
                    **payload,
                    'batch': {
                        **payload['batch'],
                        'retry': retry_number,
                        'entries': [
                            {'id': event.index, 'source': event.source_text}
                            for event in pending
                        ],
                    },
                    'recovered_context': [
                        {
                            'id': event.index,
                            'source': event.source_text,
                            'zh': batch_results[event.index],
                        }
                        for event in batch
                        if event.index in batch_results
                    ][-5:],
                    'retry_instructions': ('Translate only batch.entries; recovered_context is reference, not output. '
                        'Return every requested ID exactly once, including short utterances and punctuation.'),
                }
                logger.warning(
                    'Translation: batch %d/%d retrying missing ids '
                    '(attempt=%d/%d, missing=%s)',
                    batch_number,
                    len(batches),
                    retry_number,
                    incomplete_retries,
                    [event.index for event in pending],
                )
            result = translate_batch(request_payload)
            if not isinstance(result, dict) or not result.get('success'):
                error = result.get('error') if isinstance(result, dict) else None
                raise SubtitleTranslationError(error or f'translation batch {batch_number} failed')
            returned = result.get('translations')
            if not isinstance(returned, list):
                raise SubtitleTranslationError(
                    f'translation batch {batch_number} has no translations list'
                )
            pending_ids={event.index for event in pending}
            for item in returned:
                if not isinstance(item, dict):
                    continue
                try:
                    item_id = int(item.get('id'))
                except (TypeError, ValueError):
                    continue
                if item_id not in expected_ids or item_id not in pending_ids:
                    continue
                chinese = str(item.get('zh') or '').strip()
                if chinese:
                    batch_results[item_id] = chinese
            pending = [event for event in batch if event.index not in batch_results]
            if not pending:
                break
        if pending:
            missing = [event.index for event in pending]
            raise SubtitleTranslationError(
                f'translation batch {batch_number} returned incomplete ids after '
                f'{incomplete_retries} retries: {missing[:10]}'
            )
        translations.update(batch_results)
        completed_events += len(batch)
        progress = completed_events * 100 / len(events) if events else 100.0
        logger.info(
            'Translation: media=%s batch %d/%d completed (events=%d/%d progress=%.1f%%)',
            media_label,
            batch_number,
            len(batches),
            completed_events,
            len(events),
            progress,
        )
        previous_context = [
            {'source': event.source_text, 'zh': batch_results[event.index]}
            for event in batch[-5:]
        ]
    return [translations[event.index] for event in events]


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f'{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}'


def _ass_text(value: str) -> str:
    value = value.replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}')
    return r'\N'.join(line.strip() for line in value.splitlines() if line.strip())


def render_bilingual_ass(
    events: list[SubtitleEvent],
    translations: list[str],
    *,
    chinese_font_size: int = 68,
    source_font_size: int = 46,
    bottom_margin: int = 18,
) -> str:
    if len(events) != len(translations):
        raise SubtitleTranslationError('event and translation counts do not match')
    header = f"""[Script Info]
Title: AI translated bilingual subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,Arial,{chinese_font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2.8,0.8,2,70,70,{bottom_margin},1
Style: Source,Arial,{source_font_size},&H00D8D8D8,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2.2,0.6,2,80,80,{bottom_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue: list[str] = []
    for event, chinese in zip(events, translations):
        start = _ass_time(event.start_seconds)
        end = _ass_time(event.end_seconds)
        bilingual_text = (
            f'{_ass_text(chinese)}'
            rf'\N{{\rSource}}'
            f'{_ass_text(event.source_text)}'
        )
        dialogue.append(f'Dialogue: 0,{start},{end},Chinese,,0,0,0,,{bilingual_text}')
    return header + '\n'.join(dialogue) + '\n'


def render_chinese_ass(
    events: list[SubtitleEvent],
    translations: list[str],
    *,
    chinese_font_size: int = 68,
    bottom_margin: int = 18,
) -> str:
    if len(events) != len(translations):
        raise SubtitleTranslationError('event and translation counts do not match')
    header = f"""[Script Info]
Title: AI translated Chinese subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,Arial,{chinese_font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2.8,0.8,2,70,70,{bottom_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue: list[str] = []
    for event, chinese in zip(events, translations):
        start = _ass_time(event.start_seconds)
        end = _ass_time(event.end_seconds)
        dialogue.append(f'Dialogue: 0,{start},{end},Chinese,,0,0,0,,{_ass_text(chinese)}')
    return header + '\n'.join(dialogue) + '\n'


def restyle_bilingual_ass(
    path: str,
    *,
    chinese_font_size: int = 68,
    source_font_size: int = 46,
    bottom_margin: int = 18,
) -> bool:
    try:
        content = _decode_subtitle(path)
    except OSError:
        return False
    if 'Title: AI translated bilingual subtitle' not in content:
        return False

    chinese_style = (
        f'Style: Chinese,Arial,{chinese_font_size},&H00FFFFFF,&H000000FF,'
        f'&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,2.8,0.8,2,'
        f'70,70,{bottom_margin},1'
    )
    source_style = (
        f'Style: Source,Arial,{source_font_size},&H00D8D8D8,&H000000FF,'
        f'&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2.2,0.6,2,'
        f'80,80,{bottom_margin},1'
    )
    updated = re.sub(r'^Style: Chinese,.*$', chinese_style, content, flags=re.MULTILINE)
    updated = re.sub(r'^Style: Source,.*$', source_style, updated, flags=re.MULTILINE)
    if updated == content:
        return False
    write_text_atomic(path, updated)
    return True


def write_text_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='.subtitle-',dir=os.path.dirname(path)) as staging:
            temporary_path = os.path.join(staging,'output.part')
            with open(temporary_path, 'x', encoding='utf-8', newline='\n') as handle:
                handle.write(content)
            os.replace(temporary_path, path)
    except OSError as exc:
        raise SubtitleTranslationError(f'failed to write translated subtitle: {exc}') from exc
