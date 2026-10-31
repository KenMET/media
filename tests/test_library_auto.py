import json,os,re
from pathlib import Path
import unittest
from unittest.mock import patch
import test_collections as fixtures
from media_mcp.storage.inventory import Inventory
from media_mcp.storage.media import _client,upsert_media_subtitle
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task
from media_mcp.platform.service import PlatformService


class AutoAI:
    def check_connection(self):pass
    def __init__(self):self.calls=0
    def analyze(self,payload,**callbacks):
        self.calls+=1;callbacks['on_submitting']()
        decisions=[];opened=[]
        for file in payload['requested_files']:
            if 'Mystery' in file['source_path']:
                decisions.append({'key':file['key'],'category':'unknown','confidence':.3,'reason':'No reliable match','sources':[]});continue
            hint=file['filename_hints'];season=hint.get('season_hint');episode=hint.get('episode_hint')
            number=int(re.search(r'(\d+)(?!.*\d)',hint['title'])[1]) if season is None and re.search(r'\d+',hint['title']) else 42
            ident='tv:123' if season is not None else 'movie:'+str(1000+number)
            identity=fixtures.Provider().detail(ident)
            identity['title']='\u5267\u96c6' if season is not None else '\u5f71\u7247 '+str(number)
            url='https://www.themoviedb.org/'+ident.replace(':','/')+(f'/season/{season}' if season is not None else '')
            opened.append(url)
            decisions.append({'key':file['key'],'category':'main','identity':identity,'season':season,'episode':episode,
                'confidence':.95,'reason':'Fixture matched','sources':[url]})
        return {'decisions':decisions},opened


class AutoSubtitles:
    def __init__(self):self.calls=0
    def _run_path_summary_locked(self,path,send_notify=False):
        self.calls+=1
        db=_client(None);row=db.execute('SELECT * FROM media_link WHERE source_path=:path OR target_path=:path',{'path':path}).mappings().one()
        sub=Path(row['target_path']).with_suffix('.zh.srt');sub.write_text('1\n00:00:00,000 --> 00:00:01,000\n\u6d4b\u8bd5\u5b57\u5e55\n')
        upsert_media_subtitle(None,str(sub),str(sub),matched_video_source_path=row['source_path'],matched_video_target_path=row['target_path'],language='zh',format='srt',status='verified')
        return {'media_count':1,'handled':1,'failed':0,'missing':0,'review':0}


class AutoTests(unittest.TestCase):
    setUp=fixtures.CollectionsTests.setUp
    fixture=fixtures.CollectionsTests.fixture

    def add_movies(self,count=1):
        if not hasattr(self,'paths'):self.fixture(1)
        sources=[]
        for number in range(1,count+1):
            source=self.paths[0][0].parent/f'Unmatched Movie {number}.mkv';source.write_bytes(b'movie-'+str(number).encode());sources.append(source)
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        return sources

    def run_auto(self,job,ai=None,agent=None):
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library');self.assertIsNotNone(claimed)
        process_task(jobs,claimed,analysis_client=ai or AutoAI(),analysis_probe=lambda p:1400,subtitle_agent=agent or AutoSubtitles())
        jobs.finish(claimed)
        return self.service.collection_task(job['job_id'])

    def test_whole_library_ignores_pagination_and_automatically_saves_links_and_subtitles(self):
        self.fixture(1);sources=self.add_movies(26);before=[(s.read_bytes(),s.stat().st_ino) for s in sources]
        self.assertEqual(self.service.collections()['total'],27)
        self.assertEqual(len(self.service.collections()['collections']),24)
        job=self.service.library_auto('whole-library-001')
        self.assertEqual(job['total'],27)
        result=self.run_auto(job)
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['completed'],27);self.assertEqual(result['summary']['linked'],26)
        self.assertEqual(result['summary']['subtitles'],27)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),27)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='library_analysis' AND state='preview'").scalar(),0)
        for source,expected in zip(sources,before):
            row=self.db.execute('SELECT target_path,agent_result_json FROM media_link WHERE source_path=:source',{'source':str(source)}).mappings().one()
            self.assertTrue(os.path.samefile(source,row['target_path']))
            self.assertEqual((source.read_bytes(),source.stat().st_ino),expected)
            annotation=json.loads(self.db.execute('SELECT data FROM media_library_identity WHERE path=:path',{'path':str(source)}).scalar())
            self.assertEqual(annotation['approval_mode'],'automatic')
        again=self.service.library_auto('whole-library-002')
        self.assertEqual(again['total'],0);self.assertEqual(again['state'],'completed')

    def test_global_missing_subtitle_reuses_confirmed_identity_without_ai(self):
        self.fixture(1)
        first=self.run_auto(self.service.library_auto('confirmed-global-first'))
        self.assertEqual(first['state'],'completed')
        for row in self.db.execute('SELECT target_subtitle_path FROM media_subtitle').mappings():
            Path(row['target_subtitle_path']).unlink()
        ai=AutoAI()
        second=self.run_auto(self.service.library_auto('confirmed-global-repair'),ai=ai)
        self.assertEqual(second['state'],'completed',second)
        self.assertEqual(second['succeeded'],1)
        self.assertEqual(ai.calls,0)

    def test_global_all_is_rejected_before_queue_or_ai(self):
        self.fixture(1)
        with self.assertRaisesRegex(ValueError,'library_auto_all_requires_collection'):
            self.service.library_auto('global-all-blocked',scope='all')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='library_task'").scalar(),0)

    def test_unknown_one_does_not_stop_other_work(self):
        self.fixture(1);sources=self.add_movies(1);unknown=sources[0].parent/'Mystery.mkv';unknown.write_bytes(b'uncertain')
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        result=self.run_auto(self.service.library_auto('unknown-continue-1'))
        self.assertEqual(result['state'],'completed_with_warnings')
        self.assertEqual(result['total'],3);self.assertEqual(result['completed'],3)
        self.assertEqual(result['review_count'],1);self.assertEqual(len(result['results']),1)
        self.assertEqual(result['results'][0]['error_code'],'automatic_match_uncertain')
        self.assertTrue(self.db.execute('SELECT target_path FROM media_link WHERE source_path=:path',{'path':str(sources[0])}).scalar())
        self.assertEqual(unknown.read_bytes(),b'uncertain')

    def test_returned_subtitle_review_can_be_retried_without_unknown_fence(self):
        from unittest.mock import Mock
        self.fixture(1)
        agent=Mock();agent._last_model_error=None
        agent._run_path_summary_locked.return_value={'media_count':1,'handled':0,'review':1}
        result=self.run_auto(self.service.library_auto('returned-review-001'),agent=agent)
        self.assertEqual(result['results'][0]['error_code'],'automatic_subtitle_review')
        child=self.records.decode(self.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_auto_item'").mappings().one())
        self.assertIsNone(child['data'].get('subtitle_inflight'))
        # Simulate the legacy marker left after that same known return.
        self.records.update(child,child['state'],{**child['data'],'subtitle_inflight':child['data']['files'][0]['key']})
        result=self.run_auto(self.service.library_auto('returned-review-002'))
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['succeeded'],1)

    def test_extracted_chinese_subtitle_is_ready_and_not_processed_again(self):
        self.assert_ready_subtitle_status('embedded_extracted')

    def test_downloaded_chinese_subtitle_is_ready_and_not_processed_again(self):
        self.assert_ready_subtitle_status('downloaded')

    def assert_ready_subtitle_status(self,status):
        class ReadySubtitles(AutoSubtitles):
            def _run_path_summary_locked(self,path,send_notify=False):
                result=super()._run_path_summary_locked(path,send_notify)
                _client(None).execute("UPDATE media_subtitle SET status=:status",{'status':status})
                return result
        self.fixture(1);agent=ReadySubtitles()
        result=self.run_auto(self.service.library_auto('ready-chinese-001'),agent=agent)
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['summary']['subtitles'],1)
        self.assertEqual(self.service.collections()['collections'][0]['summary']['subtitle_verified'],1)
        again=self.service.library_auto('ready-chinese-002')
        self.assertEqual(again['total'],0)
        self.assertEqual(agent.calls,1)

    def test_unknown_file_does_not_block_other_files_in_same_collection(self):
        self.fixture(2)
        task=self.service.library_auto('partially-fenced-001')
        file=self.records.get(task['job_id'])['data']['files'][0]
        self.records.put('library_auto_item',{'owner':self.admin.id,'action':'analysis',
            'ai_inflight':True,'files':[file]},'needs_review')
        ai=AutoAI();result=self.run_auto(task,ai=ai)
        self.assertEqual(result['review_count'],1,result)
        self.assertEqual(result['succeeded'],1,result)
        self.assertEqual(result['results'][0]['error_code'],'analysis_ai_outcome_unknown')
        self.assertEqual(ai.calls,1)

    def test_unknown_subtitle_transport_keeps_inflight_marker(self):
        from media_mcp.adapters.codex import CodexError
        from unittest.mock import Mock
        self.fixture(1);agent=Mock()
        agent._run_path_summary_locked.side_effect=CodexError('model_connection_lost',outcome_unknown=True)
        jobs=MediaJobs();jobs.initialize();task=self.service.library_auto('unknown-subtitle-001');job=jobs.claim('library')
        with self.assertRaises(CodexError):
            process_task(jobs,job,analysis_client=AutoAI(),analysis_probe=lambda p:1400,subtitle_agent=agent)
        child=self.records.decode(self.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_auto_item'").mappings().one())
        self.assertEqual(child['data']['subtitle_inflight'],child['data']['files'][0]['key'])

    def test_automatic_extras_keep_their_parent_collection(self):
        self.fixture(1);source,target=self.paths[0]
        parent=source.parent/'Work';parent.mkdir();moved=parent/source.name;source.rename(moved)
        self.db.execute('UPDATE media_link SET source_path=:new WHERE source_path=:old',{'new':str(moved),'old':str(source)})
        bonus=parent/'Featurettes';bonus.mkdir()
        (bonus/'Clip A.mkv').write_bytes(b'clip a');(bonus/'Clip B.mkv').write_bytes(b'clip b')
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        job=self.service.library_auto('extras-auto-001')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        process_task(jobs,claimed,analysis_client=AutoAI(),analysis_probe=lambda path:120 if 'Featurettes' in path else 1400,subtitle_agent=AutoSubtitles())
        result=self.service.collection_task(job['job_id']);self.assertEqual(result['state'],'completed',result)
        page=self.service.collections();self.assertEqual(page['total'],1)
        self.assertEqual(page['collections'][0]['summary']['extras'],2)
        self.assertEqual(page['collections'][0]['summary']['files'],3)

    def test_quota_failure_pauses_task_without_marking_later_files_failed(self):
        from media_mcp.adapters.codex import CodexError
        from media_mcp.runtime.model_retry import ModelServiceDeferred
        from media_mcp.runtime.library_worker import record_failure
        from unittest.mock import Mock
        self.fixture(1);self.add_movies(3)
        ai=Mock();ai.analyze.side_effect=CodexError('rate_limited')
        job=self.service.library_auto('quota-auto-0001')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        with self.assertRaises(ModelServiceDeferred) as caught:
            process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:1400)
        error,retry=record_failure(jobs,claimed,caught.exception)
        jobs.finish(claimed,error=error,review_required=not retry)
        result=self.service.collection_task(job['job_id'])
        self.assertEqual(result['state'],'queued')
        self.assertEqual(result['completed'],0)
        self.assertEqual(ai.analyze.call_count,1)
        self.assertIsNone(jobs.claim('library'))
        self.db.execute("UPDATE media_processing_job SET next_attempt_at=datetime('now','-1 second') WHERE id=:id",claimed)
        row=self.records.get(job['job_id'])
        self.records.update(row,row['state'],{**row['data'],'quota_wait':{**row['data']['quota_wait'],'next_check_at':'2000-01-01 00:00:00'}})
        resumed=jobs.claim('library')
        process_task(jobs,resumed,analysis_client=AutoAI(),analysis_probe=lambda p:1400,subtitle_agent=AutoSubtitles())
        jobs.finish(resumed)
        result=self.service.collection_task(job['job_id'])
        self.assertEqual('completed',result['state'])
        self.assertEqual(4,result['completed'])


    def test_repeated_start_and_replayed_alias_do_not_start_another_run(self):
        original=self.fixture(1)
        first=self.service.library_auto('auto-original-001')
        alias=self.service.library_auto('auto-alias-00001')
        self.assertEqual(first['job_id'],alias['job_id'])
        self.run_auto(first)
        detail=self.service.collection(original)
        self.assertNotEqual(detail['collection_id'],original)
        self.assertEqual(detail['title_id'],'tv:123')
        self.assertEqual(self.service.library_auto('auto-alias-00001')['job_id'],first['job_id'])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_processing_job WHERE stage='library'").scalar(),1)

    def test_existing_target_is_not_overwritten_by_automatic_mapping(self):
        self.fixture(1);sources=self.add_movies(1)
        job=self.service.library_auto('target-conflict-001')
        from media_mcp.ingest.domain.path_builder import build_hardlink_path
        target=Path(build_hardlink_path({'kind':'movie','title':{'zh':'\u5f71\u7247 1','original':'Test Collection'},'year':2024},'.mkv',os.environ['MEDIA_LIBRARY_ROOT']))
        target.parent.mkdir(exist_ok=True);target.write_bytes(b'independent-target')
        inode=target.stat().st_ino
        result=self.run_auto(job)
        self.assertEqual(result['state'],'completed_with_warnings',result)
        self.assertEqual((target.read_bytes(),target.stat().st_ino),(b'independent-target',inode))
        self.assertIsNone(self.db.execute('SELECT id FROM media_link WHERE source_path=:path',{'path':str(sources[0])}).scalar())

    def test_valid_but_lower_confidence_ai_stays_unapplied(self):
        self.fixture(1)
        ai=AutoAI();analyze=ai.analyze
        def uncertain(*args,**kwargs):
            output,opened=analyze(*args,**kwargs)
            for decision in output['decisions']:decision['confidence']=.85
            return output,opened
        ai.analyze=uncertain
        result=self.run_auto(self.service.library_auto('low-confidence-001'),ai)
        self.assertEqual(result['review_count'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_library_identity').scalar(),0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_subtitle').scalar(),0)

    def test_permissions_and_changed_file_are_not_bypassed(self):
        ident=self.fixture(1)
        viewer=PlatformService(self.alice,self.accounts,self.records)
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):viewer.library_auto('viewer-auto-001')
        job=self.service.library_auto('changed-auto-001')
        self.paths[0][0].write_bytes(b'replaced-after-queue')
        ai=AutoAI();result=self.run_auto(job,ai)
        self.assertEqual(result['state'],'completed_with_warnings');self.assertEqual(ai.calls,0)
        self.assertIsNone(self.db.execute('SELECT media_tmdb_id FROM media_link').scalar())

    def test_committed_mapping_resumes_without_repeating_ai_or_link_creation(self):
        ident=self.fixture(1);sources=self.add_movies(1)
        collection=next(g for g in self.service.collections()['collections'] if g['summary']['mapped']==0)
        job=self.service.library_auto('crash-auto-0001',collection_id=collection['collection_id'],scope='all')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library');ai=AutoAI();agent=AutoSubtitles()
        update=self.records.update
        def crash(row,state,data=None):
            if row['kind']=='library_auto_item' and data and any(value.get('created') for value in data.get('auto_mappings',{}).values()):raise SystemExit('fixture crash after link commit')
            return update(row,state,data)
        with patch('media_mcp.storage.records.Records.update',side_effect=crash):
            with self.assertRaises(SystemExit):process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=agent)
        source=sources[0];target=self.db.execute('SELECT target_path FROM media_link WHERE source_path=:source',{'source':str(source)}).scalar()
        self.assertTrue(os.path.samefile(source,target));inode=Path(target).stat().st_ino
        process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=agent)
        result=self.service.collection_task(job['job_id']);self.assertEqual(result['state'],'completed',result)
        self.assertEqual(ai.calls,1);self.assertEqual(Path(target).stat().st_ino,inode)

    def test_interrupted_subtitle_request_is_not_silently_repeated(self):
        self.fixture(1);job=self.service.library_auto('subtitle-unknown1')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library');ai=AutoAI();agent=AutoSubtitles()
        with patch.object(agent,'_run_path_summary_locked',side_effect=SystemExit('fixture interrupted')) as method:
            with self.assertRaises(SystemExit):process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=agent)
            process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:1400,subtitle_agent=agent)
            self.assertEqual(method.call_count,1)
        result=self.service.collection_task(job['job_id']);self.assertEqual(result['state'],'completed_with_warnings')
        self.assertEqual(result['results'][0]['error_code'],'automatic_subtitle_outcome_unknown')

    def test_mutation_lock_loss_stops_run_instead_of_becoming_a_per_file_warning(self):
        self.fixture(1);sources=self.add_movies(1)
        job=self.service.library_auto('auto-lock-loss-001')
        with patch('media_mcp.runtime.library_worker.repair_mapping',side_effect=RuntimeError('media_mutation_lock_lost')):
            with self.assertRaisesRegex(RuntimeError,'media_mutation_lock_lost'):self.run_auto(job)
        self.assertIsNone(self.db.execute('SELECT id FROM media_link WHERE source_path=:path',{'path':str(sources[0])}).scalar())
        self.assertEqual(self.service.collection_task(job['job_id'])['state'],'running')

if __name__=='__main__':unittest.main()
