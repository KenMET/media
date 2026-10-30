import unittest
from unittest.mock import Mock
import test_sqlite as fixtures
from media_mcp.adapters.codex import CodexError
from media_mcp.application.collections import digest
from media_mcp.runtime.thread_cleanup import archive_intent,enqueue,drain


class ThreadCleanupTests(unittest.TestCase):
    setUp=fixtures.SQLiteTests.setUp

    def source(self,**changes):
        payload={'requested_files':[{'key':'m:1'}]}
        data={'owner':'owner','action':'analysis','analysis_thread':'media-thread','analysis_turn':'media-turn',
              'ai_inflight':False,'analysis_decisions':[{'key':'m:1'}],
              'analysis_request':{'payload':payload,'binding':{'input_digest':digest(payload)}}}
        data.update(changes)
        return self.records.put('library_auto_item',data,'completed')

    def enqueue(self,source):
        return enqueue(self.records,source,archive_intent(source['data'],['m:1']))

    def client(self,**thread_changes):
        thread={'id':'media-thread','turns':[{'id':'media-turn','status':'completed'}]};thread.update(thread_changes)
        client=Mock();client.recover_thread.return_value={'thread':thread};return client

    def test_completed_accepted_owned_turn_archived_once_without_changing_source_revision(self):
        source=self.source();before=self.records.get(source['id'])
        self.assertTrue(self.enqueue(source));self.assertTrue(self.enqueue(source))
        client=self.client();drain(self.records,client,clock=lambda:100);drain(self.records,client,clock=lambda:200)
        client.archive_thread.assert_called_once_with('media-thread')
        self.assertEqual('archived',self.records.list('library_thread_gc')[0]['state'])
        self.assertEqual(before,self.records.get(source['id']))
        client.analyze.assert_not_called();client.interrupt_turn.assert_not_called()

    def test_unknown_inflight_and_unaccepted_requests_never_enter_cleanup_queue(self):
        for change in ({'ai_inflight':True},{'analysis_decisions':[]},
                       {'analysis_request_history':[{'thread':'media-thread','status':'unknown'}]},
                       {'owner':''},{'action':'subtitles'}):
            self.assertFalse(self.enqueue(self.source(**change)))
        self.assertEqual([],self.records.list('library_thread_gc'))

    def test_running_reused_or_mismatched_thread_is_held_and_never_archived(self):
        for changed in ({'id':'unrelated'},
                        {'turns':[{'id':'media-turn','status':'inProgress'}]},
                        {'turns':[{'id':'media-turn','status':'completed'},{'id':'human-turn','status':'completed'}]}):
            source=self.source();self.enqueue(source);client=self.client(**changed)
            drain(self.records,client,clock=lambda:100);client.archive_thread.assert_not_called();client.recover_thread.assert_called_once()
            row=self.records.list('library_thread_gc')[0];self.assertEqual('held',row['state'])
            self.records.update(row,'pending',{**row['data'],'next_attempt_at':0})

    def test_archive_failure_retains_retry_without_failing_media_task(self):
        source=self.source();self.enqueue(source);client=self.client()
        client.archive_thread.side_effect=CodexError('connection_failed')
        drain(self.records,client,clock=lambda:100)
        self.assertEqual('retry',self.records.list('library_thread_gc')[0]['state'])
        self.assertEqual('completed',self.records.get(source['id'])['state'])
        drain(self.records,client,clock=lambda:120);self.assertEqual(1,client.archive_thread.call_count)
        client.archive_thread.side_effect=None;drain(self.records,client,clock=lambda:161)
        self.assertEqual('archived',self.records.list('library_thread_gc')[0]['state'])

    def test_unknown_state_after_enqueue_is_rechecked(self):
        source=self.source();self.enqueue(source)
        self.records.update(source,'running',{**source['data'],'ai_inflight':True})
        client=self.client();drain(self.records,client,clock=lambda:100)
        self.assertEqual('held',self.records.list('library_thread_gc')[0]['state'])
        client.recover_thread.assert_not_called();client.archive_thread.assert_not_called()

    def test_checkpointed_intent_is_reconciled_without_scanning_unrelated_threads(self):
        source=self.source();intent=archive_intent(source['data'],['m:1'])
        self.records.update(source,'completed',{**source['data'],'thread_archive_intents':[intent]})
        client=self.client();drain(self.records,client,clock=lambda:100)
        client.archive_thread.assert_called_once_with('media-thread');client._control.assert_not_called()

    def test_observed_terminal_failure_archives_only_after_proof_is_checkpointed(self):
        source=self.source(analysis_decisions=[])
        intent=archive_intent(source['data'],['m:1'],'failed')
        source=self.records.update(source,'running',{**source['data'],
            'thread_archive_intents':[intent],'analysis_request_history':[
                {'thread':'media-thread','turn':'media-turn','generation':0,'status':'failed'}]})
        client=self.client(turns=[{'id':'media-turn','status':'failed'}]);drain(self.records,client,clock=lambda:100)
        client.archive_thread.assert_called_once_with('media-thread')
        self.assertEqual('archived',self.records.list('library_thread_gc')[0]['state'])
