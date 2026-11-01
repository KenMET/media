"""Media summaries use completed rounds, unique identities and durable send fences."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
import test_platform
from media_mcp.runtime.media_notifications import deliver,reconcile,digest,notify_path
from media_mcp.runtime.state import MediaJobs
from media_mcp.storage.media import upsert_media_link,upsert_media_subtitle
from media_mcp.ingest.domain.classifier import validate_result


class MediaNotificationTests(TestCase):
    def setUp(self):
        test_platform.PlatformTests.setUp(self)
        self.jobs=MediaJobs();self.jobs.initialize()
        reconcile(self.records)
        policy=self.records.by_key(digest(['media-notification-policy',1]))
        self.records.update(policy,'enabled',{'enabled_at':'2000-01-01 00:00:00'})
        self.sender=Mock(return_value=True)

    def video(self,episode=1,season=3,kind='tv',subtitle=True,embedded=False):
        root=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);library=Path(os.environ['MEDIA_LIBRARY_ROOT'])
        root.mkdir(exist_ok=True);library.mkdir(exist_ok=True)
        stem=f'{kind}-{season}-{episode}'
        source=root/(stem+'.mkv');source.write_bytes(b'Original video')
        target=library/source.name;os.link(source,target)
        metadata={'media_type':kind,'media_tmdb_id':1,'media_name':'Example','season':season if kind=='tv' else None,
            'episode':episode if kind=='tv' else None}
        upsert_media_link(None,str(source),str(target),**metadata,status='linked')
        if subtitle:
            if embedded:
                src=str(source)+'#stream:2';dst=str(target)+'#stream:2'
            else:
                src=str(source.with_suffix('.srt'));dst=str(target.with_suffix('.srt'))
                Path(src).write_text('Verified subtitle');os.link(src,dst)
            upsert_media_subtitle(None,src,dst,**metadata,matched_video_source_path=str(source),matched_video_target_path=str(target),
                status='exists',source_type='embedded' if embedded else 'sidecar',stream_index=2 if embedded else None)
        return str(source),str(target)

    def acquisition(self,episodes,state='completed',season=3,kind='tv',parent=None,run=None):
        return self.records.put('acquisition',{'identity':{'kind':kind,'tmdb_id':1,'title_id':kind+':1','title':'Example'},
            'scope':{'season':season if kind=='tv' else None,'episodes':episodes if kind=='tv' else []},
            **({'season_request_id':parent,'season_run_key':run} if parent else {})},state)

    def test_fourteen_episodes_one_summary_after_both_phases_not_each_retry(self):
        for episode in range(1,15):self.video(episode,embedded=True)
        row=self.acquisition(list(range(1,15)),state='processing')
        for _ in range(4):deliver(self.records,self.sender)
        self.sender.assert_not_called()
        self.records.update(row,'completed')
        deliver(self.records,self.sender);deliver(self.records,self.sender)
        self.sender.assert_called_once()
        content=self.sender.call_args.args[1]
        self.assertIn('S03',content);self.assertIn('Library videos: 14/14',content);self.assertIn('Subtitles ready: 14/14',content)
        self.assertNotIn('Needs attention',content)

    def test_episode_fallback_waits_for_parent_plan_and_all_children(self):
        for n in (1,2):self.video(n)
        parent=self.records.put('season_request',{'run_key':'run','owner':self.admin.id},'active')
        self.acquisition([1],parent=parent['id'],run='run')
        second=self.acquisition([2],state='processing',parent=parent['id'],run='run')
        deliver(self.records,self.sender);self.sender.assert_not_called()
        self.records.update(parent,'active',{**parent['data'],'result_run_key':'run'})
        deliver(self.records,self.sender);self.sender.assert_not_called()
        self.records.update(second,'completed');deliver(self.records,self.sender)
        self.sender.assert_called_once();self.assertIn('2/2',self.sender.call_args.args[1])

    def test_movie_one_notice_missing_subtitles_visible_and_unknown_delivery_not_replayed(self):
        self.video(kind='movie',subtitle=False);self.acquisition([],kind='movie')
        self.sender.return_value=False
        deliver(self.records,self.sender);deliver(self.records,self.sender)
        self.sender.assert_called_once()
        self.assertIn('Movie Example',self.sender.call_args.args[1]);self.assertIn('Subtitles ready: 0/1',self.sender.call_args.args[1])
        self.assertEqual(self.records.list('media_notice')[0]['state'],'delivery_unknown')

    def test_crash_after_claim_is_fenced_without_another_push(self):
        self.video();self.acquisition([1]);reconcile(self.records)
        notice=self.records.list('media_notice')[0];self.records.update(notice,'sending')
        deliver(self.records,self.sender);self.sender.assert_not_called()
        self.assertEqual(self.records.get(notice['id'])['state'],'delivery_unknown')

    def test_historical_completed_tasks_do_not_generate_backfill_pushes(self):
        self.video();row=self.acquisition([1])
        self.db.execute("UPDATE media_mcp_record SET updated_at='1999-01-01' WHERE id=:id",{'id':row['id']})
        deliver(self.records,self.sender);self.sender.assert_not_called()

    def test_direct_multi_season_and_movie_paths_are_grouped(self):
        self.video(1,season=1);self.video(2,season=1);self.video(1,season=2);self.video(kind='movie')
        notify_path(os.environ['MEDIA_DOWNLOAD_ROOT'],sender=self.sender)
        self.assertEqual(self.sender.call_count,3)
        bodies=[call.args[1] for call in self.sender.call_args_list]
        self.assertTrue(any('S01' in body and '2/2' in body for body in bodies))
        self.assertTrue(any('S02' in body and '1/1' in body for body in bodies))
        self.assertTrue(any('Movie' in body and '1/1' in body for body in bodies))

    def test_currently_active_owned_child_blocks_premature_summary(self):
        self.video();row=self.acquisition([1])
        self.jobs.enqueue('owned-delivery',os.environ['MEDIA_DOWNLOAD_ROOT'])
        delivery=self.db.execute('SELECT delivery_key FROM media_processing_job').scalar()
        self.records.update(row,'completed',{**row['data'],'delivery_hash':delivery})
        deliver(self.records,self.sender);self.sender.assert_not_called()

    def test_retained_hardlink_is_noop_and_does_not_requeue_completed_subtitles(self):
        from media_mcp.ingest.run import restore_link_from_db
        source,target=self.video()
        row=dict(self.db.execute('SELECT * FROM media_link WHERE source_path=:source',{'source':source}).mappings().one())
        with patch('media_mcp.ingest.run.logger',return_value=Mock()), \
             patch('media_mcp.ingest.run.get_media_link_by_source',return_value=row), \
             patch('media_mcp.ingest.run.validate_canonical_hardlink_path',return_value=(True,'ok',target)), \
             patch('media_mcp.ingest.services.linking.apply_preferred_media',return_value=(True,'Existing preferred hardlink retained',target)):
            self.assertEqual(restore_link_from_db(source),(True,'exists'))
        self.jobs.enqueue('retained',str(Path(source).parent))
        first=self.jobs.claim('ingest')
        self.jobs.finish(first,error='ingest_incomplete',result='{"created":0,"relinked":0,"existed":1,"failed":13}')
        subtitle=self.jobs.claim('subtitle');self.jobs.finish(subtitle)
        self.db.execute("UPDATE media_processing_job SET next_attempt_at=CURRENT_TIMESTAMP WHERE stage='ingest'")
        retry=self.jobs.claim('ingest');self.assertEqual(retry['attempts'],2)
        self.jobs.finish(retry,error='ingest_incomplete',result='{"created":0,"relinked":0,"existed":1,"failed":13}')
        self.assertEqual(self.db.execute("SELECT state FROM media_processing_job WHERE stage='subtitle'").scalar(),'succeeded')

    def test_old_completed_sibling_still_counts_in_newly_completed_parent_round(self):
        self.video(1);self.video(2)
        parent=self.records.put('season_request',{'run_key':'run','result_run_key':'run'},'active')
        old=self.acquisition([1],parent=parent['id'],run='run')
        self.db.execute("UPDATE media_mcp_record SET updated_at='1999-01-01' WHERE id=:id",{'id':old['id']})
        self.acquisition([2],parent=parent['id'],run='run')
        deliver(self.records,self.sender)
        self.sender.assert_called_once();self.assertIn('2/2',self.sender.call_args.args[1])

    def test_explicit_processing_retry_starts_a_new_notice_round_without_new_download(self):
        self.video();row=self.acquisition([1],state='needs_review')
        deliver(self.records,self.sender)
        retried=self.records.update(row,'processing',{**row['data'],'notification_round':1})
        deliver(self.records,self.sender);self.assertEqual(self.sender.call_count,1)
        self.records.update(retried,'completed');deliver(self.records,self.sender)
        self.assertEqual(self.sender.call_count,2)

    def test_unidentified_batch_keeps_one_actionable_fallback(self):
        notify_path(os.environ['MEDIA_DOWNLOAD_ROOT'],media_links=[],unresolved=2,sender=self.sender)
        self.sender.assert_called_once()
        self.assertIn('Unidentified media',self.sender.call_args.args[1])
        self.assertIn('Needs attention: 2',self.sender.call_args.args[1])

    def test_supervised_workers_disable_low_level_ingest_and_subtitle_pushes(self):
        from media_mcp.runtime.worker import run_worker
        source,_=self.video()
        for stage in ('ingest','subtitle'):
            jobs=Mock();jobs.db=self.db;jobs.claim.side_effect=[{'id':999,'delivery_key':'fixture','path':source},KeyboardInterrupt]
            agent=Mock();agent.run_path_summary.return_value={'handled':1,'missing':0,'review':0,'failed':0}
            with patch('media_mcp.runtime.worker.MediaJobs',return_value=jobs), \
                 patch('media_mcp.runtime.worker.heartbeat'), \
                 patch('media_mcp.logging_utils.init'),patch('media_mcp.logging_utils.get',return_value=Mock()), \
                 patch('media_mcp.ingest.run.set_logger'), \
                 patch('media_mcp.ingest.services.triage_agent.CodexMediaTriageAgent'), \
                 patch('media_mcp.ingest.run.full_scan_triage',return_value=(1,0,0,0)) as triage, \
                 patch('media_mcp.subtitle.services.subtitle_agent.SubtitleAgent',return_value=agent):
                with self.assertRaises(KeyboardInterrupt):run_worker(stage)
            self.assertFalse((triage if stage=='ingest' else agent.run_path_summary).call_args.kwargs['send_notify'])
            jobs.finish.assert_called_once()


class SeasonPackValidationTests(TestCase):
    def test_filename_episode_wins_over_pack_directory_and_mismatch_still_fails(self):
        for episode in range(1,15):
            result={'success':True,'kind':'tv','season':3,'episode':episode,
                'source_path':f'/downloads/Show.S03E01-E14/Show.S03E{episode:02d}.mkv',
                'hardlink_path':f'/library/Show/Season03/Show.S03E{episode:02d}.mkv'}
            self.assertEqual(validate_result(result),(True,'ok'))
            wrong={**result,'hardlink_path':'/library/Show/Show.S03E99.mkv'}
            self.assertFalse(validate_result(wrong)[0])

    def test_valid_single_episode_parent_evidence_is_retained(self):
        result={'success':True,'kind':'tv','season':3,'episode':2,
            'source_path':'/downloads/Show.S03E01/video.mkv','hardlink_path':'/library/Show.S03E02.mkv'}
        self.assertFalse(validate_result(result)[0])
