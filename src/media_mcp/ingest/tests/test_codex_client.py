#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from media_mcp.ingest.clients.codex import CodexMediaClient


class CodexClientTest(unittest.TestCase):
    def setUp(self):
        import os, tempfile
        from pathlib import Path
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {'MEDIA_DB_PATH':str(Path(directory.name)/'test.sqlite3')})
        env.start()
        self.addCleanup(env.stop)

    def test_media_and_subtitle_pin_model_and_low_effort(self):
        from media_mcp.subtitle.clients.codex import CodexSubtitleClient
        for client_type in (CodexMediaClient, CodexSubtitleClient):
            client = client_type(bearer_token='test', websocket_factory=lambda: None)
            self.assertEqual('gpt-6.1-terra', client.model)
            self.assertEqual('low', client.reasoning_effort)
            medium = client_type(bearer_token='test', reasoning_effort='medium', websocket_factory=lambda: None)
            self.assertEqual('medium', medium.reasoning_effort)
            for options in ({'model': ''}, {'model': '../other'}, {'reasoning_effort': ''}, {'reasoning_effort': 'high'}):
                with self.subTest(client=client_type.__name__, options=options), self.assertRaises(ValueError):
                    client_type(bearer_token='test', **options)


    def test_requests_send_pinned_model_and_effort(self):
        from unittest.mock import Mock
        from media_mcp.subtitle.clients.codex import CodexSubtitleClient
        for client_type in (CodexMediaClient, CodexSubtitleClient):
            client = client_type(bearer_token='test', max_retries=0)
            session = Mock()
            def rpc(method, params):
                if method == 'thread/start':
                    return {'thread': {'id': 'test-thread'}}
                if method == 'turn/start':
                    return {'turn': {'id': 'test-turn'}}
                return {'data': []}
            session.rpc.side_effect = rpc
            session.wait_turn.return_value = '{"success": true}'
            with patch.object(client, '_connect', return_value=session):
                client.classify({'title': 'fixture'})
            requests = {call.args[0]: call.args[1] for call in session.rpc.call_args_list}
            self.assertEqual('gpt-6.1-terra', requests['thread/start']['model'])
            self.assertEqual('low', requests['turn/start']['effort'])

    def test_url_reads_environment_at_construction(self):
        with patch.dict('os.environ', {'CODEX_APP_SERVER_URL': 'ws://127.0.0.1:9999'}):
            client = CodexMediaClient(bearer_token='test', websocket_factory=lambda: None)
            self.assertEqual('ws://127.0.0.1:9999', client.app_server_url)
            explicit = CodexMediaClient(app_server_url='ws://localhost:8888', bearer_token='test', websocket_factory=lambda: None)
            self.assertEqual('ws://localhost:8888', explicit.app_server_url)

    def test_probe_requires_exact_nonce_response(self):
        client = CodexMediaClient(bearer_token='test', websocket_factory=lambda: None)
        with patch.object(client, '_run_codex', side_effect=lambda instructions, payload, **kw: payload):
            client.check_connection()
        with patch.object(client, '_run_codex', return_value={'success': True, 'nonce': 'wrong'}):
            with self.assertRaises(ValueError):
                client.check_connection()

    def test_parse_json_response_accepts_trailing_garbage(self):
        parsed, repaired = CodexMediaClient._parse_json_response(
            '{"success": true, "translations": [{"id": 1, "zh": "\u4f60\u597d"}]}]}'
        )

        self.assertTrue(repaired)
        self.assertEqual({'success': True, 'translations': [{'id': 1, 'zh': '\u4f60\u597d'}]}, parsed)

    def test_parse_json_response_rejects_non_json(self):
        with self.assertRaises(json.JSONDecodeError):
            CodexMediaClient._parse_json_response('not json')

    def _session(self, wait_turn_results):
        from unittest.mock import Mock
        session = Mock()

        def rpc(method, params):
            if method == 'thread/start':
                return {'thread': {'id': 'test-thread'}}
            if method == 'turn/start':
                return {'turn': {'id': 'test-turn'}}
            return {'data': []}

        session.rpc.side_effect = rpc
        session.wait_turn.side_effect = list(wait_turn_results)
        return session

    def test_response_limit_retries_on_fresh_session(self):
        from media_mcp.adapters.codex import CodexError
        client = CodexMediaClient(bearer_token='test', max_retries=2, retry_backoff_seconds=0)
        first = self._session([CodexError('response_limit')])
        second = self._session(['{"success": true}'])
        with patch.object(client, '_connect', side_effect=[first, second]):
            result = client.classify({'title': 'fixture'})
        self.assertEqual({'success': True}, result)
        # The first session got as far as submitting the turn before dying.
        first_methods = [call.args[0] for call in first.rpc.call_args_list]
        self.assertIn('turn/start', first_methods)
        # Second attempt ran on a brand-new session (fresh thread, not resumed).
        methods = [call.args[0] for call in second.rpc.call_args_list]
        self.assertIn('thread/start', methods)
        self.assertNotIn('thread/resume', methods)

    def test_response_limit_raises_after_exhausting_retries(self):
        from media_mcp.adapters.codex import CodexError
        client = CodexMediaClient(bearer_token='test', max_retries=1, retry_backoff_seconds=0)
        sessions = [self._session([CodexError('response_limit')]) for _ in range(2)]
        with patch.object(client, '_connect', side_effect=sessions):
            with self.assertRaises(CodexError) as ctx:
                client.classify({'title': 'fixture'})
        self.assertEqual('response_limit', ctx.exception.code)
        self.assertEqual(2, len(sessions))

    def test_other_submitted_errors_still_fail_fast(self):
        from media_mcp.adapters.codex import CodexError
        client = CodexMediaClient(bearer_token='test', max_retries=2, retry_backoff_seconds=0)
        only = self._session([CodexError('turn_failed', terminal_observed=True)])
        with patch.object(client, '_connect', side_effect=[only]) as connect:
            with self.assertRaises(CodexError) as ctx:
                client.classify({'title': 'fixture'})
        self.assertNotEqual('response_limit', ctx.exception.code)
        self.assertEqual(1, connect.call_count)


if __name__ == '__main__':
    unittest.main()
