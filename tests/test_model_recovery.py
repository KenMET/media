import unittest
from unittest.mock import Mock
import test_library_auto as auto_fixtures
from media_mcp.adapters.codex import CodexError,CodexClient,error_code
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task,record_failure
from media_mcp.runtime.model_retry import ModelServiceDeferred,retryable_model_error


class ModelRecoveryTests(unittest.TestCase):
    setUp=auto_fixtures.AutoTests.setUp
    fixture=auto_fixtures.AutoTests.fixture

    def start(self):
        self.fixture(1)
        task=self.service.library_auto('retry-fixture-001')
        jobs=MediaJobs();jobs.initialize()
        return task,jobs,jobs.claim('library')

    def test_unknown_submission_stays_fenced_and_does_not_schedule_retry(self):
        task,jobs,job=self.start()
        ai=Mock()
        def fail(payload,**callbacks):
            callbacks['on_submitting']()
            raise CodexError('model_connection_lost',outcome_unknown=True,phase='model_turn')
        ai.analyze.side_effect=fail
        with self.assertRaises(CodexError) as caught:
            process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,job,caught.exception)
        self.assertFalse(retry);self.assertEqual('analysis_ai_outcome_unknown',error)
        jobs.finish(job,error=error,review_required=not retry)
        child=self.db.execute("SELECT data FROM media_mcp_record WHERE kind='library_auto_item'").mappings().one()
        import json
        self.assertTrue(json.loads(child['data'])['ai_inflight'])
        self.assertIsNone(jobs.claim('library'))
        self.assertEqual('needs_review',self.service.collection_task(task['job_id'])['state'])
        self.assertEqual(1,ai.analyze.call_count)

    def test_observed_terminal_failure_can_resume_but_has_finite_retry_limit(self):
        task,jobs,job=self.start()
        ai=Mock()
        def fail(payload,**callbacks):
            callbacks['on_submitting']()
            raise CodexError('model_upstream_unavailable',terminal_observed=True,phase='model_turn')
        ai.analyze.side_effect=fail
        for attempt in range(1,5):
            self.assertEqual(attempt,job['attempts'])
            with self.assertRaises(ModelServiceDeferred) as caught:
                process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
            error,retry=record_failure(jobs,job,caught.exception)
            self.assertEqual(attempt<=3,retry)
            jobs.finish(job,error=error,review_required=not retry)
            import json
            child=self.db.execute("SELECT data FROM media_mcp_record WHERE kind='library_auto_item'").mappings().one()
            self.assertFalse(json.loads(child['data'])['ai_inflight'])
            self.assertEqual(0,self.service.collection_task(task['job_id'])['completed'])
            if retry:
                self.db.execute("UPDATE media_processing_job SET next_attempt_at=datetime('now','-1 second') WHERE id=:id",job)
                job=jobs.claim('library')
        self.assertIsNone(jobs.claim('library'))
        self.assertEqual(4,ai.analyze.call_count)

    def test_subtitle_failure_retains_certainty_instead_of_becoming_generic_review(self):
        self.fixture(1)
        cid=self.service.collections()['collections'][0]['collection_id']
        preview=self.service.collection_identify(cid,'tv:123')
        cid=self.service.collection_identity_apply(preview['plan_id'])['collection_id']
        task=self.service.collection_subtitles(cid,'subtitle-retry-fixture')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library')
        class FailedSubtitles:
            def _run_path_summary_locked(self,*args,**kwargs):
                self._last_model_error=CodexError('model_upstream_unavailable',terminal_observed=True)
                return {'media_count':1,'handled':0,'failed':1}
        with self.assertRaises(ModelServiceDeferred) as caught:
            process_task(jobs,job,subtitle_agent=FailedSubtitles())
        error,retry=record_failure(jobs,job,caught.exception)
        jobs.finish(job,error=error,review_required=not retry)
        row=self.records.get(task['job_id'])
        self.assertNotIn('subtitle_inflight',row['data'])
        self.assertEqual([],row['data']['results'])
        self.db.execute("UPDATE media_processing_job SET next_attempt_at=datetime('now','-1 second') WHERE id=:id",job)
        job=jobs.claim('library')
        process_task(jobs,job,subtitle_agent=auto_fixtures.AutoSubtitles())
        jobs.finish(job)
        self.assertEqual('completed',self.service.collection_task(task['job_id'])['state'])

    def test_accepted_chunks_are_not_resubmitted_after_terminal_failure(self):
        self.fixture(13)
        task=self.service.library_auto('chunk-recovery-fixture')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library')
        ai=auto_fixtures.AutoAI();original=ai.analyze;calls=[]
        def analyze(payload,**callbacks):
            calls.append([item['key'] for item in payload['requested_files']])
            if len(calls)==2:
                callbacks['on_submitting']()
                raise CodexError('model_upstream_unavailable',terminal_observed=True)
            return original(payload,**callbacks)
        ai.analyze=analyze
        with self.assertRaises(ModelServiceDeferred) as caught:
            process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,job,caught.exception);jobs.finish(job,error=error,review_required=not retry)
        self.assertEqual([12,1],[len(x) for x in calls])
        self.db.execute("UPDATE media_processing_job SET next_attempt_at=datetime('now','-1 second') WHERE id=:id",job)
        job=jobs.claim('library')
        process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=auto_fixtures.AutoSubtitles())
        jobs.finish(job)
        self.assertEqual([12,1,1],[len(x) for x in calls])
        self.assertEqual(calls[1],calls[2])
        self.assertFalse(set(calls[0]) & set(calls[2]))

    def test_starting_new_task_cannot_replay_an_older_unknown_research_turn(self):
        task,jobs,job=self.start()
        ai=Mock()
        def fail(payload,**callbacks):
            callbacks['on_submitting']()
            raise CodexError('model_connection_lost',outcome_unknown=True)
        ai.analyze.side_effect=fail
        with self.assertRaises(CodexError) as caught:
            process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,job,caught.exception);jobs.finish(job,error=error,review_required=True)
        new=self.service.library_auto('new-request-still-fenced')
        job=jobs.claim('library');second=auto_fixtures.AutoAI()
        process_task(jobs,job,analysis_client=second,analysis_probe=lambda p:1400)
        jobs.finish(job)
        self.assertEqual(0,second.calls)
        result=self.service.collection_task(new['job_id'])
        self.assertEqual('analysis_ai_outcome_unknown',result['results'][0]['error_code'])

    def test_scope_fence_uses_physical_fingerprint_and_respects_accepted_chunks(self):
        from media_mcp.runtime.model_scope import assert_no_unresolved_analysis
        fingerprint=[1,2,3,4]
        row=self.records.put('library_auto_item',{'ai_inflight':True,
            'files':[{'key':'old','state':{'source':fingerprint}}]})
        with self.assertRaisesRegex(ValueError,'analysis_ai_outcome_unknown'):
            assert_no_unresolved_analysis(self.db,[{'key':'new','state':{'target':fingerprint}}],exclude_id='other')
        assert_no_unresolved_analysis(self.db,[{'state':{'source':[1,2,3,5]}}],exclude_id='other')
        self.records.update(row,'running',{**row['data'],'analysis_decisions':[{'key':'old'}]})
        assert_no_unresolved_analysis(self.db,[{'state':{'source':fingerprint}}],exclude_id='other')

    def test_prior_subtitle_scope_stays_fenced_across_task_ids(self):
        from media_mcp.runtime.model_scope import assert_no_unresolved_subtitle
        state={'source':[1,2,3,4]}
        prior=self.records.put('library_auto_item',{'subtitle_inflight':'old',
            'files':[{'key':'old','state':state}]})
        with self.assertRaisesRegex(ValueError,'prior_subtitle_outcome_unknown'):
            assert_no_unresolved_subtitle(self.db,{'key':'new','state':state},exclude_id='other')
        assert_no_unresolved_subtitle(self.db,{'state':state},exclude_id=prior['id'])
        assert_no_unresolved_subtitle(self.db,{'state':{'source':[1,2,3,5]}},exclude_id='other')

    def test_error_codes_do_not_leak_raw_server_or_credential_text(self):
        self.assertEqual('model_upstream_unavailable',error_code(RuntimeError('IO error: Connection reset by peer; https://secret.invalid/?api_key=secret')))
        self.assertEqual('rate_limited',error_code(RuntimeError('usage_limit_reached')))
        self.assertFalse(retryable_model_error(CodexError('rate_limited',outcome_unknown=True)))
        self.assertFalse(retryable_model_error(CodexError('token_rejected')))

    def test_connect_failure_is_identified_before_submission(self):
        self.fixture(1)
        def refused(*args,**kwargs):raise ConnectionRefusedError('fixture only')
        client=CodexClient(bearer_token='fixture',max_retries=0,websocket_factory=refused)
        with self.assertRaises(CodexError) as caught:client.run_json('fixture',{})
        self.assertEqual('app_server_unreachable',caught.exception.code)
        self.assertEqual('app_server_connect',caught.exception.phase)
        self.assertFalse(caught.exception.outcome_unknown)


if __name__=='__main__':unittest.main()

class QuotaWaitTests(unittest.TestCase):
    setUp=ModelRecoveryTests.setUp
    fixture=ModelRecoveryTests.fixture
    start=ModelRecoveryTests.start
    def test_quota_wait_has_two_hour_due_time_even_after_many_attempts(self):
        task,jobs,job=self.start();job['attempts']=9
        error,retry=record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        self.assertTrue(retry);self.assertEqual('model_quota_waiting',error)
        jobs.finish(job,error=error,retry_delay_seconds=7200)
        self.assertIsNone(jobs.claim('library'))
        seconds=self.db.execute("SELECT strftime('%s',next_attempt_at)-strftime('%s',CURRENT_TIMESTAMP) FROM media_processing_job WHERE id=:id",job).scalar()
        self.assertGreaterEqual(seconds,7198);self.assertLessEqual(seconds,7200)
        self.assertEqual('waiting_quota',self.service.collection_task(task['job_id'])['analysis_progress']['phase'])

    def test_quota_probe_is_independent_and_never_clears_original_unknown(self):
        from media_mcp.runtime.quota_wait import check_quota_wait
        task,jobs,job=self.start();parent=self.records.get(task['job_id'])
        child=self.records.put('library_auto_item',{'ai_inflight':True,'analysis_thread':'thread','analysis_turn':'turn'})
        exc=CodexError('rate_limited',outcome_unknown=True);exc.recovery_record_id=child['id']
        record_failure(jobs,job,exc)
        parent=self.records.get(parent['id']);client=Mock()
        row=check_quota_wait(self.records,parent,client)
        self.assertNotIn('quota_wait',row['data'])
        self.assertTrue(self.records.get(child['id'])['data']['ai_inflight'])
        self.assertEqual('quota_available',row['data']['quota_history'][-1]['observation'])
        client.check_connection.assert_called_once()
        client.read_thread.assert_not_called();client.analyze.assert_not_called()

    def test_quota_success_does_not_reconcile_or_replay_original_request(self):
        from media_mcp.runtime.quota_wait import check_quota_wait
        task,jobs,job=self.start();row=self.records.get(task['job_id'])
        row=self.records.update(row,'queued',{**row['data'],'ai_inflight':True,'analysis_thread':'t','analysis_turn':'v','quota_wait':{'outcome_unknown':True}})
        client=Mock()
        result=check_quota_wait(self.records,row,client)
        self.assertTrue(result['data']['ai_inflight'])
        self.assertEqual('t',result['data']['analysis_thread']);self.assertEqual('v',result['data']['analysis_turn'])
        client.analyze.assert_not_called();client.read_thread.assert_not_called()

    def test_probe_failure_preserves_wait_and_success_allows_resume(self):
        from media_mcp.runtime.quota_wait import QuotaWaiting,check_quota_wait
        task,jobs,job=self.start();record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        row=self.records.get(task['job_id']);client=Mock();client.check_connection.side_effect=CodexError('rate_limited',outcome_unknown=True)
        with self.assertRaises(QuotaWaiting):check_quota_wait(self.records,row,client)
        self.assertIn('quota_wait',self.records.get(row['id'])['data'])
        client.check_connection.side_effect=None
        row=self.records.get(row['id'])
        self.assertNotIn('quota_wait',check_quota_wait(self.records,row,client)['data'])

    def test_probe_budget_is_persisted_before_external_io_and_survives_crash(self):
        from media_mcp.runtime.quota_wait import check_quota_wait,QuotaWaiting
        task,jobs,job=self.start();record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        row=self.records.get(task['job_id']);seen={}
        def crash():
            seen.update(self.records.get(row['id'])['data']['quota_wait'])
            raise KeyboardInterrupt()
        client=Mock();client.check_connection.side_effect=crash
        with self.assertRaises(KeyboardInterrupt):check_quota_wait(self.records,row,client)
        self.assertEqual(1,seen['checks']);self.assertTrue(seen['probe_inflight'])
        self.assertTrue(seen['next_check_at']);self.assertEqual(1,seen['probe_attempts'])
        row=self.records.get(row['id']);wait={**row['data']['quota_wait'],'checks':10}
        row=self.records.update(row,row['state'],{**row['data'],'quota_wait':wait})
        with self.assertRaises(QuotaWaiting) as caught:check_quota_wait(self.records,row,client)
        self.assertFalse(caught.exception.checked);self.assertEqual(1,client.check_connection.call_count)

    def test_existing_stopped_quota_task_can_be_scheduled_without_clearing_fence(self):
        from media_mcp.runtime.quota_wait import schedule_existing_quota_task
        from media_mcp.application.collections import digest
        task,jobs,job=self.start()
        row=self.records.get(task['job_id'])
        child=self.records.put('library_auto_item',{'ai_inflight':True,'last_model_failure':{'code':'rate_limited','outcome_unknown':True}},key_hash=digest(['library-auto-item',row['id'],0]))
        error,retry=record_failure(jobs,job,CodexError('model_connection_lost',outcome_unknown=True))
        jobs.finish(job,error=error,review_required=True)
        updated=schedule_existing_quota_task(self.records,row['id'],self.service.actor)
        self.assertEqual('queued',updated['state']);self.assertTrue(updated['data']['quota_wait']['outcome_unknown'])
        self.assertTrue(self.records.get(child['id'])['data']['ai_inflight']);self.assertIsNone(jobs.claim('library'))
        with self.assertRaisesRegex(ValueError,'quota_task_not_stopped'):
            schedule_existing_quota_task(self.records,row['id'],self.service.actor)

    def test_restart_before_due_does_not_probe_or_replay(self):
        from media_mcp.runtime.quota_wait import QuotaWaiting
        task,jobs,job=self.start();record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        client=Mock()
        with self.assertRaises(QuotaWaiting):process_task(jobs,job,analysis_client=client)
        client.check_connection.assert_not_called();client.analyze.assert_not_called()

    def test_terminal_observation_checkpoint_is_idempotent_after_restart(self):
        from media_mcp.runtime.quota_wait import check_quota_wait
        task,jobs,job=self.start();row=self.records.get(task['job_id'])
        proof={'thread':'t','turn':'v','status':'failed'}
        row=self.records.update(row,'queued',{**row['data'],'ai_inflight':False,'analysis_thread':'t','analysis_turn':'v',
            'quota_terminal_observation':proof,'quota_wait':{'outcome_unknown':True}})
        client=Mock();client.read_thread.return_value={'thread':{'id':'t','turns':[{'id':'v','status':'failed'}]}}
        result=check_quota_wait(self.records,row,client)
        self.assertNotIn('quota_wait',result['data']);client.check_connection.assert_called_once()

    def test_ten_due_checks_survive_restart_and_stop_without_replaying(self):
        from datetime import datetime, timedelta, timezone
        from media_mcp.runtime.quota_wait import QuotaWaiting
        from media_mcp.storage.records import Records
        task,jobs,job=self.start()
        error,retry=record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        jobs.finish(job,error=error,review_required=not retry)
        client=Mock();client.check_connection.side_effect=CodexError('rate_limited',terminal_observed=True)
        for count in range(1,11):
            # Advance only disposable SQLite deadlines; never sleep or contact a model.
            records=Records(self.db);row=records.get(task['job_id'])
            wait={**row['data']['quota_wait'],'next_check_at':'2000-01-01 00:00:00'}
            records.update(row,'queued',{**row['data'],'quota_wait':wait})
            self.db.execute("UPDATE media_processing_job SET next_attempt_at='2000-01-01 00:00:00' WHERE id=:id",job)
            jobs=MediaJobs();job=jobs.claim('library')
            with self.assertRaises(QuotaWaiting) as caught:
                process_task(jobs,job,analysis_client=client)
            error,retry=record_failure(jobs,job,caught.exception)
            jobs.finish(job,error=error,review_required=not retry)
            saved=Records(self.db).get(task['job_id'])
            self.assertEqual(count,saved['data']['quota_wait']['checks'])
            self.assertEqual(count<10,retry)
            self.assertEqual([],saved['data']['results'])
            if count<10:
                due=datetime.strptime(saved['data']['quota_wait']['next_check_at'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                self.assertGreater(due,datetime.now(timezone.utc)+timedelta(seconds=7190))
                self.assertIsNone(MediaJobs().claim('library'))
        self.assertEqual('failed',saved['state'])
        self.assertEqual('quota_checks_exhausted',saved['data']['error_code'])
        self.assertIsNone(saved['data']['quota_wait']['next_check_at'])
        self.assertIsNone(MediaJobs().claim('library'))
        self.assertEqual(10,client.check_connection.call_count)
        client.analyze.assert_not_called()
