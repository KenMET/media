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


if __name__ == '__main__':
    unittest.main()
