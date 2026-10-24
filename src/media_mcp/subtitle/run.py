#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""User-facing entrypoint for subtitle processing."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))


def _init_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
    )


def _log_dependency_status() -> set[str]:
    logger = logging.getLogger('SubtitleAgent')
    dependencies = (
        ('ffprobe', True, 'required for embedded subtitle probing'),
        ('ffmpeg', False, 'required for embedded subtitle extraction fallback'),
        ('mkvpropedit', False, 'optional for setting mkv default subtitle track'),
        ('mkvmerge', False, 'optional for safely mapping mkv subtitle track ids'),
    )
    missing_required: set[str] = set()
    for binary, required, purpose in dependencies:
        path = shutil.which(binary)
        if not path:
            logger.warning('Dependency missing: %s (%s)', binary, purpose)
            if required:
                missing_required.add(binary)
    return missing_required


def _fail_on_missing_required_dependencies(missing_required: set[str]):
    if not missing_required:
        return
    logging.getLogger('SubtitleAgent').error(
        'Abort: missing required dependency %s. Install required tools before running subtitle agent.',
        ','.join(sorted(missing_required)),
    )
    raise SystemExit(2)


def scan_selected_paths(agent, paths: list[str], dry_run: bool = False):
    total_handled = total_missing = total_review = total_failed = 0
    for path in paths:
        handled, missing, review, failed = agent.run_path(path, test_mode=dry_run)
        total_handled += handled
        total_missing += missing
        total_review += review
        total_failed += failed
    if len(paths) > 1:
        logging.getLogger('SubtitleAgent').info(
            'Total: handled=%d, missing=%d, review=%d, failed=%d',
            total_handled,
            total_missing,
            total_review,
            total_failed,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Subtitle agent')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Only inspect media and print planned actions; do not write files or database rows',
    )
    parser.add_argument(
        '--path',
        action='append',
        default=None,
        help='Scan file/folder path. Relative paths resolve under /data/downloads.',
    )
    parser.add_argument(
        '--disable-agent',
        action='store_true',
        default=False,
        help='Disable all Codex calls. Keep local/provider processing and skip AI translation.',
    )
    parser.add_argument(
        '--disable-opensubtitle',
        action='store_true',
        default=False,
        help='Use local subtitle processing only. Skip online providers and all Codex calls.',
    )
    return parser


def main(args: argparse.Namespace | None = None):
    parser = build_parser()
    args = args or parser.parse_args()
    _init_logging()
    _fail_on_missing_required_dependencies(_log_dependency_status())

    from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent

    disable_agent = bool(getattr(args, 'disable_agent', False))
    disable_opensubtitle = bool(getattr(args, 'disable_opensubtitle', False))
    agent = SubtitleAgent(
        disable_agent=disable_agent,
        disable_opensubtitle=disable_opensubtitle,
    )
    if args.path:
        if disable_opensubtitle:
            opensubtitle_status = 'disabled'
        elif agent.provider_registry.providers:
            opensubtitle_status = 'configured'
        else:
            opensubtitle_status = 'unconfigured'
        logging.getLogger('SubtitleAgent').info(
            'Run: %s, paths=%d, agent=%s, opensubtitle=%s',
            'dry-run' if args.dry_run else 'apply',
            len(args.path),
            'disabled' if disable_agent or disable_opensubtitle else 'enabled',
            opensubtitle_status,
        )
        scan_selected_paths(agent, args.path, dry_run=bool(args.dry_run))
        return
    logging.getLogger('SubtitleAgent').info('No task specified. Use --path.')


if __name__ == '__main__':
    main()
