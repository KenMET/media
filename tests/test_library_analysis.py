import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from media_mcp.application.library_analysis import LibraryAnalysis,Decision,validate_decision,manifest
from media_mcp.platform.service import PlatformService
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task
from media_mcp.adapters.codex import CodexError
import test_collections as fixtures
Provider=fixtures.Provider

URL='https://www.themoviedb.org/movie/42-test'

class FakeAI:
    def __init__(self,category='main',identity=None,change=None):
        self.payloads=[];self.category=category;self.identity=identity or Provider().detail('movie:42');self.change=change
    def analyze(self,payload,**callbacks):
        self.payloads.append(payload)
        callbacks['on_thread']('fixture-thread');callbacks['on_submitting']();callbacks['on_turn']('fixture-turn')
        if self.change:self.change()
        identity=self.identity
        url=URL if identity['kind']=='movie' else 'https://www.themoviedb.org/tv/123-test/season/1'
        return {'decisions':[{'key':f['key'],'category':self.category,'identity':identity,'season':None if identity['kind']=='movie' or self.category=='extra' else 1,
            'episode':None if identity['kind']=='movie' or self.category=='extra' else 1,'confidence':.95,'reason':'Fixture research and duration assessment','sources':[url]} for f in payload['requested_files']]},[url]

class AnalysisTests(unittest.TestCase):
    setUp=fixtures.CollectionsTests.setUp
    fixture=fixtures.CollectionsTests.fixture
    identify=fixtures.CollectionsTests.identify

    def process(self,job,ai=None,probe=None):
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library');self.assertIsNotNone(claimed)
        process_task(jobs,claimed,analysis_client=ai,analysis_probe=probe or (lambda path:7200))
        jobs.finish(claimed)
        result=self.service.collection_task(job['job_id'])
        return result,self.service.collection_analysis_plan(result['analysis_plan_id'])

    def test_unknown_identity_uses_full_directory_paths_and_is_preview_only(self):
        ident=self.fixture(1);source,target=self.paths[0]
        subtitle=source.with_suffix('.srt');subtitle.write_text('subtitle must not be read')
        before=(source.read_bytes(),source.stat().st_ino,target.stat().st_ino)
        job=self.service.collection_analyze(ident,'analysis-fullpath-1');ai=FakeAI()
        result,plan=self.process(job,ai)
        payload=ai.payloads[0]
        self.assertEqual(payload['requested_files'][0]['source_path'],str(source))
        self.assertIn(str(subtitle),payload['directory_files'])
        self.assertNotIn('subtitle must not be read',str(payload))
        self.assertTrue(plan['ai_used']);self.assertTrue(plan['decisions'][0]['applicable'])
        self.assertIsNone(self.db.execute('SELECT media_tmdb_id FROM media_link').scalar())
        key=plan['decisions'][0]['key']
        saved=self.service.collection_analysis_apply(plan['plan_id'],[key])
        self.assertEqual(self.service.collection_analysis_apply(plan['plan_id'],[key]),saved)
        self.assertEqual(self.db.execute('SELECT media_tmdb_id FROM media_link').scalar(),42)
        self.assertEqual((source.read_bytes(),source.stat().st_ino,target.stat().st_ino),before)

    def test_confirmed_normal_files_take_rule_path_without_ai(self):
        ident=self.identify(self.fixture());ai=Mock()
        job=self.service.collection_analyze(ident,'rules-existing-01')
        result,plan=self.process(job,ai,lambda path:1400)
        self.assertFalse(plan['ai_used']);ai.analyze.assert_not_called()
        self.assertTrue(all(d['source']=='rule' and d['applicable'] for d in plan['decisions']))

    def test_reidentification_refreshes_card_metadata_without_erasing_overview(self):
        ident=self.identify(self.fixture(1))
        self.paths[0][0].write_bytes(b'changed-edition')
        identity={**Provider().detail('tv:123'),'title':'新的作品名称'}
        _,plan=self.process(self.service.collection_analyze(ident,'refresh-title-001'),FakeAI(identity=identity))
        self.service.collection_analysis_apply(plan['plan_id'],[plan['decisions'][0]['key']])
        detail=self.service.collection(ident)
        self.assertEqual(detail['title'],'新的作品名称')
        self.assertEqual(detail['overview'],'A test collection')

    def test_large_duration_difference_goes_to_ai_and_can_be_extra(self):
        ident=self.identify(self.fixture());short=self.paths[2][0]
        job=self.service.collection_analyze(ident,'duration-outlier-1')
        ai=FakeAI('extra',Provider().detail('tv:123'))
        result,plan=self.process(job,ai,lambda path:200 if path==str(short) else 1400)
        self.assertEqual(len(ai.payloads[0]['requested_files']),1)
        self.assertEqual(ai.payloads[0]['requested_files'][0]['fallback_reason'],'duration_outlier')
        self.assertEqual(ai.payloads[0]['peer_median_seconds'],1400)
        item=next(d for d in plan['decisions'] if d['source']=='ai')
        self.service.collection_analysis_apply(plan['plan_id'],[item['key']])
        detail=self.service.collection(ident)
        self.assertEqual(detail['summary']['extras'],1)
        self.assertEqual(detail['summary']['main_files'],2)

    def test_long_bonus_and_unavailable_duration_are_not_blindly_filtered(self):
        ident=self.fixture(1);self.service.collection_classify(ident,'extra')
        ai=FakeAI();job=self.service.collection_analyze(ident,'long-bonus-check1')
        _,plan=self.process(job,ai,lambda path:7200)
        self.assertTrue(plan['ai_used'])
        self.assertEqual(ai.payloads[0]['requested_files'][0]['fallback_reason'],'extra_with_long_duration')

    def test_missing_probe_goes_to_ai_without_inventing_duration(self):
        ident=self.fixture(1);ai=FakeAI()
        _,plan=self.process(self.service.collection_analyze(ident,'probe-missing-01'),ai,lambda path:None)
        self.assertIsNone(ai.payloads[0]['requested_files'][0]['duration_seconds'])
        self.assertEqual(ai.payloads[0]['requested_files'][0]['fallback_reason'],'duration_unavailable')

    def test_cached_runtime_disagreement_uses_ai_even_without_peers(self):
        ident=self.identify(self.fixture(1))
        self.db.execute("UPDATE media_library_identity SET data=json_set(data,'$.runtime_seconds',7200)")
        ai=FakeAI()
        self.process(self.service.collection_analyze(ident,'metadata-duration1'),ai,lambda path:600)
        self.assertEqual(ai.payloads[0]['requested_files'][0]['fallback_reason'],'duration_metadata_mismatch')
        self.assertEqual(ai.payloads[0]['requested_files'][0]['expected_runtime_seconds'],7200)

    def test_model_cannot_replace_requested_file_keys(self):
        ident=self.fixture(1);ai=FakeAI();original=ai.analyze
        def wrong_key(*args,**kwargs):
            output,sources=original(*args,**kwargs);output['decisions'][0]['key']='m:99999';return output,sources
        ai.analyze=wrong_key
        job=self.service.collection_analyze(ident,'wrong-file-key-01')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        with self.assertRaisesRegex(ValueError,'analysis_selection_changed'):
            process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:7200)
        self.assertIsNone(self.db.execute('SELECT media_tmdb_id FROM media_link').scalar())

    def test_ai_cannot_confirm_a_conflicting_source_target_pair(self):
        ident=self.fixture(1);source,target=self.paths[0];target.unlink();target.write_bytes(b'another video')
        _,plan=self.process(self.service.collection_analyze(ident,'conflict-analysis1'),FakeAI())
        self.assertFalse(plan['decisions'][0]['applicable'])
        with self.assertRaisesRegex(ValueError,'analysis_result_not_applicable'):
            self.service.collection_analysis_apply(plan['plan_id'],[plan['decisions'][0]['key']])
        self.assertEqual(source.read_bytes(),b'original-1');self.assertEqual(target.read_bytes(),b'another video')

    def test_changed_source_or_directory_cannot_publish_a_plan(self):
        for change in ('source','directory'):
            with self.subTest(change=change):
                if change=='source':
                    ident=self.fixture(1);source=self.paths[0][0]
                    callback=lambda:source.write_bytes(b'changed-source')
                else:
                    source=self.paths[0][0]
                    # The previous task remains running after the intentionally interrupted fixture.
                    self.db.execute("UPDATE media_mcp_record SET state='needs_review' WHERE kind='library_task'")
                    self.db.execute("UPDATE media_processing_job SET state='completed'")
                    ident=self.service.collections()['collections'][0]['collection_id']
                    callback=lambda:source.with_suffix('.new.srt').write_text('new sidecar')
                job=self.service.collection_analyze(ident,'changed-context-'+change)
                jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
                with self.assertRaisesRegex(ValueError,'collection_changed_rebuild_plan|analysis_directory_changed'):
                    process_task(jobs,claimed,analysis_client=FakeAI(change=callback),analysis_probe=lambda p:7200)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='library_analysis'").scalar(),0)

    def test_model_cannot_invent_evidence_ids_or_tv_seasons(self):
        base={'key':'m:1','category':'main','identity':Provider().detail('movie:42'),'confidence':.95,'reason':'Evidence','sources':[URL]}
        self.assertFalse(validate_decision(Decision.model_validate(base),set())['applicable'])
        self.assertFalse(validate_decision(Decision.model_validate(base),{'https://www.themoviedb.org/movie/43-other'})['applicable'])
        tv={**base,'identity':Provider().detail('tv:123'),'season':2,'episode':1,'sources':['https://www.themoviedb.org/tv/123-test/season/1']}
        self.assertFalse(validate_decision(Decision.model_validate(tv),set(tv['sources']))['applicable'])

    def test_tv_season_evidence_has_specific_rejection_and_season_link_is_accepted(self):
        root='https://www.themoviedb.org/tv/123-test'
        data={'key':'m:1','category':'main','identity':Provider().detail('tv:123'),
              'season':2,'episode':1,'confidence':.98,'reason':'Matched','sources':[root]}
        rejected=validate_decision(Decision.model_validate(data),set(),search_count=1)
        self.assertFalse(rejected['applicable'])
        self.assertEqual(rejected['review_code'],'analysis_season_evidence_missing')
        data['sources'].append(root+'/season/2')
        self.assertTrue(validate_decision(Decision.model_validate(data),set(),search_count=1)['applicable'])

    def test_indexed_tmdb_id_can_use_open_attempt_with_corroborating_source(self):
        wiki='https://en.wikipedia.org/wiki/Test_film'
        item=Decision.model_validate({'key':'m:1','category':'main','identity':Provider().detail('movie:42'),
            'confidence':.9,'reason':'TMDB body blocked; indexed ID and accessible reference agree','sources':[URL,wiki]})
        opened={URL+'?language=zh-CN',wiki}
        result=validate_decision(item,opened)
        self.assertTrue(result['applicable']);self.assertIn(wiki,result['sources'])
        self.assertIn(URL+'?language=zh-CN',result['sources'])

    def test_indexed_references_require_observed_search_and_are_labelled(self):
        item=Decision.model_validate({'key':'m:1','category':'main','identity':Provider().detail('movie:42'),
            'confidence':.9,'reason':'Indexed references match title year and runtime','sources':[URL]})
        self.assertFalse(validate_decision(item,set())['applicable'])
        result=validate_decision(item,set(),search_count=2)
        self.assertTrue(result['applicable'])
        self.assertEqual(result['source_provenance'][URL],'search_reference')
        self.assertEqual(result['observed_search_count'],2)

    def test_research_links_cannot_include_private_or_unopened_addresses(self):
        item=Decision.model_validate({'key':'m:1','category':'extra','confidence':.9,'reason':'Untrusted sources',
            'sources':['javascript:alert(1)','https://127.0.0.1/private','https://nas.lan/private',URL]})
        result=validate_decision(item,{'javascript:alert(1)','https://127.0.0.1/private','https://nas.lan/private'})
        self.assertFalse(result['applicable']);self.assertEqual(result['sources'],[])

    def test_unopened_or_low_confidence_result_remains_unapplied(self):
        ident=self.fixture(1);ai=FakeAI()
        original=ai.analyze
        def no_sources(*args,**kwargs):
            result,_=original(*args,**kwargs);return result,[]
        ai.analyze=no_sources
        result,plan=self.process(self.service.collection_analyze(ident,'no-evidence-001'),ai)
        self.assertEqual(result['state'],'completed_with_warnings')
        with self.assertRaisesRegex(ValueError,'analysis_result_not_applicable'):
            self.service.collection_analysis_apply(plan['plan_id'],[plan['decisions'][0]['key']])
        self.assertIsNone(self.db.execute('SELECT media_tmdb_id FROM media_link').scalar())

    def test_model_unknown_turn_is_not_automatically_resubmitted(self):
        ident=self.fixture(1);job=self.service.collection_analyze(ident,'unknown-ai-turn1')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library');ai=Mock()
        def failed(payload,**callbacks):
            callbacks['on_submitting']();raise CodexError('connection_failed',outcome_unknown=True)
        ai.analyze.side_effect=failed
        with self.assertRaises(CodexError):process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:7200)
        with self.assertRaisesRegex(ValueError,'analysis_ai_outcome_unknown'):
            process_task(jobs,claimed,analysis_client=ai,analysis_probe=lambda p:7200)
        self.assertEqual(ai.analyze.call_count,1)

    def test_preview_scope_permissions_and_directory_staleness(self):
        ident=self.fixture(1);job=self.service.collection_analyze(ident,'private-analysis1')
        self.assertEqual(self.service.collection_analyze(ident,'private-analysis1')['job_id'],job['job_id'])
        _,plan=self.process(job,FakeAI())
        viewer=PlatformService(self.alice,self.accounts,self.records)
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            viewer.collection_analysis_plan(plan['plan_id'])
        self.paths[0][0].with_suffix('.srt').write_text('added later')
        with self.assertRaisesRegex(ValueError,'analysis_directory_changed'):
            self.service.collection_analysis_apply(plan['plan_id'],[plan['decisions'][0]['key']])

    def test_folder_mode_covers_indexed_files_outside_one_collection(self):
        from media_mcp.storage.inventory import Inventory
        ident=self.fixture(1);source=self.paths[0][0].parent/'Other.Movie.mkv';source.write_bytes(b'other')
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        job=self.service.collection_analyze(ident,'folder-analysis-1',folder=True)
        self.assertEqual(job['total'],2)
        _,plan=self.process(job,FakeAI())
        self.assertEqual(len(plan['decisions']),2)

    def test_single_file_in_flat_download_root_does_not_send_other_movies(self):
        ident=self.fixture(1);other=self.paths[0][0].parent/'Unrelated.Movie.mkv';other.write_bytes(b'other movie')
        ai=FakeAI()
        self.process(self.service.collection_analyze(ident,'flat-root-private1'),ai)
        self.assertNotIn(str(other),ai.payloads[0]['directory_files'])

    def test_folder_mode_expands_nested_indexed_videos(self):
        from media_mcp.storage.inventory import Inventory
        ident=self.fixture(1);nested=self.paths[0][0].parent/'Nested';nested.mkdir()
        (nested/'Other.mkv').write_bytes(b'nested video')
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        job=self.service.collection_analyze(ident,'nested-folder-01',folder=True)
        self.assertEqual(job['total'],2)

if __name__=='__main__':unittest.main()
