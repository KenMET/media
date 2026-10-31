"""Season coverage and consent are distinct from individual delivery jobs."""
from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch
import time

import test_platform
from media_mcp.application.releases import coverage, season_scope, select_releases, release_rank
from media_mcp.application.subscriptions import SeasonRequests, INTERVAL
from media_mcp.platform.service import PlatformService
from media_mcp.platform.cloud import CloudRequest
from media_mcp.runtime.subscription_worker import check_season


class CoverageTests(TestCase):
    def test_pack_episode_ranges_wrong_season_and_ambiguous_combined_files(self):
        self.assertEqual(coverage('Show.S01.1080p',1,[1,2]),('season_pack',[1,2]))
        self.assertEqual(coverage('Show.S01E01-E02',1,[1,2]),('season_pack',[1,2]))
        self.assertEqual(coverage('Show.S01E02',1,[1,2]),('episode',[2]))
        self.assertEqual(coverage('Show.S02E02',1,[1,2]),('other_season',[]))
        self.assertEqual(coverage('Show.S01E01E02',1,[1,2]),('unknown',[]))
        self.assertEqual(coverage('Show complete',1,[1,2]),('unknown',[]))

    def test_aired_snapshot_excludes_future_and_refuses_explicit_future(self):
        metadata={'episodes':[{'episode_number':1,'air_date':'2026-01-01'},
                              {'episode_number':2,'air_date':'2026-12-01'}]}
        self.assertEqual(season_scope(metadata,[],date(2026,6,1)),([1],[1,2]))
        with self.assertRaisesRegex(ValueError,'not_aired'):
            season_scope(metadata,[2],date(2026,6,1))

    def test_available_pack_first_then_episode_fallback_and_honest_missing(self):
        singles=[{'release_id':str(n),'coverage_kind':'episode','covered_episodes':[n],'seeders':100} for n in (1,2)]
        pack={'release_id':'pack','coverage_kind':'season_pack','covered_episodes':[1,2],'seeders':1}
        self.assertEqual(select_releases(singles+[pack],[1,2]),([(pack,[1,2])],[]))
        selected,missing=select_releases(singles+[dict(pack,seeders=0)],[1,2,3])
        self.assertEqual([r['release_id'] for r,_ in selected],['1','2'])
        self.assertEqual(missing,[3])


    def test_explicit_subset_prefers_single_and_overlapping_packs_get_disjoint_scopes(self):
        single={'coverage_kind':'episode','covered_episodes':[1],'seeders':1}
        pack={'coverage_kind':'season_pack','covered_episodes':[1,2],'seeders':1}
        self.assertEqual(sorted([pack,single],key=lambda r:release_rank(r,explicit=True)),[single,pack])
        first={'coverage_kind':'partial_pack','covered_episodes':[1,2],'seeders':10}
        second={'coverage_kind':'partial_pack','covered_episodes':[2,3],'seeders':1}
        self.assertEqual(select_releases([second,first],[1,2,3]),([(first,[1,2]),(second,[3])],[]))


class SeasonRequestTests(TestCase):
    setUp=test_platform.PlatformTests.setUp

    def service(self):
        tmdb,indexer=Mock(),Mock()
        tmdb.detail.return_value={'title_id':'tv:1','kind':'tv','tmdb_id':1,'title':'Show','original_title':'Show'}
        tmdb.get.return_value={'episodes':[{'episode_number':n,'name':str(n),'air_date':'2020-01-01'} for n in (1,2)]}
        indexer.search.return_value={'releases':[{'name':f'Show S01E{n:02d} 1080p', 'resolution':1080,
            'seeders':2,'download_url':'magnet:?xt=urn:btih:'+str(n)*40,'claimed_infohash':str(n)*40} for n in (1,2)],
            'diagnostics':[{'site':'test','status':'ok','raw_count':2}]}
        indexer.torrent.side_effect=lambda url:url
        return PlatformService(self.admin,self.accounts,self.records,tmdb=tmdb,indexer=indexer)

    def test_ordinary_download_is_one_shot_idempotent_disjoint_and_scope_frozen(self):
        service=self.service();seasons=SeasonRequests(service)
        claim=seasons.create('tv:1',1,1080,'one-shot-123')
        def call(payload):
            if payload.get('request'):
                payload={**payload,'request':CloudRequest.model_validate(payload['request'])}
            return seasons.execute(**payload)
        first=check_season(claim,call,self.db,service.service.tmdb,service.service.indexer)
        self.assertEqual(len(first['job_ids']),2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='season_subscription'").scalar(),0)
        resumed=seasons.create('tv:1',1,1080,'one-shot-123')
        self.assertEqual(check_season(resumed,call,self.db,service.service.tmdb,service.service.indexer),first)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='acquisition'").scalar(),2)
        scopes=[self.records.get(ident)['data']['scope']['episodes'] for ident in first['job_ids']]
        self.assertEqual(scopes,[[1],[2]])

    def test_subscription_requires_explicit_consent_dedupes_and_retains_deadline(self):
        seasons=SeasonRequests(self.service())
        created=seasons.create('tv:1',1,1080,'subscription-123',subscribe=True)
        self.assertEqual(seasons.create('tv:1',1,1080,'another-key-123',subscribe=True)['request_id'],created['request_id'])
        now=time.time()
        claims=SeasonRequests.due(self.accounts,self.records,now)
        self.assertEqual(len(claims),1)
        self.assertEqual(claims[0]['next_check_at'],now+INTERVAL)
        self.assertEqual(SeasonRequests.due(self.accounts,self.records,now+INTERVAL-1),[])
        row=self.records.get(created['request_id'])
        paused=seasons.change(row['id'],row['revision'],'paused')
        with self.assertRaisesRegex(ValueError,'not_active'):
            seasons.execute(row['id'],claims[0]['run_key'],episodes=[1])
        self.assertEqual(SeasonRequests.due(self.accounts,self.records,now+INTERVAL),[])
        seasons.change(paused['request_id'],paused['revision'],'active')
        self.assertEqual(len(SeasonRequests.due(self.accounts,self.records,now+INTERVAL)),1)

    def test_owner_and_scope_checks_fail_closed(self):
        service=self.service();seasons=SeasonRequests(service)
        created=seasons.create('tv:1',1,1080,'subscription-123',subscribe=True)
        other=SeasonRequests(PlatformService(self.alice,self.accounts,self.records))
        with self.assertRaisesRegex(ValueError,'not_found'):
            other.change(created['request_id'],created['revision'],'cancelled')

    def test_twelve_episode_fallback_uses_one_account_request_and_one_submission_charge(self):
        service=self.service();seasons=SeasonRequests(service)
        service.service.tmdb.get.return_value={'episodes':[{'episode_number':n,'air_date':'2020-01-01'} for n in range(1,13)]}
        service.service.indexer.search.return_value={'releases':[{'name':f'Show S01E{n:02d}', 'resolution':1080,
            'seeders':2,'download_url':'magnet:?xt=urn:btih:'+f'{n:040x}','claimed_infohash':f'{n:040x}'} for n in range(1,13)],
            'diagnostics':[{'site':'test','status':'ok','raw_count':12}]}
        claim=seasons.create('tv:1',1,1080,'twelve-episodes-123')
        def call(payload):
            if payload.get('request'):payload={**payload,'request':CloudRequest.model_validate(payload['request'])}
            return seasons.execute(**payload)
        result=check_season(claim,call,self.db,service.service.tmdb,service.service.indexer)
        self.assertEqual(len(result['job_ids']),12)
        self.assertEqual(self.db.execute("SELECT COUNT(DISTINCT json_extract(data,'$.season_request_id')) FROM media_mcp_record WHERE kind='acquisition'").scalar(),1)

    def test_revoked_download_permission_pauses_due_subscription(self):
        seasons=SeasonRequests(PlatformService(self.alice,self.accounts,self.records))
        row=seasons.create('tv:1',1,1080,'alice-subscription-123',subscribe=True)
        self.accounts.update_user(self.admin,self.alice.id,enabled=True,role='user',can_download=False)
        self.assertEqual(SeasonRequests.due(self.accounts,self.records),[])
        saved=self.records.get(row['request_id'])
        self.assertEqual(saved['state'],'paused')
        self.assertEqual(saved['data']['error_code'],'download_permission_required')

    def test_unannounced_future_dates_do_not_block_known_aired_episodes(self):
        service=self.service();seasons=SeasonRequests(service)
        service.service.tmdb.get.return_value={'episodes':[{'episode_number':1,'air_date':'2020-01-01'},
            {'episode_number':2,'air_date':None}]}
        claim=seasons.create('tv:1',1,1080,'unknown-future-dates')
        def call(payload):
            if payload.get('request'):payload={**payload,'request':CloudRequest.model_validate(payload['request'])}
            return seasons.execute(**payload)
        result=check_season(claim,call,self.db,service.service.tmdb,service.service.indexer)
        self.assertEqual(result['expected_episodes'],[1]);self.assertEqual(result['air_dates_unknown'],[2])
        self.assertEqual(len(result['job_ids']),1)
