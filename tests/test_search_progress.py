"""Disposable-state checks for authorized, bounded search progress."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

import test_gateway
from media_mcp.adapters.jackett import Jackett
from media_mcp.platform.api import create_app
from media_mcp.platform.gateway import create_gateway
from media_mcp.platform.search_progress import report_progress, stream_search
from media_mcp.platform.service import PlatformService


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_arrive_before_search_finishes_and_observers_do_not_leak(self):
        release = threading.Event()
        def work():
            report_progress(sites=['fast', 'slow'])
            release.wait(5)
            report_progress(site='slow', status='jackett_timeout')
            return {'releases': []}
        iterator = stream_search(work).body_iterator
        try:
            first = json.loads(await asyncio.wait_for(anext(iterator), 2))
            self.assertEqual(first, {'progress': {'sites': ['fast', 'slow']}})
            release.set()
            rest = [json.loads(item) async for item in iterator]
            self.assertEqual(rest[-1], {'success': True, 'data': {'releases': []}})
            other = [json.loads(item) async for item in stream_search(lambda: 1).body_iterator]
            self.assertEqual(other, [{'success': True, 'data': 1}])
        finally:
            release.set()
            await iterator.aclose()

    async def test_concurrent_requests_keep_progress_isolated(self):
        barrier = threading.Barrier(2)
        def work(site):
            barrier.wait(timeout=3)
            report_progress(site=site, status='searching')
            return site
        async def collect(site):
            return [json.loads(item) async for item in stream_search(lambda: work(site)).body_iterator]
        left, right = await asyncio.gather(collect('left'), collect('right'))
        self.assertEqual(left[0]['progress']['site'], 'left')
        self.assertEqual(right[0]['progress']['site'], 'right')
        self.assertEqual(left[-1]['data'], 'left')
        self.assertEqual(right[-1]['data'], 'right')

    async def test_disconnect_stops_the_next_provider_and_hides_exception_details(self):
        release, finished = threading.Event(), threading.Event()
        def work():
            try:
                report_progress(site='first', status='searching')
                release.wait(5)
                report_progress(site='second', status='searching')
                self.fail('Disconnected searches must stop before the next provider')
            finally:
                finished.set()
        iterator = stream_search(work).body_iterator
        await anext(iterator)
        await iterator.aclose()
        release.set()
        self.assertTrue(await asyncio.to_thread(finished.wait, 2))
        def failure():
            raise RuntimeError('private-token-must-not-escape')
        events = [json.loads(item) async for item in stream_search(failure).body_iterator]
        self.assertEqual(events, [{'success': False, 'error_code': 'dependency_unavailable'}])

    async def test_real_adapter_publishes_configured_sites_and_safe_terminal_states(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'JACKETT_CONFIG_FILE': str(Path(directory)/'ServerConfig.json'),
            'MEDIA_EXECUTION_ONLY': 'false', 'JACKETT_API_KEY': 'private-fixture-key',
        }):
            indexers = Path(directory)/'Indexers'
            indexers.mkdir()
            for site in ('fast', 'slow'):
                (indexers/(site+'.json')).write_text('{}')
            adapter = Jackett(remote=False)
            adapter._search_site = Mock(side_effect=[[], RuntimeError('jackett_timeout')])
            events = [json.loads(item) async for item in stream_search(lambda: adapter.search('Example')).body_iterator]
            self.assertEqual(events[0]['progress']['sites'], ['fast', 'slow'])
            self.assertIn({'progress': {'site': 'slow', 'status': 'jackett_timeout'}}, events)
            self.assertNotIn('private-fixture-key', json.dumps(events))
            self.assertEqual(events[-1]['data']['diagnostics'][0]['status'], 'ok')


class ProgressHTTPTests(unittest.TestCase):
    setUp = test_gateway.GatewayTests.setUp

    def providers(self):
        tmdb, indexer = Mock(), Mock()
        tmdb.detail.return_value = {'title_id': 'movie:1', 'kind': 'movie', 'tmdb_id': 1,
                                   'title': 'Example', 'original_title': 'Example'}
        def search(query, kind):
            report_progress(sites=['fixture'])
            report_progress(site='fixture', status='ok')
            return {'releases': [], 'diagnostics': [{'site': 'fixture', 'status': 'ok', 'raw_count': 0}]}
        indexer.search.side_effect = search
        return tmdb, indexer

    def test_local_and_cloud_stream_the_same_authorized_search_with_json_compatibility(self):
        tmdb, indexer = self.providers()
        apps = [create_app(self.accounts, self.records, service_factory=lambda actor:
                           PlatformService(actor, self.accounts, self.records, tmdb=tmdb, indexer=indexer)),
                create_gateway(self.remote, tmdb=tmdb, jackett=indexer,
                               catalog=Mock(), http_request=self.transport.request)]
        for app in apps:
            with self.subTest(app=app), TestClient(app, base_url='http://media.test', client=('127.0.0.1', 1234)) as client:
                payload = {'operation': 'search_releases', 'arguments': {'title_id': 'movie:1'}}
                headers = {'accept': 'application/x-ndjson'}
                denied = client.post('/api/command', json=payload, headers=headers)
                self.assertFalse(denied.json()['success'])
                login = client.post('/api/auth/login', json={'username': 'owner', 'password': 'owner-password-123'})
                client.headers['x-csrf-token'] = login.json()['data']['csrf']
                response = client.post('/api/command', json=payload, headers=headers)
                self.assertEqual(response.headers['x-accel-buffering'], 'no')
                self.assertIn('application/x-ndjson', response.headers['content-type'])
                events = [json.loads(line) for line in response.text.splitlines()]
                self.assertEqual(events[0], {'progress': {'sites': ['fixture']}})
                self.assertTrue(events[-1]['success'], events)
                self.assertEqual(events[-1]['data']['search_status'], 'complete')
                regular = client.post('/api/command', json=payload)
                self.assertEqual(regular.json()['data']['releases'], [])
                client.headers['x-csrf-token'] = 'invalid'
                self.assertFalse(client.post('/api/command', json=payload, headers=headers).json()['success'])
