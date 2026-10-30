"""Disposable SQLite and media fixtures for durable original-request recovery."""
import json
import unittest
from unittest.mock import Mock

import test_library_auto as fixtures
from media_mcp.adapters.codex import CodexError
from media_mcp.application.collections import digest
from media_mcp.runtime.session_recovery import recover_analysis, SessionWaiting, assert_generation
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task, record_failure


class SessionRecoveryTests(unittest.TestCase):
    setUp=fixtures.AutoTests.setUp
    fixture=fixtures.AutoTests.fixture

    def original(self):
        self.fixture(1)
        row=self.records.put('library_auto_item',{'ai_inflight':True,'analysis_thread':'original',
            'analysis_turn':'turn','files':[],'analysis_decisions':[]})
        self.binding={'input_digest':'input','files_digest':'files','manifest_digest':'manifest',
                      'policy':{'model':'gpt-6.1-terra','effort':'low'}}
        return row

    def due(self,row):
        row=self.records.get(row['id']);data=row['data']
        if data.get('session_recovery'):data['session_recovery']['next_check_at']='2000-01-01 00:00:00'
        return self.records.update(row,row['state'],data)

    def test_missing_history_observed_three_times_then_one_replacement_preserves_unknown(self):
        row=self.original();client=Mock();client.recover_thread.side_effect=CodexError('thread_unavailable')
        for count in (1,2):
            with self.assertRaises(SessionWaiting) as caught:recover_analysis(self.records,row,client,lambda:None,self.binding)
            self.assertEqual(count,caught.exception.recovery['checks']);row=self.due(row)
        old=row
        row,result=recover_analysis(self.records,row,client,lambda:None,self.binding)
        self.assertIsNone(result);self.assertEqual(1,row['data']['analysis_generation'])
        history=row['data']['analysis_request_history'][0]
        self.assertEqual('unknown',history['status']);self.assertTrue(history['superseded'])
        self.assertEqual('original',history['thread']);self.assertFalse(row['data']['ai_inflight'])
        with self.assertRaisesRegex(RuntimeError,'stale_job_revision'):self.records.update(old,'running',old['data'])
        with self.assertRaisesRegex(RuntimeError,'analysis_execution_superseded'):assert_generation(self.records,row['id'],0)
        client.analyze.assert_not_called()

    def test_connection_failure_never_authorizes_replacement(self):
        row=self.original();client=Mock();client.recover_thread.side_effect=CodexError('connection_failed')
        for _ in range(2):
            with self.assertRaises(SessionWaiting):recover_analysis(self.records,row,client,lambda:None,self.binding)
            row=self.due(row)
        with self.assertRaisesRegex(ValueError,'analysis_session_recovery_exhausted'):recover_analysis(self.records,row,client,lambda:None,self.binding)
        saved=self.records.get(row['id'])['data'];self.assertTrue(saved['ai_inflight']);self.assertEqual(3,saved['session_recovery']['checks'])

    def test_replacement_cannot_repeat(self):
        row=self.original();data=row['data'];data.update(analysis_replacements={'input':1},session_recovery={'checks':2})
        row=self.records.update(row,'running',data);client=Mock();client.recover_thread.side_effect=CodexError('thread_unavailable')
        with self.assertRaisesRegex(ValueError,'analysis_replacement_exhausted'):recover_analysis(self.records,row,client,lambda:None,self.binding)
        self.assertTrue(self.records.get(row['id'])['data']['ai_inflight'])

    def test_running_turn_never_replaced_even_at_third_observation(self):
        row=self.original();row=self.records.update(row,'running',{**row['data'],'session_recovery':{'checks':2}})
        client=Mock();client.recover_thread.return_value={'thread':{'id':'original','turns':[{'id':'turn','status':'inProgress'}]}}
        with self.assertRaises(SessionWaiting):recover_analysis(self.records,row,client,lambda:None,self.binding)
        self.assertTrue(self.records.get(row['id'])['data']['ai_inflight'])

    def test_running_turn_has_persistent_deadline(self):
        row=self.original();row=self.records.update(row,'running',{**row['data'],'session_recovery':{'checks':2,'running_since':'2000-01-01 00:00:00'}})
        client=Mock();client.recover_thread.return_value={'thread':{'id':'original','turns':[{'id':'turn','status':'inProgress'}]}}
        with self.assertRaisesRegex(ValueError,'analysis_original_turn_still_running'):recover_analysis(self.records,row,client,lambda:None,self.binding)

    def test_completed_result_durably_retained_for_validation_without_replay(self):
        row=self.original();client=Mock();turn={'id':'turn','status':'completed','items':[]}
        client.recover_thread.return_value={'thread':{'id':'original','turns':[turn]}}
        saved,result=recover_analysis(self.records,row,client,lambda:None,self.binding)
        self.assertEqual(turn,result);self.assertEqual(turn,saved['data']['recovered_analysis_turn']['turn'])
        client.analyze.assert_not_called()

    def test_due_time_and_input_identity_and_lease_fence(self):
        row=self.original();client=Mock();data=row['data'];data['session_recovery']={'next_check_at':'2999-01-01 00:00:00'}
        row=self.records.update(row,'running',data)
        with self.assertRaises(SessionWaiting):recover_analysis(self.records,row,client,lambda:None,self.binding)
        client.recover_thread.assert_not_called();row=self.due(row)
        row=self.records.update(row,'running',{**row['data'],'analysis_request':{'binding':{'input_digest':'other'}}})
        with self.assertRaisesRegex(ValueError,'analysis_recovery_input_changed'):recover_analysis(self.records,row,client,lambda:None,self.binding)
        row=self.records.update(row,'running',{**row['data'],'analysis_request':{'binding':self.binding}})
        with self.assertRaisesRegex(RuntimeError,'media_job_lease_lost'):recover_analysis(self.records,row,client,Mock(side_effect=RuntimeError('media_job_lease_lost')),self.binding)

    def test_completed_or_wrong_thread_identity_cannot_authorize_replacement(self):
        row=self.original();client=Mock();client.recover_thread.return_value={'thread':{'id':'wrong','turns':[{'id':'turn','status':'failed'}]}}
        with self.assertRaisesRegex(ValueError,'analysis_recovery_identity_mismatch'):recover_analysis(self.records,row,client,lambda:None,self.binding)
        self.assertTrue(self.records.get(row['id'])['data']['ai_inflight'])

    def test_plan_from_old_execution_generation_cannot_publish(self):
        cid=self.fixture(1);task=self.service.collection_analyze(cid,'stale-generation-plan')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library')
        process_task(jobs,job,analysis_client=fixtures.AutoAI(),analysis_probe=lambda p:1400)
        jobs.finish(job)
        row=self.records.get(task['job_id']);plan_id=row['data']['analysis_plan_id']
        plan=self.records.get(plan_id);selected=[d['key'] for d in plan['data']['decisions'] if d['applicable']]
        self.records.update(row,row['state'],{**row['data'],'analysis_generation':1})
        before=[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths]
        with self.assertRaisesRegex(RuntimeError,'analysis_execution_superseded'):
            self.service.collection_analysis_apply(plan_id,selected)
        self.assertEqual('preview',self.records.get(plan_id)['state'])
        self.assertEqual(before,[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths])

    def test_unknown_history_fences_its_requested_files_without_blocking_unrelated_rules(self):
        from media_mcp.runtime.model_scope import assert_no_unresolved_analysis
        first={'key':'m:1','state':{'source':[1,101,10,3]}}
        second={'key':'m:2','state':{'source':[1,102,10,3]}}
        row=self.records.put('library_auto_item',{'files':[first,second],'ai_inflight':False,
            'analysis_request_history':[{'status':'unknown','requested_keys':['m:1']}]})
        assert_no_unresolved_analysis(self.db,[second],exclude_id='f'*32)
        with self.assertRaisesRegex(ValueError,'analysis_ai_outcome_unknown'):
            assert_no_unresolved_analysis(self.db,[first],exclude_id='f'*32)
        self.records.update(row,'completed',{**row['data'],'analysis_decisions':[{'key':'m:1'}]})
        assert_no_unresolved_analysis(self.db,[first,second],exclude_id='f'*32)

    def test_legacy_unknown_scope_requires_matching_persisted_input_digest(self):
        from media_mcp.runtime.model_scope import assert_no_unresolved_analysis
        first={'key':'m:1','state':{'source':[1,101,10,3]}}
        second={'key':'m:2','state':{'source':[1,102,10,3]}}
        payload={'requested_files':[{'key':'m:1'}]};binding={'input_digest':digest(payload)}
        row=self.records.put('library_auto_item',{'files':[first,second],
            'analysis_request':{'payload':payload,'binding':binding},
            'analysis_request_history':[{'status':'unknown','binding':binding}]})
        assert_no_unresolved_analysis(self.db,[second],exclude_id='f'*32)
        self.records.update(row,'running',{**row['data'],'analysis_request':{}})
        with self.assertRaisesRegex(ValueError,'analysis_ai_outcome_unknown'):
            assert_no_unresolved_analysis(self.db,[second],exclude_id='f'*32)

    def test_settled_history_cannot_exhaust_scan_budget_or_hide_a_later_unknown(self):
        from media_mcp.runtime.model_scope import assert_no_unresolved_analysis
        file={'key':'m:1','state':{'source':[1,101,10,3]}}
        for _ in range(130):
            self.records.put('library_auto_item',{'files':[file],
                'analysis_request_history':[{'status':'completed','requested_keys':['m:1']}]},'completed')
        assert_no_unresolved_analysis(self.db,[file],exclude_id='f'*32)
        self.records.put('library_auto_item',{'files':[file],
            'analysis_request_history':[{'status':'unknown','requested_keys':['m:1']}]})
        with self.assertRaisesRegex(ValueError,'analysis_ai_outcome_unknown'):
            assert_no_unresolved_analysis(self.db,[file],exclude_id='f'*32)

    def test_completed_original_turn_is_validated_and_applied_without_new_model_call(self):
        self.fixture(1);task=self.service.library_auto('completed-original-integration')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library');ai=fixtures.AutoAI()
        original=ai.analyze;stored={}
        def fail_after_completion(payload,**callbacks):
            callbacks['on_thread']('original');callbacks['on_turn']('turn')
            result,opened=original(payload,**callbacks)
            stored.update(result=result,opened=opened)
            raise CodexError('model_connection_lost',outcome_unknown=True)
        ai.analyze=fail_after_completion
        with self.assertRaises(CodexError) as caught:process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,job,caught.exception);jobs.finish(job,error=error,retry_delay_seconds=60)
        items=[{'type':'webSearch','action':{'type':'openPage','url':url}} for url in stored['opened']]
        items.append({'type':'agentMessage','text':json.dumps(stored['result'])})
        ai.recover_thread=Mock(return_value={'thread':{'id':'original','turns':[{'id':'turn','status':'completed','items':items}]}})
        self.db.execute("UPDATE media_processing_job SET next_attempt_at='2000-01-01 00:00:00'")
        job=jobs.claim('library')
        process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=fixtures.AutoSubtitles());jobs.finish(job)
        self.assertEqual(1,ai.calls);self.assertEqual('completed',self.service.collection_task(task['job_id'])['state'])

    def test_legacy_observation_counts_preserved_but_not_claimed_as_quota_failures(self):
        from media_mcp.runtime.quota_wait import check_quota_wait,QuotaWaiting
        row=self.records.put('library_task',{'quota_wait':{'checks':5,'observation':'original_turn_unavailable','outcome_unknown':True}})
        client=Mock();client.check_connection.side_effect=CodexError('rate_limited')
        with self.assertRaises(QuotaWaiting) as caught:check_quota_wait(self.records,row,client)
        wait=caught.exception.wait
        self.assertEqual(6,wait['checks']);self.assertEqual(5,wait['legacy_observation_checks'])
        self.assertEqual(1,wait['actual_probe_checks']);self.assertEqual('rate_limited',wait['observation'])
        client.read_thread.assert_not_called()

    def test_failed_quota_probe_records_connection_reason_without_claiming_insufficient_quota(self):
        from media_mcp.runtime.quota_wait import check_quota_wait,QuotaWaiting
        row=self.records.put('library_task',{'quota_wait':{'checks':0}})
        client=Mock();client.check_connection.side_effect=CodexError('model_upstream_unavailable')
        with self.assertRaises(QuotaWaiting) as caught:check_quota_wait(self.records,row,client)
        self.assertEqual('probe_unavailable',caught.exception.wait['observation'])
        self.assertEqual('model_upstream_unavailable',caught.exception.wait['probe_error_code'])

    def test_session_and_quota_checks_do_not_consume_transport_retry_budget(self):
        from media_mcp.runtime.quota_wait import QuotaWaiting
        self.fixture(1);task=self.service.library_auto('independent-budget-fixture')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library');job['attempts']=99
        record_failure(jobs,job,SessionWaiting({'checks':2,'record_id':task['job_id']}))
        record_failure(jobs,job,QuotaWaiting({'checks':8}))
        self.assertEqual(0,self.records.get(task['job_id'])['data']['transport_retry_count'])
        for count in range(1,5):
            error,retry=record_failure(jobs,job,CodexError('model_upstream_unavailable',terminal_observed=True))
            self.assertEqual(count<=3,retry)
            self.assertEqual(count,self.records.get(task['job_id'])['data']['transport_retry_count'])

    def test_quota_terminal_notification_event_survives_crash_before_enqueue(self):
        from unittest.mock import patch
        from media_mcp.runtime.quota_wait import QuotaWaiting
        from media_mcp.runtime.task_notifications import deliver
        self.fixture(1);task=self.service.library_auto('quota-notification-crash')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library')
        with patch('media_mcp.runtime.task_notifications.enqueue',side_effect=RuntimeError('simulated_crash')):
            with self.assertRaisesRegex(RuntimeError,'simulated_crash'):record_failure(jobs,job,QuotaWaiting({'checks':10}))
        row=self.records.get(task['job_id'])
        self.assertEqual('failed',row['state']);self.assertEqual('quota_checks_exhausted',row['data']['terminal_notice_event']['reason'])
        self.assertEqual([],self.records.list('library_notice'))
        sender=Mock(return_value=True);deliver(self.records,sender,clock=lambda:100)
        sender.assert_called_once();self.assertEqual('delivered',self.records.list('library_notice')[0]['state'])

    def test_successful_tiny_probe_cannot_reset_ten_check_budget_without_media_progress(self):
        from media_mcp.runtime.quota_wait import QuotaWaiting,check_quota_wait
        self.fixture(1);task=self.service.library_auto('nonce-does-not-reset-budget')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library');client=Mock()
        record_failure(jobs,job,QuotaWaiting({'checks':8,'actual_probe_checks':8}))
        for count in (9,10):
            check_quota_wait(self.records,self.records.get(task['job_id']),client)
            error,retry=record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
            saved=self.records.get(task['job_id'])
            self.assertEqual(count,saved['data']['quota_wait']['checks'])
            self.assertEqual(count,saved['data']['quota_wait']['actual_probe_checks'])
            self.assertEqual(count<10,retry)
        self.assertEqual('failed',saved['state']);self.assertIsNone(saved['data']['quota_wait']['next_check_at'])

    def test_new_completed_work_can_start_a_new_quota_episode(self):
        from media_mcp.runtime.quota_wait import QuotaWaiting,check_quota_wait
        self.fixture(1);task=self.service.library_auto('quota-after-real-progress')
        jobs=MediaJobs();jobs.initialize();job=jobs.claim('library')
        record_failure(jobs,job,QuotaWaiting({'checks':8}))
        row=check_quota_wait(self.records,self.records.get(task['job_id']),Mock())
        self.records.update(row,'running',{**row['data'],'results':[{'key':'m:1','state':'completed'}]})
        _,retry=record_failure(jobs,job,CodexError('rate_limited',terminal_observed=True))
        self.assertTrue(retry);self.assertEqual(0,self.records.get(task['job_id'])['data']['quota_wait']['checks'])

    def test_legacy_recovery_admission_preserves_budget_results_and_is_idempotent(self):
        self.fixture(1);task=self.service.library_auto('legacy-migration-fixture')
        parent=self.records.get(task['job_id']);data=parent['data']
        child=self.records.put('library_auto_item',{'owner':self.admin.id,'action':'analysis',
            'ai_inflight':True,'analysis_thread':'original','analysis_turn':'turn',
            'files':data['files'],'results':[]},key_hash=digest(['library-auto-item',parent['id'],0]))
        wait={'checks':5,'record_id':child['id'],'outcome_unknown':True,'observation':'original_turn_unavailable','next_check_at':'2999-01-01 00:00:00'}
        self.records.update(parent,'queued',{**data,'quota_wait':wait})
        self.db.execute("UPDATE media_processing_job SET state='retry',next_attempt_at='2999-01-01 00:00:00'")
        result=self.service.library_session_recover(parent['id'])
        self.assertEqual(5,result['quota_wait']['checks']);self.assertEqual(5,result['quota_wait']['legacy_observation_checks'])
        self.assertTrue(self.records.get(child['id'])['data']['ai_inflight'])
        self.assertEqual(result,self.service.library_session_recover(parent['id']))
        self.assertIsNotNone(MediaJobs().claim('library'))

    def test_legacy_recovery_admission_rejects_active_job_and_does_not_change_records(self):
        self.fixture(1);task=self.service.library_auto('legacy-active-fixture')
        parent=self.records.get(task['job_id']);data=parent['data']
        from media_mcp.application.collections import digest
        child=self.records.put('library_auto_item',{'owner':self.admin.id,'action':'analysis','ai_inflight':True,'files':data['files']},key_hash=digest(['library-auto-item',parent['id'],0]))
        self.records.update(parent,'queued',{**data,'quota_wait':{'record_id':child['id'],'checks':3,'outcome_unknown':True,'observation':'original_turn_unavailable'}})
        MediaJobs().claim('library');before=self.records.get(parent['id'])
        with self.assertRaisesRegex(ValueError,'session_recovery_job_active'):self.service.library_session_recover(parent['id'])
        self.assertEqual(before,self.records.get(parent['id']))

    def test_real_processing_resumes_with_new_session_after_missing_rollout_and_keeps_bytes(self):
        self.fixture(1);before=[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths]
        task=self.service.library_auto('session-recovery-integration');jobs=MediaJobs();jobs.initialize()
        ai=fixtures.AutoAI();original=ai.analyze;calls=[]
        def analyze(payload,**callbacks):
            calls.append(payload)
            if len(calls)==1:
                callbacks['on_thread']('original');callbacks['on_submitting']();callbacks['on_turn']('turn')
                raise CodexError('model_connection_lost',outcome_unknown=True,phase='model_turn')
            callbacks['on_thread']('replacement');callbacks['on_turn']('new-turn')
            return original(payload,**callbacks)
        ai.analyze=analyze;ai.recover_thread=Mock(side_effect=CodexError('thread_unavailable'))
        for attempt in range(4):
            job=jobs.claim('library');self.assertIsNotNone(job,(attempt,[dict(r) for r in self.db.execute('SELECT state,error,next_attempt_at FROM media_processing_job').mappings().all()],self.service.collection_task(task['job_id'])))
            try:
                process_task(jobs,job,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=fixtures.AutoSubtitles())
                jobs.finish(job)
            except (CodexError,SessionWaiting) as error:
                code,retry=record_failure(jobs,job,error);self.assertTrue(retry)
                jobs.finish(job,error=code,review_required=not retry,retry_delay_seconds=60)
                child=self.records.decode(self.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_auto_item'").mappings().one())
                self.due(child)
                self.db.execute("UPDATE media_processing_job SET next_attempt_at='2000-01-01 00:00:00'")
        self.assertEqual(2,len(calls));self.assertEqual(calls[0],calls[1])
        self.assertEqual('completed',self.service.collection_task(task['job_id'])['state'])
        child=self.records.list('library_auto_item')[0]
        intent=child['data']['thread_archive_intents'][0]
        self.assertEqual('replacement',intent['thread']);self.assertEqual('new-turn',intent['turn'])
        self.assertEqual({f['key'] for f in calls[1]['requested_files']},set(intent['requested_keys']))
        self.assertEqual(before,[(a.read_bytes(),a.stat().st_ino,b.stat().st_ino) for a,b in self.paths])


class NotificationTests(unittest.TestCase):
    setUp=fixtures.AutoTests.setUp

    def test_intent_deduplicated_and_failure_retries_without_false_delivery(self):
        from media_mcp.runtime.task_notifications import enqueue,deliver
        row=self.records.put('library_task',{'files':[],'results':[]})
        enqueue(self.records,row,'quota_checks_exhausted');enqueue(self.records,row,'quota_checks_exhausted')
        self.assertEqual(1,len(self.records.list('library_notice')))
        sender=Mock(return_value=False);deliver(self.records,sender,clock=lambda:100)
        self.assertEqual('pending',self.records.list('library_notice')[0]['state'])
        deliver(self.records,sender,clock=lambda:120);self.assertEqual(1,sender.call_count)
        sender.return_value=True;deliver(self.records,sender,clock=lambda:161)
        self.assertEqual('delivered',self.records.list('library_notice')[0]['state'])

    def test_terminal_state_without_intent_is_reconciled_after_crash(self):
        from media_mcp.runtime.task_notifications import deliver
        row=self.records.put('library_task',{'files':[],'results':[],'error_code':'quota_checks_exhausted','terminal_notice_event':{'reason':'quota_checks_exhausted'}},'failed')
        sender=Mock(return_value=True);deliver(self.records,sender,clock=lambda:100)
        self.assertEqual(1,sender.call_count);self.assertTrue(self.records.get(row['id'])['data']['terminal_notice'])
        deliver(self.records,sender,clock=lambda:200);self.assertEqual(1,sender.call_count)

    def test_historical_failures_and_per_file_records_never_generate_compensation_notifications(self):
        from media_mcp.runtime.task_notifications import deliver,enqueue
        for kind in ('library_task','library_auto_item'):
            for reason in ('automatic_ai_unavailable','quota_checks_exhausted'):
                self.records.put(kind,{'files':[],'results':[],'error_code':reason},'needs_review')
        child=self.records.put('library_auto_item',{'files':[],'results':[],'terminal_notice_event':{'reason':'automatic_ai_unavailable'}},'needs_review')
        sender=Mock();deliver(self.records,sender,clock=lambda:100)
        sender.assert_not_called();self.assertEqual([],self.records.list('library_notice'))
        with self.assertRaisesRegex(ValueError,'notification_requires_root_task'):enqueue(self.records,child,'automatic_ai_unavailable')
