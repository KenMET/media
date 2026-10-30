"""Recovery must load only the requested history and never submit a model turn."""
import unittest
from unittest.mock import Mock

from media_mcp.adapters.codex import CodexClient, CodexError, error_code


class SessionRecoveryTransportTests(unittest.TestCase):
    def client(self):
        return CodexClient.__new__(CodexClient)

    def test_loaded_thread_needs_no_resume(self):
        client = self.client()
        client._control = Mock(return_value={'thread': {'id': 'original', 'turns': []}})
        client.recover_thread('original')
        self.assertEqual(['thread/read'], [call.args[0] for call in client._control.call_args_list])

    def test_unloaded_thread_loads_same_identity_without_policy_overrides(self):
        client = self.client()
        result = {'thread': {'id': 'original', 'turns': [{'id': 'turn', 'status': 'failed'}]}}
        client._control = Mock(side_effect=[CodexError('thread_not_loaded'), result, result])
        self.assertEqual(result, client.recover_thread('original'))
        calls = client._control.call_args_list
        self.assertEqual(['thread/read', 'thread/resume', 'thread/read'], [c.args[0] for c in calls])
        self.assertEqual({'threadId': 'original'}, calls[1].args[1])

    def test_missing_history_stays_unknown_and_does_not_start_new_thread(self):
        client = self.client()
        client._control = Mock(side_effect=[CodexError('thread_not_loaded'), CodexError('thread_unavailable')])
        with self.assertRaisesRegex(CodexError, 'thread_unavailable'):
            client.recover_thread('original')
        self.assertEqual(2, client._control.call_count)

    def test_transport_failure_does_not_attempt_resume(self):
        client = self.client()
        client._control = Mock(side_effect=CodexError('connection_failed'))
        with self.assertRaisesRegex(CodexError, 'connection_failed'):
            client.recover_thread('original')
        self.assertEqual(1, client._control.call_count)

    def test_mismatched_loaded_or_read_identity_is_rejected(self):
        for responses in ([{'thread': {'id': 'other'}}],
                          [CodexError('thread_not_loaded'), {'thread': {'id': 'other'}}]):
            client = self.client()
            client._control = Mock(side_effect=responses)
            with self.assertRaisesRegex(CodexError, 'protocol_error'):
                client.recover_thread('original')

    def test_recovery_errors_have_distinct_sanitized_codes(self):
        for message, code in [('thread not loaded: private-id', 'thread_not_loaded'),
                              ('no rollout found for thread private-id', 'thread_unavailable')]:
            self.assertEqual(code, error_code(RuntimeError(message)))
