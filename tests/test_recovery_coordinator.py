"""Independent quota/session timers and completed-result-first acceptance."""
import json
import unittest
from unittest.mock import Mock
import test_library_auto as fixtures
from media_mcp.adapters.codex import CodexError
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task,record_failure,retry_delay
from media_mcp.runtime.quota_wait import QuotaWaiting
from media_mcp.runtime.session_recovery import SessionWaiting


class RecoveryCoordinatorTests(unittest.TestCase):
    setUp=fixtures.AutoTests.setUp
    fixture=fixtures.AutoTests.fixture

    def waiting(self,standalone=False):
        cid=self.fixture(1)
        task=self.service.collection_analyze(cid,'coordinator-fixture') if standalone else self.service.library_auto('coordinator-fixture')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library');ai=fixtures.AutoAI();original=ai.analyze
        stored={}
        def lost(payload,**callbacks):
            callbacks['on_thread']('original')
            result,opened=original(payload,**callbacks);callbacks['on_turn']('turn')
            stored.update(result=result,opened=opened)
            raise CodexError('rate_limited',outcome_unknown=True,phase='model_turn')
        ai.analyze=lost;ai.check_connection=Mock(side_effect=CodexError('rate_limited'))
        with self.assertRaises(CodexError) as caught:process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,job,caught.exception);self.assertTrue(retry)
        self.assertLessEqual(retry_delay(jobs,job,error),60)
        jobs.finish(job,error=error,retry_delay_seconds=retry_delay(jobs,job,error))
        parent=self.records.get(task['job_id']);self.deadline=parent['data']['quota_wait']['next_check_at']
        self.target=parent['data']['quota_wait']['record_id']
        return task,jobs,ai,stored

    def wake(self,jobs):
        self.db.execute("UPDATE media_processing_job SET next_attempt_at='2000-01-01 00:00:00'")
        target=self.records.get(self.target);data=target['data']
        if data.get('session_recovery'):
            data['session_recovery']['next_check_at']='2000-01-01 00:00:00'
            self.records.update(target,target['state'],data)
        return jobs.claim('library')

    def completed(self,stored):
        items=[{'type':'webSearch','action':{'type':'openPage','url':url}} for url in stored['opened']]
        items.append({'type':'agentMessage','text':json.dumps(stored['result'])})
        return {'thread':{'id':'original','turns':[{'id':'turn','status':'completed','items':items}]}}

    def test_failure_checkpoint_restores_original_deadline_after_parent_save_crash(self):
        from media_mcp.runtime.recovery_coordinator import restore_wait_checkpoint
        task,jobs,ai,_=self.waiting();parent=self.records.get(task['job_id'])
        data=dict(parent['data']);data.pop('quota_wait')
        parent=self.records.update(parent,parent['state'],data)
        restored=restore_wait_checkpoint(self.records,parent,lambda:None)
        self.assertEqual(self.deadline,restored['data']['quota_wait']['next_check_at'])
        self.assertEqual(0,restored['data']['quota_wait']['checks'])
        self.assertTrue(restored['data']['quota_wait']['outcome_unknown'])
        ai.check_connection.assert_not_called()

    def test_successful_probe_checkpoint_does_not_restore_same_old_failure(self):
        from media_mcp.runtime.recovery_coordinator import restore_wait_checkpoint
        from media_mcp.runtime.quota_wait import check_quota_wait
        task,jobs,ai,_=self.waiting();parent=self.records.get(task['job_id'])
        ai.check_connection=Mock()
        resumed=check_quota_wait(self.records,parent,ai)
        same=restore_wait_checkpoint(self.records,resumed,lambda:None)
        self.assertNotIn('quota_wait',same['data'])
        self.assertEqual(resumed['revision'],same['revision'])

    def test_completed_original_result_finishes_without_a_new_quota_probe_or_model_call(self):
        task,jobs,ai,stored=self.waiting();ai.recover_thread=Mock(return_value=self.completed(stored))
        job=self.wake(jobs)
        process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=fixtures.AutoSubtitles());jobs.finish(job)
        self.assertEqual('completed',self.service.collection_task(task['job_id'])['state'])
        self.assertEqual(1,ai.calls);ai.check_connection.assert_not_called()
        history=self.records.get(task['job_id'])['data']['quota_history']
        self.assertEqual('original_completed_reconciled',history[-1]['observation']);self.assertEqual(0,history[-1]['checks'])

    def test_standalone_completed_result_keeps_parent_revision_and_closes_stale_failure(self):
        task,jobs,ai,stored=self.waiting(standalone=True);ai.recover_thread=Mock(return_value=self.completed(stored))
        before=[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths]
        job=self.wake(jobs);process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400);jobs.finish(job)
        row=self.records.get(task['job_id']);self.assertEqual('completed',row['state'])
        self.assertNotIn('quota_wait',row['data']);self.assertNotIn('model_failure',row['data'])
        self.assertTrue(row['data']['model_failure_history']);ai.check_connection.assert_not_called()
        self.assertEqual(before,[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths])

    def test_observed_failed_original_is_checkpointed_without_early_quota_check(self):
        task,jobs,ai,_=self.waiting();ai.recover_thread=Mock(return_value={'thread':{'id':'original','turns':[{'id':'turn','status':'failed'}]}})
        job=self.wake(jobs)
        with self.assertRaises(QuotaWaiting) as caught:process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        self.assertFalse(caught.exception.checked)
        error,retry=record_failure(jobs,job,caught.exception);self.assertTrue(retry)
        self.assertGreater(retry_delay(jobs,job,error),7100)
        parent=self.records.get(task['job_id']);child=self.records.get(self.target)
        self.assertEqual(self.deadline,parent['data']['quota_wait']['next_check_at'])
        self.assertEqual(0,parent['data']['quota_wait']['checks']);self.assertFalse(child['data']['ai_inflight'])
        self.assertEqual('failed',child['data']['analysis_request_history'][-1]['status'])
        self.assertEqual('failed',child['data']['thread_archive_intents'][-1]['terminal_status'])
        ai.check_connection.assert_not_called();self.assertEqual(1,ai.calls)

    def test_missing_history_has_three_one_minute_checks_independent_of_quota_deadline(self):
        task,jobs,ai,_=self.waiting();ai.recover_thread=Mock(side_effect=CodexError('thread_unavailable'))
        for count in (1,2,3):
            job=self.wake(jobs)
            with self.assertRaises((SessionWaiting,QuotaWaiting)) as caught:
                process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
            error,retry=record_failure(jobs,job,caught.exception);self.assertTrue(retry)
            jobs.finish(job,error=error,retry_delay_seconds=retry_delay(jobs,job,error))
            parent=self.records.get(task['job_id']);child=self.records.get(self.target)
            self.assertEqual(self.deadline,parent['data']['quota_wait']['next_check_at'])
            self.assertEqual(0,parent['data']['quota_wait']['checks'])
            self.assertEqual(count,child['data']['session_recovery']['checks'])
        self.assertEqual(1,child['data']['analysis_generation']);self.assertFalse(child['data']['ai_inflight'])
        self.assertTrue(child['data']['analysis_request']['pending_replacement'])
        self.assertEqual('unknown',child['data']['analysis_request_history'][0]['status'])
        ai.check_connection.assert_not_called();self.assertEqual(1,ai.calls)

    def test_due_quota_probe_and_running_session_keep_both_timers_and_counters(self):
        task,jobs,ai,_=self.waiting();parent=self.records.get(task['job_id'])
        self.records.update(parent,'queued',{**parent['data'],'quota_wait':{**parent['data']['quota_wait'],'next_check_at':'2000-01-01 00:00:00'}})
        ai.recover_thread=Mock(return_value={'thread':{'id':'original','turns':[{'id':'turn','status':'inProgress'}]}})
        for count in (1,2):
            job=self.wake(jobs)
            with self.assertRaises(SessionWaiting) as caught:process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
            error,retry=record_failure(jobs,job,caught.exception);self.assertTrue(retry)
            self.assertLessEqual(retry_delay(jobs,job,error),60)
            jobs.finish(job,error=error,retry_delay_seconds=retry_delay(jobs,job,error))
            saved=self.records.get(task['job_id'])['data']
            self.assertEqual(1,saved['quota_wait']['checks'])
            child=self.records.get(self.target)['data']
            self.assertEqual(count,child['session_recovery']['observations'])
            self.assertEqual(0,child['session_recovery']['checks'])
        self.assertEqual(1,ai.check_connection.call_count);self.assertTrue(child['ai_inflight'])

    def test_changed_media_rejects_recovered_result_before_probe_or_publish(self):
        task,jobs,ai,stored=self.waiting();ai.recover_thread=Mock(return_value=self.completed(stored))
        self.paths[0][0].write_bytes(b'changed-disposable-media')
        with self.assertRaises(ValueError):process_task(jobs,self.wake(jobs),analysis_client=ai,analysis_probe=lambda p:1400)
        self.assertTrue(self.records.get(self.target)['data']['ai_inflight'])
        ai.recover_thread.assert_not_called();ai.check_connection.assert_not_called()
        self.assertNotIn('analysis_plan_id',self.records.get(self.target)['data'])

    def test_unknown_quota_request_schedules_observation_without_a_manual_api(self):
        task,jobs,ai,_=self.waiting()
        parent=self.records.get(task['job_id']);source=self.records.get(self.target)
        session=parent['data']['session_recovery']
        self.assertTrue(session['independent_observation'])
        self.assertLess(session['next_check_at'],parent['data']['quota_wait']['next_check_at'])
        self.assertEqual(0,parent['data']['quota_wait']['checks'])
        self.assertTrue(source['data']['ai_inflight'])
        self.assertIsNone(jobs.claim('library'))
        ai.check_connection.assert_not_called()

    def test_lease_loss_after_remote_observation_cannot_accept_result_or_clear_fence(self):
        task,jobs,ai,stored=self.waiting();job=self.wake(jobs)
        def lose_lease(thread):
            self.db.execute("UPDATE media_processing_job SET owner='another-owner' WHERE id=:id",job)
            return self.completed(stored)
        ai.recover_thread=Mock(side_effect=lose_lease)
        with self.assertRaisesRegex(RuntimeError,'media_job_lease_lost'):
            process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        self.assertTrue(self.records.get(self.target)['data']['ai_inflight'])
        self.assertNotIn('analysis_plan_id',self.records.get(self.target)['data'])
        ai.check_connection.assert_not_called();self.assertEqual(1,ai.calls)
