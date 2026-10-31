import json
import unittest
from unittest.mock import patch
import test_collections as fixtures
from media_mcp.application.collections import digest
from media_mcp.runtime.state import MediaJobs,media_mutation_lock
from media_mcp.platform.service import PlatformService
from media_mcp.platform.accounts import Actor


class TaskViewsTests(unittest.TestCase):
    setUp=fixtures.CollectionsTests.setUp
    fixture=fixtures.CollectionsTests.fixture

    def test_progress_is_readable_during_mutation_lock_without_touching_media(self):
        self.fixture(1);job=self.service.library_auto('task-view-active1')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        row=self.records.get(job['job_id']);row['data']['analysis_progress']['phase']='identifying';row=self.records.update(row,'running')
        work=row['data']['work'][0]
        self.records.put('library_auto_item',{'files':row['data']['files'],'analysis_progress':{'phase':'researching','done':3,'total':8}},'running',key_hash=digest(['library-auto-item',row['id'],0]))
        with media_mutation_lock(self.db),patch('media_mcp.application.collections.Collections.files',side_effect=AssertionError('progress must not scan media')):
            status=self.service.library_task_status(job['job_id'])
            listing=self.service.library_tasks()
        self.assertEqual(status['analysis_progress']['phase'],'researching')
        self.assertEqual(status['analysis_progress']['detail'],{'phase':'researching','done':3,'total':8})
        self.assertTrue(status['worker']['lease_active'])
        self.assertNotIn('source_path',json.dumps(status));self.assertEqual(listing['tasks'][0]['job_id'],job['job_id'])
        jobs.finish(claimed)

    def test_every_file_result_is_paginated_including_successes_and_more_than_fifty_issues(self):
        self.fixture(1);job=self.service.library_auto('task-view-results1')
        row=self.records.get(job['job_id']);data=row['data']
        data['results']=[{'key':'i:'+str(i),'name':'file-'+str(i),'state':'completed' if i%2 else 'needs_review','error_code':None if i%2 else 'automatic_match_uncertain'} for i in range(1,121)]
        data['total']=120;data['work']=[]
        self.records.update(row,'completed_with_warnings',data)
        first=self.service.library_task_details(job['job_id'],limit=50)
        self.assertEqual(first['total_results'],120);self.assertEqual(first['next_cursor'],50)
        last=self.service.library_task_details(job['job_id'],after=50,limit=50,issues_only=True)
        self.assertEqual(last['total_results'],60);self.assertEqual(len(last['results']),10);self.assertIsNone(last['next_cursor'])
        self.assertEqual(last['results'][-1]['name'],'file-120')
        self.assertEqual(first['results'][0]['state'],'completed')
        status=self.service.library_task_status(job['job_id'])
        self.assertEqual((status['completed'],status['review_count'],status['total']),(120,60,120))
        self.assertEqual(status['succeeded'],60)
        self.assertEqual(self.service.library_tasks()['tasks'][0]['succeeded'],60)

    def test_subtitle_progress_exposes_current_group_checkpoints_without_scanning_media(self):
        self.fixture(2);job=self.service.library_auto('task-subtitle-progress1')
        row=self.records.get(job['job_id']);data=row['data'];data['analysis_progress']['phase']='subtitles'
        row=self.records.update(row,'running',data)
        files=data['files'];outcome={'key':files[0]['key'],'state':'completed','subtitles':'ready'}
        child=self.records.put('library_auto_item',{'files':files,'analysis_applied':2,'auto_results':[outcome]},
            'running',key_hash=digest(['library-auto-item',row['id'],0]))
        with patch('media_mcp.application.collections.Collections.files',side_effect=AssertionError('status must not scan media')):
            status=self.service.library_task_status(row['id'])
        self.assertEqual(status['analysis_progress']['detail'],{'phase':'subtitles','done':1,'total':2})
        self.assertEqual(status['completed'],0)
        self.records.update(child,'running',{**child['data'],'auto_results':[outcome,{'key':files[1]['key'],'state':'needs_review'}]})
        self.assertEqual(self.service.library_task_status(row['id'])['analysis_progress']['detail']['done'],2)

    def test_resume_lookup_is_read_only_and_owned(self):
        self.fixture(1);job=self.service.library_auto('recover-request01')
        before=self.db.execute('SELECT COUNT(*) FROM media_processing_job').scalar()
        with media_mutation_lock(self.db):
            found=self.service.library_auto_status('recover-request01')
        self.assertEqual(found['task']['job_id'],job['job_id'])
        self.assertFalse(self.service.library_auto_status('never-submitted-01')['found'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_processing_job').scalar(),before)
        other=PlatformService(Actor(self.alice.id,'alice','user',can_manage_media=True),self.accounts,self.records)
        self.assertFalse(other.library_auto_status('recover-request01')['found'])
        with self.assertRaisesRegex(ValueError,'permission_denied'):other.library_task_status(job['job_id'])
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            PlatformService(self.alice,self.accounts,self.records).library_tasks()

    def test_active_task_remains_on_first_page_after_newer_history(self):
        self.fixture(1);job=self.service.library_auto('active-history-01')
        template=self.records.get(job['job_id'])['data']
        for number in range(12):self.records.put('library_task',{**template,'processing_key':'history-'+str(number)},'completed')
        page=self.service.library_tasks(limit=3)
        self.assertIn(job['job_id'],[item['job_id'] for item in page['tasks']])
        self.assertEqual(len(page['tasks']),4)
        next_page=self.service.library_tasks(after=page['next_cursor'],limit=3)
        self.assertEqual(len(next_page['tasks']),3)
        self.assertNotEqual(page['next_cursor'],next_page['next_cursor'])

    def test_old_worker_decision_reasons_are_visible_without_rewriting_it(self):
        self.fixture(1);job=self.service.library_auto('legacy-task-reason1')
        row=self.records.get(job['job_id']);data=row['data'];key=data['files'][0]['key']
        plan=self.records.put('library_analysis',{'decisions':[{'key':key,'reason':'season evidence incomplete','confidence':.85,'category':'main'}]})
        self.records.put('library_auto_item',{'analysis_plan_id':plan['id']},key_hash=digest(['library-auto-item',row['id'],0]))
        data['results']=[{'key':key,'state':'needs_review','error_code':'automatic_match_uncertain'}]
        self.records.update(row,'completed_with_warnings',data)
        details=self.service.library_task_details(row['id'])
        self.assertEqual(details['results'][0]['reason'],'season evidence incomplete')
        self.assertEqual(details['results'][0]['confidence'],.85)
        self.assertTrue(details['results'][0]['source_path'])
        self.assertNotIn('reason',self.records.get(row['id'])['data']['results'][0])

    def test_subtitle_reasons_and_current_links_are_visible_with_credentials_removed(self):
        from media_mcp.storage.media import upsert_media_subtitle
        self.fixture(1);job=self.service.library_auto('subtitle-details-1')
        row=self.records.get(job['job_id']);data=row['data'];file=data['files'][0]
        reason='HTTP denied https://user:fixture-password@example.org/file?token=fixture-query Authorization: Bearer fixture-bearer token=fixture-token'
        upsert_media_subtitle(None,file['source_path']+'.srt',file['target_path']+'.srt',matched_video_source_path=file['source_path'],matched_video_target_path=file['target_path'],status='failed',reason=reason)
        data['results']=[{'key':file['key'],'state':'needs_review','error_code':'automatic_subtitle_review'}]
        self.records.update(row,'completed_with_warnings',data)
        result=self.service.library_task_details(row['id'])['results'][0]
        self.assertEqual(result['current_mapping']['target_path'],file['target_path'])
        self.assertEqual(result['subtitle_records'][0]['status'],'failed')
        rendered=json.dumps(result)
        for value in ('fixture-password','fixture-query','fixture-bearer','fixture-token'):self.assertNotIn(value,rendered)
        self.assertEqual(self.db.execute('SELECT reason FROM media_subtitle').scalar(),reason)

if __name__=='__main__':unittest.main()
