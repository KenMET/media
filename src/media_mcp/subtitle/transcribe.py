#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone audio transcription CLI for subtitle smoke tests."""

from __future__ import annotations

import argparse
import logging
import os
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from media_mcp.subtitle.domain.audio_transcription import (
    AudioTranscriptionError,
    build_asr_sidecar_path,
    transcribe_audio,
    write_srt,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Transcribe media audio to SRT with faster-whisper')
    parser.add_argument('--path', required=True, help='Input audio or video path')
    parser.add_argument('--output', default=None, help='Output SRT path. Defaults to <input>.asr.<language>.srt')
    parser.add_argument('--model-size', default=os.environ.get('SUBTITLE_ASR_MODEL', 'small'))
    parser.add_argument('--language', default=os.environ.get('SUBTITLE_ASR_LANGUAGE') or None)
    parser.add_argument('--device', default=os.environ.get('SUBTITLE_ASR_DEVICE', 'cpu'))
    parser.add_argument('--compute-type', default=os.environ.get('SUBTITLE_ASR_COMPUTE_TYPE', 'int8'))
    parser.add_argument('--beam-size', type=int, default=int(os.environ.get('SUBTITLE_ASR_BEAM_SIZE', '5')))
    parser.add_argument('--disable-vad', action='store_true', default=False)
    parser.add_argument('--ffmpeg-path', default=os.environ.get('FFMPEG_PATH', 'ffmpeg'))
    return parser


def main(args: argparse.Namespace | None = None) -> None:
    parser = build_parser()
    args = args or parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger('AudioTranscription')
    try:
        result = transcribe_audio(
            args.path,
            model_size=args.model_size,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            vad_filter=not args.disable_vad,
            ffmpeg_path=args.ffmpeg_path,
        )
    except AudioTranscriptionError as exc:
        logger.error('ASR failed: %s', exc)
        raise SystemExit(2) from exc

    output = args.output or build_asr_sidecar_path(args.path, result.language)
    write_srt(output, result.events)
    logger.info(
        'ASR complete: events=%d language=%s probability=%s output=%s',
        len(result.events),
        result.language or 'unknown',
        f'{result.language_probability:.3f}' if result.language_probability is not None else '-',
        output,
    )


if __name__ == '__main__':
    main()
