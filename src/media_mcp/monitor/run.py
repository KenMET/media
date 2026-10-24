#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download monitor entrypoint.

The monitor owns qBittorrent polling and orchestration. Media and subtitle
agents remain independently runnable services.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from multiprocessing import Process, Queue

if __package__ in {None, ''}:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from media_mcp import logging_utils as log
from media_mcp.ingest.run import process_media, set_logger
from media_mcp.monitor.qbittorrent import MediaMonitor


py_dir = os.path.dirname(os.path.realpath(__file__))
log_name = 'MediaMonitor'


def main(args: argparse.Namespace) -> None:
    log_level = 'debug' if args.debug else 'info'
    log.init('%s/../../log' % (py_dir), log_name, log_mode='a', log_level=log_level, console_enable=True)
    logger = log.get(log_name)
    logger.info('Logger Create Success')
    logger.info('Logger level set to %s', log_level)
    set_logger(logger)
    # Docker restarts retain /tmp in the same container. Old heartbeats must
    # never make a new startup gate look ready before its workers have started.
    from pathlib import Path
    health_root = Path(os.environ.get('MEDIA_HEALTH_DIR','/tmp/phantom-media-health'))
    for name in ('monitor','ingest','subtitle'):
        (health_root/name).unlink(missing_ok=True)

    from media_mcp.runtime.state import MediaJobs
    from media_mcp.runtime.worker import run_worker
    q = Queue(maxsize=100)
    jobs = None if args.dry_run else MediaJobs()
    if jobs:
        jobs.initialize()
    processes = []

    def start_workers():
        if args.dry_run:
            processes.append(Process(target=process_media, args=(q, args.test, True)))
        else:
            processes.extend(Process(target=run_worker, args=(stage, args.test)) for stage in ('ingest', 'subtitle'))
        for process in processes:
            process.start()

    def check_workers():
        if any(not process.is_alive() for process in processes):
            raise RuntimeError('media_worker_exited')

    try:
        monitor = MediaMonitor(q, logger, jobs=jobs, on_ready=start_workers, check_workers=check_workers)
        monitor.run()
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download monitor agent')
    parser.add_argument('--test', action='store_true', default=False, help='Disable notifications from media batch handling')
    parser.add_argument('--debug', action='store_true', default=False, help='Enable debug logging, default log level is info')
    parser.add_argument('--dry-run', action='store_true', default=False, help='Run media inference without creating hardlinks or writing database records')
    args = parser.parse_args()
    main(args)
