#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qBittorrent completion monitor for agent orchestration."""

from __future__ import annotations

import os
import signal
import sys
import time
from multiprocessing import Queue
from typing import Set

import qbittorrentapi

from media_mcp.adapters.dispatch import mcp_direct_call_ns
from media_mcp.ingest.clients.codex import CodexMediaClient

def _default_conn() -> dict:
    port = os.environ.get('LOCAL_QBITTORRENT_PORT')
    if not port:
        raise RuntimeError('LOCAL_QBITTORRENT_PORT must be set before starting MediaMonitor')
    return {
        'host': os.environ.get('LOCAL_QBITTORRENT_HOST', 'localhost'),
        'port': int(port),
        'username': os.environ.get('LOCAL_QBITTORRENT_USERNAME', 'admin'),
        'password': os.environ.get('LOCAL_QBITTORRENT_PASSWORD', 'adminadmin'),
    }


DEFAULT_POLL_INTERVAL = 5
DEFAULT_FILTER_CATEGORY = None
DEFAULT_FILTER_TAGS: set[str] = set()


class MediaMonitor:
    def __init__(
        self,
        q: Queue,
        logger,
        conn_dict: dict | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        filter_category: str | None = DEFAULT_FILTER_CATEGORY,
        filter_tags: set[str] | None = None,
        jobs=None,
        on_ready=None,
        check_workers=None,
    ):
        self.jobs = jobs
        self.on_ready = on_ready
        self.check_workers = check_workers
        self.client = None
        self.completed_seen: Set[str] = set()
        self._completed_deliveries: dict[str,str] = {}
        self.in_progress_hashes: Set[str] = set()
        self.stop = False
        self.queue = q
        self.logger = logger
        self.conn_dict = conn_dict or _default_conn()
        self.poll_interval = poll_interval
        self.filter_category = filter_category
        self.filter_tags = filter_tags or DEFAULT_FILTER_TAGS

        signal.signal(signal.SIGINT, self._sig_handler)
        signal.signal(signal.SIGTERM, self._sig_handler)

    def _sig_handler(self, signum, frame):
        self.stop = True

    def _get_client(self) -> qbittorrentapi.Client:
        client = qbittorrentapi.Client(**self.conn_dict, REQUESTS_ARGS={'timeout':15})
        try:
            client.auth_log_in()
            self.logger.info(f"Connected: qBittorrent {client.app.version} | WebAPI {client.app.web_api_version}")
        except qbittorrentapi.LoginFailed as e:
            self.logger.error(f"Login failed: {e}")
            sys.exit(2)
        return client

    def _is_active_state(self, state: str) -> bool:
        active_states = {
            'downloading', 'stalledDL', 'queuedDL', 'checkingDL',
            'uploading', 'stalledUP', 'queuedUP', 'checkingUP',
            'forcedDL', 'forcedUP', 'allocating',
            'moving', 'metaDL', 'pausedDL', 'pausedUP'
        }
        return state in active_states

    def _is_completed(self, t: qbittorrentapi.TorrentDictionary) -> bool:
        try:
            return float(getattr(t, 'progress', 0.0)) >= 1.0 and getattr(t, 'completion_on', 0) > 0
        except Exception:
            return False

    def _delivery_key(self, torrent):
        return f"{torrent.hash}:{getattr(torrent,'added_on',0)}:{torrent.completion_on}:{torrent.content_path}"

    def _on_torrent_completed(self, torrent: qbittorrentapi.TorrentDictionary) -> None:
        self.logger.info(f"[COMPLETED] {torrent.name} | hash={torrent.hash} | content_path={torrent.content_path}")

        if os.path.exists(torrent.content_path):
            if self.jobs is not None:
                key = self._delivery_key(torrent)
                self.jobs.enqueue(key, torrent.content_path)
            else:
                self.queue.put(torrent.content_path)
            self.completed_seen.add(torrent.hash)
            self._completed_deliveries[torrent.hash] = self._delivery_key(torrent)
        else:
            self.logger.warning('Source path unavailable; preserve torrent and retry: %s', torrent.content_path)

    def _check_codex_before_start(self) -> bool:
        failure_notified = False
        while not self.stop:
            try:
                client = CodexMediaClient(timeout=45, max_retries=0)
                client.check_connection()
                self.logger.info('[Codex][startup] authenticated model round-trip passed')
                return True
            except Exception as exc:
                # Avoid leaking credentials or upstream response bodies in notifications.
                self.logger.warning('[Codex][startup] check failed (%s); retry in 60s', type(exc).__name__)
                if not failure_notified:
                    failure_notified = bool(mcp_direct_call_ns(
                        'notify.send_notification', title='Media Monitor 启动自检失败',
                        content='Codex 认证或模型调用未通过；媒体处理尚未开始，60秒后重试。',
                    ))
                    self.logger.info('[Codex][startup] failure notification sent=%s', failure_notified)
                for _ in range(60):
                    if self.stop:
                        return False
                    time.sleep(1)
        return False

    def run(self) -> None:
        self.client = self._get_client()
        if not self._check_codex_before_start():
            return
        notified = mcp_direct_call_ns(
            'notify.send_notification',
            title='Media Monitor',
            content='Started\nCodex 启动自检通过：本地连接、认证及模型响应正常。',
        )
        if not notified:
            raise RuntimeError('MCP startup notification failed')
        self.logger.info('[Codex][startup] success notification sent; media scanning enabled')
        if self.on_ready:
            self.on_ready()
        while not self.stop:
            if self.check_workers:
                self.check_workers()
            from media_mcp.runtime.worker import heartbeat
            heartbeat('monitor')
            try:
                kwargs = {}
                if self.filter_category:
                    kwargs['category'] = self.filter_category

                torrents = self.client.torrents_info(**kwargs)

                present_hashes = {torrent.hash for torrent in torrents}
                self.completed_seen.intersection_update(present_hashes)
                self._completed_deliveries = {key:value for key,value in self._completed_deliveries.items() if key in present_hashes}
                active = []
                newly_completed = []

                for t in torrents:
                    if self.filter_tags:
                        tags = {tag.strip() for tag in (t.tags or '').split(',') if tag.strip()}
                        if tags.isdisjoint(self.filter_tags):
                            continue

                    if self._is_active_state(t.state):
                        active.append(t)

                    if self._is_completed(t) and self._completed_deliveries.get(t.hash)!=self._delivery_key(t):
                        newly_completed.append(t)

                now_hashes = {t.hash for t in active}
                if now_hashes != self.in_progress_hashes:
                    self.in_progress_hashes = now_hashes
                    names = ', '.join([t.name for t in active]) or '<none>'
                    self.logger.info(f"[ACTIVE] {len(active)} torrents: {names}")

                for t in newly_completed:
                    try:
                        self._on_torrent_completed(t)
                    except Exception as e:
                        self.logger.error(f"torrent completed but callback failed: {t.name} | {e}")

                for t in active:
                    if self._is_completed(t):
                        continue
                    self.logger.debug(f"[Ongoing] {float(getattr(t, 'progress', 0.0)):.2%} : {t.name}")

                time.sleep(self.poll_interval)

            except qbittorrentapi.APIConnectionError as e:
                print(f"[WARN] Connection stopped, retrying: {e}")
                time.sleep(2)
                self.client = self._get_client()
            except Exception as e:
                print(f"[ERROR] Unexpected failure: {e}")
                time.sleep(self.poll_interval)

        self.logger.warning('[INFO] Monitor exit.')
        mcp_direct_call_ns('notify.send_notification', title='Media Monitor', content='Stopped')
