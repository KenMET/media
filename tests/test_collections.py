import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

from media_mcp.platform.service import PlatformService
from media_mcp.storage.media import upsert_media_link
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task
import test_platform


class Provider:
    def detail(self,title_id):
        kind,ident=title_id.split(':')
        return {'title_id':title_id,'kind':kind,'tmdb_id':int(ident),'title':'测试合集',
                'original_title':'Test Collection','original_language':'en','date':'2024-01-01',
                'poster_url':'https://image.tmdb.org/t/p/w342/test.jpg','rating_source':'TMDB'}
    def get(self,path,**params):
        if '/season/' in path:return {'episodes':[{'episode_number':i} for i in range(1,5)]}
        return {'overview':'A test collection','seasons':[{'season_number':1},{'season_number':2}]}


class CollectionsTests(unittest.TestCase):
    setUp=test_platform.PlatformTests.setUp

    def fixture(self,count=3):
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);source.mkdir()
        library=Path(os.environ['MEDIA_LIBRARY_ROOT']);library.mkdir()
        self.paths=[]
        for i in range(1,count+1):
            season=1 if i<=2 else 2
            src=source/f'Show.S{season:02d}E{i:02d}.mkv';src.write_bytes(b'original-'+str(i).encode())
            target=library/'series'/'同一作品'/f'第{season:02d}季'/f'同一作品 - S{season:02d}E{i:02d} - 2024.mkv'
            target.parent.mkdir(parents=True,exist_ok=True);os.link(src,target)
            upsert_media_link(None,str(src),str(target),media_name=target.stem,status='linked')
            self.paths.append((src,target))
        self.service=PlatformService(self.admin,self.accounts,self.records,tmdb=Provider())
        return self.service.collections()['collections'][0]['collection_id']

    def identify(self,collection):
        preview=self.service.collection_identify(collection,'tv:123')
        return self.service.collection_identity_apply(preview['plan_id'])['collection_id']

    def work(self,job,agent=None):
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        self.assertIsNotNone(claimed)
        process_task(jobs,claimed,agent)
        jobs.finish(claimed)
        return self.service.collection_task(job['job_id'])

    def test_group_before_pagination_and_provisional_episode_hints(self):
        ident=self.fixture(105)
        page=self.service.collections(limit=1)
        self.assertEqual(page['total'],1)
        self.assertIsNone(page['next_cursor'])
        group=page['collections'][0]
        self.assertEqual(group['summary']['files'],105)
        self.assertFalse(group['identified']);self.assertIsNone(group['poster_url'])
        detail=self.service.collection(ident)
        self.assertEqual(len(detail['seasons']),2)
        self.assertTrue(all(s['provisional'] for s in detail['seasons']))
        self.assertEqual(sum(len(s['files']) for s in detail['seasons']),105)

    def test_confirmed_identity_poster_seasons_and_repeated_recognition(self):
        ident=self.fixture()
        before=[(src.read_bytes(),src.stat().st_ino,target.stat().st_ino) for src,target in self.paths]
        preview=self.service.collection_identify(ident,'tv:123')
        self.assertIsNone(self.db.execute('SELECT media_tmdb_id FROM media_link LIMIT 1').scalar())
        result=self.service.collection_identity_apply(preview['plan_id'])
        self.assertEqual(result['updated_files'],3)
        self.assertEqual(self.service.collection_identity_apply(preview['plan_id']),result)
        detail=self.service.collection(result['collection_id'])
        self.assertEqual(detail['poster_url'],'https://image.tmdb.org/t/p/w342/test.jpg')
        self.assertTrue(detail['identified']);self.assertEqual(detail['summary']['episodes'],3)
        self.assertFalse(any(s['provisional'] for s in detail['seasons']))
        second=self.service.collection_identify(result['collection_id'],'tv:123',season=1)
        self.assertEqual(second['total'],2)
        self.service.collection_identity_apply(second['plan_id'])
        for (src,target),expected in zip(self.paths,before):
            self.assertEqual((src.read_bytes(),src.stat().st_ino,target.stat().st_ino),expected)

    def test_unsupported_season_and_changed_preview_fail_closed(self):
        ident=self.fixture()
        with self.assertRaisesRegex(ValueError,'collection_season_requires_review'):
            self.service.collection_identify(ident,'tv:123',season_override=9)
        preview=self.service.collection_identify(ident,'tv:123')
        self.paths[0][0].write_bytes(b'changed-outside')
        with self.assertRaisesRegex(ValueError,'collection_changed_rebuild_plan'):
            self.service.collection_identity_apply(preview['plan_id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link WHERE media_tmdb_id IS NOT NULL').scalar(),0)

    def test_mapping_plan_queue_lease_and_exact_missing_link_repair(self):
        ident=self.identify(self.fixture())
        source,target=self.paths[0];target.unlink()
        preview=self.service.collection_mapping_plan(ident)
        self.assertEqual(sum(op['action']=='create_link' for op in preview['operations']),1)
        job=self.service.collection_mapping_apply(preview['plan_id'],'mapping-check-001')
        self.assertEqual(self.service.collection_mapping_apply(preview['plan_id'],'mapping-check-001')['job_id'],job['job_id'])
        self.assertFalse(target.exists())
        result=self.work(job)
        self.assertEqual(result['state'],'completed')
        self.assertTrue(os.path.samefile(source,target))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),3)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_version_change WHERE state!='done'").scalar(),0)

    def test_mapping_does_not_overwrite_replacement_or_unidentified_content(self):
        ident=self.fixture();source,target=self.paths[0];target.unlink()
        preview=self.service.collection_mapping_plan(ident)
        self.assertFalse(any(op['action']=='create_link' for op in preview['operations']))
        ident=self.identify(ident)
        preview=self.service.collection_mapping_plan(ident)
        job=self.service.collection_mapping_apply(preview['plan_id'],'mapping-check-002')
        target.write_bytes(b'unrelated-replacement')
        result=self.work(job)
        self.assertEqual(result['state'],'completed_with_warnings')
        self.assertEqual(target.read_bytes(),b'unrelated-replacement')
        self.assertEqual(source.read_bytes(),b'original-1')

    def test_subtitles_scope_repeated_request_and_preserved_valid_files(self):
        ident=self.identify(self.fixture())
        detail=self.service.collection(ident)
        key=detail['seasons'][0]['files'][0]['key']
        target=self.paths[0][1];subtitle=target.with_suffix('.zh.srt');subtitle.write_text('preserved subtitle')
        agent=Mock();agent._run_path_summary_locked.return_value={'handled':1,'media_count':1,'failed':0,'missing':0,'review':0}
        job=self.service.collection_subtitles(ident,'subtitle-check-01',selection=[key],mode='recheck')
        self.assertEqual(job['total'],1)
        self.assertEqual(self.service.collection_subtitles(ident,'subtitle-check-01',selection=[key],mode='recheck')['job_id'],job['job_id'])
        result=self.work(job,agent)
        self.assertEqual(result['state'],'completed')
        self.assertEqual(subtitle.read_text(),'preserved subtitle')
        agent._run_path_summary_locked.assert_called_once_with(str(self.paths[0][0]),send_notify=False)
        self.assertEqual(self.service.collection_subtitles(ident,'subtitle-check-01',selection=[key],mode='recheck')['job_id'],job['job_id'])

    def test_permissions_filter_before_grouping_and_do_not_leak_paths(self):
        ident=self.fixture()
        alice=PlatformService(self.alice,self.accounts,self.records,tmdb=Provider())
        self.assertEqual(alice.collections()['total'],0)
        media_id=self.db.execute('SELECT id FROM media_link ORDER BY id').scalar()
        self.accounts.grant(self.admin,'media',str(media_id),self.alice.id,'read')
        detail=alice.collection(ident)
        self.assertEqual(detail['summary']['files'],1)
        file=detail['seasons'][0]['files'][0]
        self.assertNotIn('source_path',file);self.assertNotIn('target_path',file)
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            alice.collection_identify(ident,'tv:123')
        plan=self.service.collection_identify(ident,'tv:123')
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            alice.collection_identity_apply(plan['plan_id'])

    def test_partial_identity_stays_one_collection_and_merges_editions(self):
        ident=self.fixture()
        preview=self.service.collection_identify(ident,'tv:123',season=1)
        new_id=self.service.collection_identity_apply(preview['plan_id'])['collection_id']
        page=self.service.collections()
        self.assertEqual(page['total'],1)
        self.assertEqual(page['collections'][0]['summary']['identity_pending'],1)
        self.assertEqual(self.service.collection(new_id)['summary']['files'],3)
        source=self.paths[0][0].parent/'version-two.mkv';source.write_bytes(b'edition-two')
        target=self.paths[0][1].with_suffix('.mp4');os.link(source,target)
        upsert_media_link(None,str(source),str(target),media_name='Another edition',media_type='tv',media_tmdb_id=123,season=1,episode=1,status='linked')
        detail=self.service.collection(new_id)
        episode=next(e for s in detail['seasons'] if s['season']==1 for e in s['episodes'] if e['episode']==1)
        self.assertEqual(len(episode['versions']),2)
        self.assertEqual(detail['summary']['episodes'],2)

    def test_unorganized_identification_and_mapping_preserve_source(self):
        ident=self.identify(self.fixture())
        from media_mcp.storage.inventory import Inventory
        source=self.paths[0][0].parent/'Loose.S01E04.mkv';source.write_bytes(b'unorganized-source')
        inventory=Inventory(self.records);scan=inventory.scan(self.admin.id);inventory.adopt(scan['scan_id'],self.admin.id)
        pending=next(g for g in self.service.collections()['collections'] if not g['title_id'])
        recognized=self.service.collection_identify(pending['collection_id'],'tv:123')
        self.service.collection_identity_apply(recognized['plan_id'])
        file=next(f for season in self.service.collection(ident)['seasons'] for f in season['files'] if f['source_path']==str(source))
        preview=self.service.collection_mapping_plan(ident,selection=[file['key']])
        self.assertEqual(preview['operations'][0]['action'],'create_link')
        job=self.service.collection_mapping_apply(preview['plan_id'],'loose-mapping-001')
        result=self.work(job)
        self.assertEqual(result['state'],'completed')
        self.assertEqual(source.read_bytes(),b'unorganized-source')
        target=preview['operations'][0]['target_path']
        self.assertTrue(os.path.samefile(source,target))
        self.assertEqual(self.service.collections()['total'],1)

    def test_expired_lease_does_not_mutate_files(self):
        ident=self.identify(self.fixture());source,target=self.paths[0];target.unlink()
        preview=self.service.collection_mapping_plan(ident)
        job=self.service.collection_mapping_apply(preview['plan_id'],'expired-mapping-1')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        jobs.db.execute("UPDATE media_processing_job SET lease_until='2000-01-01' WHERE id=:id",{'id':claimed['id']})
        with self.assertRaisesRegex(RuntimeError,'media_job_lease_lost'):process_task(jobs,claimed)
        self.assertFalse(target.exists())
        self.assertEqual(self.records.get(job['job_id'])['state'],'queued')

    def test_revoked_management_does_not_execute_queued_repairs(self):
        ident=self.identify(self.fixture());source,target=self.paths[0];target.unlink()
        self.accounts.update_user(self.admin,self.alice.id,enabled=True,role='user',can_download=False,can_manage_media=True)
        manager=PlatformService(self.accounts.actor_by_id(self.alice.id),self.accounts,self.records)
        plan=manager.collection_mapping_plan(ident)
        manager.collection_mapping_apply(plan['plan_id'],'revoked-mapping-1')
        self.accounts.update_user(self.admin,self.alice.id,enabled=True,role='user',can_download=False,can_manage_media=False)
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            process_task(jobs,claimed)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(),b'original-1')

    def test_repair_resumes_committed_link_without_repeating_file_writes(self):
        ident=self.identify(self.fixture());source,target=self.paths[0];target.unlink()
        preview=self.service.collection_mapping_plan(ident)
        job=self.service.collection_mapping_apply(preview['plan_id'],'recover-mapping-1')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        original=self.records.update
        # Crash after link/database commit but before the task's first result is saved.
        def interrupted(row,state,data=None):
            if data and data.get('results'):raise SystemExit('fixture crash')
            return original(row,state,data)
        with patch('media_mcp.storage.records.Records.update',side_effect=interrupted):
            with self.assertRaises(SystemExit):process_task(jobs,claimed)
        self.assertTrue(os.path.samefile(source,target))
        process_task(jobs,claimed)
        result=self.service.collection_task(job['job_id'])
        self.assertEqual(result['state'],'completed')
        self.assertTrue(result['results'][0]['recovered'])

    def test_valid_mapping_can_refresh_failed_record_without_changing_files(self):
        ident=self.identify(self.fixture())
        source,target=self.paths[0];before=source.stat()
        self.db.execute("UPDATE media_link SET status='failed',fail_stage='subtitle' WHERE source_path=:path",{'path':str(source)})
        plan=self.service.collection_mapping_plan(ident)
        self.assertEqual(sum(op['action']=='refresh_record' for op in plan['operations']),1)
        job=self.service.collection_mapping_apply(plan['plan_id'],'refresh-record-001')
        self.assertEqual(self.work(job)['state'],'completed')
        self.assertEqual(source.stat().st_ino,before.st_ino)
        self.assertTrue(os.path.samefile(source,target))
        self.assertEqual(self.db.execute('SELECT status FROM media_link WHERE source_path=:path',{'path':str(source)}).scalar(),'linked')

    def test_subtitle_engine_zero_media_is_not_reported_as_success(self):
        ident=self.identify(self.fixture())
        agent=Mock();agent._run_path_summary_locked.return_value={'handled':0,'media_count':0,'failed':0}
        job=self.service.collection_subtitles(ident,'empty-subtitle-001',mode='recheck')
        result=self.work(job,agent)
        self.assertEqual(result['state'],'completed_with_warnings')
        self.assertTrue(all(item['state']=='needs_review' for item in result['results']))

    def test_bonus_directories_attach_to_parent_and_do_not_become_movies(self):
        from media_mcp.storage.inventory import Inventory
        ident=self.fixture(1)
        source,target=self.paths[0]
        work=source.parent/'Work';work.mkdir();moved=work/source.name;source.rename(moved)
        self.db.execute('UPDATE media_link SET source_path=:new WHERE source_path=:old',{'new':str(moved),'old':str(source)})
        bonus=work/'Featurettes'/'Deleted Scenes';bonus.mkdir(parents=True)
        (bonus/'Chandler Charters.mkv').write_bytes(b'extra-one')
        (bonus/'Children’s Funeral.mkv').write_bytes(b'extra-two')
        scan=Inventory(self.records).scan(self.admin.id);Inventory(self.records).adopt(scan['scan_id'],self.admin.id)
        page=self.service.collections()
        self.assertEqual(page['total'],1)
        self.assertEqual(page['collections'][0]['summary']['extras'],2)
        self.assertEqual(page['collections'][0]['summary']['files'],3)
        self.assertEqual(self.service.collections(kind='extra')['total'],1)
        with patch.object(self.service.service.tmdb,'get',side_effect=AssertionError('implicit provider')):
            self.service.collections()
        context=self.service._collections().identity_context(ident)
        self.assertEqual(len(context['files']),1)

    def test_standalone_extras_hidden_but_recoverable_and_manual_classification_persists(self):
        from media_mcp.storage.inventory import Inventory
        self.fixture(1)
        path=self.paths[0][0].parent/'Unmatched Movie'/'Extras';path.mkdir(parents=True)
        first=path/'Unknown Clip.mkv';first.write_bytes(b'bonus')
        (path/'Another Clip.mkv').write_bytes(b'bonus-two')
        inv=Inventory(self.records);scan=inv.scan(self.admin.id);inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(self.service.collections()['total'],1)
        extra=self.service.collections(kind='extra')['collections'][0]
        self.assertEqual(extra['summary']['files'],2)
        self.assertEqual(extra['title'],'Unmatched Movie')
        detail=self.service.collection(extra['collection_id'])
        keys=[file['key'] for season in detail['seasons'] for file in season['files']]
        self.service.collection_classify(extra['collection_id'],'main',selection=[keys[0]])
        page=PlatformService(self.admin,self.accounts,self.records).collections()
        self.assertEqual(page['total'],2)
        self.assertEqual(first.read_bytes(),b'bonus')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_inventory').scalar(),4)

    def test_unfamiliar_title_is_not_filtered_and_known_movie_names_are_preserved(self):
        from media_mcp.application.collections import classify
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT'])
        self.assertEqual(classify({'source_path':str(source/'Children’s Funeral.mkv')})['category'],'main')
        self.assertEqual(classify({'source_path':str(source/'Trailer.mkv'),'media_tmdb_id':42,'media_type':'movie'})['category'],'main')
        self.assertEqual(classify({'source_path':str(source/'Show.NCOP01.mkv')})['category'],'extra')
        self.assertEqual(classify({'source_path':str(source/'Special.S00E01.mkv')})['category'],'extra')

    def test_classification_permissions_and_active_task_fence(self):
        ident=self.identify(self.fixture())
        viewer=PlatformService(self.alice,self.accounts,self.records)
        with self.assertRaisesRegex(ValueError,'media_management_permission_required'):
            viewer.collection_classify(ident,'extra')
        self.service.collection_subtitles(ident,'classify-busy-001',mode='recheck')
        with self.assertRaisesRegex(ValueError,'collection_operation_busy'):
            self.service.collection_classify(ident,'extra')

    def test_classification_changes_invalidate_existing_identity_preview(self):
        ident=self.fixture()
        plan=self.service.collection_identify(ident,'tv:123')
        self.service.collection_classify(ident,'extra')
        with self.assertRaisesRegex(ValueError,'collection_changed_rebuild_plan'):
            self.service.collection_identity_apply(plan['plan_id'])

    def test_extras_do_not_enter_normal_mapping_or_subtitle_maintenance(self):
        ident=self.identify(self.fixture(1))
        self.service.collection_classify(ident,'extra')
        self.assertEqual(self.service.collections()['total'],0)
        self.assertEqual(self.service.collections(kind='extra')['total'],1)
        plan=self.service.collection_mapping_plan(ident)
        self.assertEqual(plan['operations'][0]['reason'],'extra_requires_review')
        with self.assertRaisesRegex(ValueError,'collection_no_eligible_subtitles'):
            self.service.collection_subtitles(ident,'skip-extra-001',mode='recheck')

    def test_manual_category_does_not_hide_a_replaced_file(self):
        ident=self.fixture(1)
        self.service.collection_classify(ident,'extra')
        self.assertEqual(self.service.collections()['total'],0)
        self.paths[0][0].write_bytes(b'replaced-with-another-video')
        self.assertEqual(self.service.collections()['total'],1)

    def test_numeric_title_is_not_mistaken_for_release_year(self):
        from media_mcp.application.collections import guess
        file={'target_path':str(Path(os.environ['MEDIA_LIBRARY_ROOT'])/'movie/银翼杀手2049(Blade Runner 2049) - 2017.mkv')}
        result=guess(file)
        self.assertEqual(result['title'],'银翼杀手2049(Blade Runner 2049)')
        self.assertEqual(result['year_hint'],2017)
        first=guess({'source_path':str(Path(os.environ['MEDIA_DOWNLOAD_ROOT'])/'First.S01E01.mkv')})
        second=guess({'source_path':str(Path(os.environ['MEDIA_DOWNLOAD_ROOT'])/'Second.S01E01.mkv')})
        self.assertNotEqual(first['scope'],second['scope'])

    def test_overlapping_jobs_and_identity_changes_wait_for_current_task(self):
        ident=self.identify(self.fixture())
        files=[f for season in self.service.collection(ident)['seasons'] for f in season['files']]
        self.service.collection_subtitles(ident,'overlap-task-one',selection=[files[0]['key']],mode='recheck')
        with self.assertRaisesRegex(ValueError,'collection_operation_busy'):
            self.service.collection_subtitles(ident,'overlap-task-two',selection=[files[0]['key'],files[1]['key']],mode='recheck')
        plan=self.service.collection_identify(ident,'tv:123')
        with self.assertRaisesRegex(ValueError,'collection_operation_busy'):
            self.service.collection_identity_apply(plan['plan_id'])

    def test_changed_source_requires_fresh_identity_before_repair(self):
        ident=self.identify(self.fixture());source,target=self.paths[0];target.unlink();source.write_bytes(b'new-version')
        preview=self.service.collection_mapping_plan(ident)
        first=next(op for op in preview['operations'] if op['source_path']==str(source))
        self.assertEqual(first['action'],'review');self.assertEqual(first['reason'],'source_identity_changed')
        plan=self.service.collection_identify(ident,'tv:123')
        self.service.collection_identity_apply(plan['plan_id'])
        preview=self.service.collection_mapping_plan(ident)
        first=next(op for op in preview['operations'] if op['source_path']==str(source))
        self.assertEqual(first['action'],'create_link')

if __name__=='__main__':unittest.main()
