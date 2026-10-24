#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from media_mcp.ingest.clients.codex import CodexMediaClient


class CodexClientTest(unittest.TestCase):
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
            '{"success": true, "translations": [{"id": 1, "zh": "你好"}]}]}'
        )

        self.assertTrue(repaired)
        self.assertEqual({'success': True, 'translations': [{'id': 1, 'zh': '你好'}]}, parsed)

    def test_parse_json_response_rejects_non_json(self):
        with self.assertRaises(json.JSONDecodeError):
            CodexMediaClient._parse_json_response('not json')


if __name__ == '__main__':
    unittest.main()
