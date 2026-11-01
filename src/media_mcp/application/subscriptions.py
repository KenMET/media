"""Explicit season consent and durable six-hour checks; NAS remains authoritative."""
import hashlib
import time
import uuid

from media_mcp.config import parse_title_id
from media_mcp.runtime.state import media_mutation_lock
from media_mcp.platform.limits import Budget

INTERVAL = 21600


class SeasonRequests:
    def __init__(self, service):
        self.service = service
        self.records = service.records

    @staticmethod
    def public(row):
        data = row['data']
        return {'request_id':row['id'], 'revision':row['revision'], 'state':row['state'],
                **{k:data.get(k) for k in ('title_id','season','resolution','next_check_at','last_result','error_code')}}

    def owned(self, ident):
        row = self.records.get(ident)
        if row['kind'] not in ('season_request','season_subscription') or row['data']['owner'] != self.service.actor.id:
            raise ValueError('record_not_found')
        return row

    def create(self, title_id, season, resolution, idempotency_key, *, subscribe=False):
        self.service._download_permission()
        if parse_title_id(title_id)[0] != 'tv':
            raise ValueError('tv_season_required')
        config = {'title_id':title_id,'season':season,'resolution':resolution or 1080}
        kind = 'season_subscription' if subscribe else 'season_request'
        key = hashlib.sha256((kind+':'+self.service._key(idempotency_key)).encode()).hexdigest()
        with media_mutation_lock(self.records.db):
            previous = self.records.by_key(key)
            if previous:
                if any(previous['data'][k] != v for k,v in config.items()):
                    raise ValueError('idempotency_key_reused_with_different_request')
                return self.claim_data(previous) if not subscribe else self.public(previous)
            if subscribe:
                existing=self.records.db.execute("""SELECT * FROM media_mcp_record WHERE kind='season_subscription' AND state!='cancelled'
                    AND json_extract(data,'$.owner')=:owner AND json_extract(data,'$.title_id')=:title
                    AND json_extract(data,'$.season')=:season LIMIT 1""",{'owner':self.service.actor.id,'title':title_id,'season':season}).mappings().first()
                if existing:
                    existing=self.records.decode(existing)
                    if existing['data']['resolution']!=config['resolution']:
                        raise ValueError('subscription_configuration_conflict')
                    return self.public(existing)
                count = self.records.db.execute("""SELECT COUNT(*) FROM media_mcp_record WHERE kind='season_subscription'
                    AND state!='cancelled' AND json_extract(data,'$.owner')=:owner""",{'owner':self.service.actor.id}).scalar()
                if count >= 100:
                    raise ValueError('subscription_limit_reached')
            Budget(self.records.db,self.service.accounts.clock).charge(self.service.actor.id,'search' if subscribe else 'plan')
            row = self.records.put(kind,{**config,'owner':self.service.actor.id,'next_check_at':0,
                'run_key':uuid.uuid4().hex,'plan_paid':not subscribe,'expires_at':time.time()+1800 if not subscribe else None},'active',key)
        return self.public(row) if subscribe else self.claim_data(row)

    def list(self):
        rows = self.records.db.execute("""SELECT * FROM media_mcp_record WHERE kind='season_subscription'
            AND json_extract(data,'$.owner')=:owner ORDER BY created_at DESC,id""",{'owner':self.service.actor.id}).mappings()
        return {'subscriptions':[self.public(self.records.decode(row)) for row in rows]}

    def change(self, request_id, revision, state):
        with self.records.db.lock('season-consent:'+request_id,timeout=5), media_mutation_lock(self.records.db):
            row = self.owned(request_id)
            if row['kind'] != 'season_subscription' or row['revision'] != revision or row['state']=='cancelled':
                raise ValueError('stale_subscription_revision')
            if state == 'active':
                self.service._download_permission()
            row = self.records.update(row,state,{**row['data'],'run_key':uuid.uuid4().hex,'next_check_at':0,'plan_paid':False})
        return self.public(row)

    @staticmethod
    def claim_data(row):
        data=row['data']
        return {**SeasonRequests.public(row),'owner':data['owner'],'run_key':data['run_key'],
                'one_time':row['kind']=='season_request','requested_episodes':data.get('requested_episodes')}

    @classmethod
    def due(cls, accounts, records, now=None):
        now = time.time() if now is None else now
        claims=[]
        with records.db.lock('season-subscriptions',timeout=1):
            rows=records.db.execute("""SELECT * FROM media_mcp_record WHERE kind='season_subscription' AND state='active'
                AND COALESCE(json_extract(data,'$.next_check_at'),0)<=:now ORDER BY updated_at,id LIMIT 5""",{'now':now}).mappings().all()
            for raw in rows:
                row=records.decode(raw)
                try:
                    actor=accounts.actor_by_id(row['data']['owner'])
                    if not actor.can_download:
                        raise ValueError('download_permission_required')
                except ValueError:
                    records.update(row,'paused',{**row['data'],'error_code':'download_permission_required'})
                    continue
                try:
                    Budget(records.db,accounts.clock).charge(actor.id,'plan')
                except ValueError:
                    records.update(row,'active',{**row['data'],'next_check_at':now+INTERVAL,'error_code':'account_rate_limited'})
                    continue
                row=records.update(row,'active',{**row['data'],'run_key':uuid.uuid4().hex,
                    'next_check_at':now+INTERVAL,'error_code':None,'plan_paid':True,'requested_episodes':None})
                claims.append(cls.claim_data(row))
        return claims

    def execute(self, request_id, run_key, request=None, result=None, episodes=None):
        from media_mcp.platform.cloud import accept_cloud, decode_payload
        from media_mcp.adapters.torrent import infohash
        with media_mutation_lock(self.records.db):
            if sum(value is not None for value in (request,result,episodes))!=1:
                raise ValueError('invalid_request')
            row=self.owned(request_id)
            data=row['data']
            self.service._download_permission()
            if row['state']!='active' or not data.get('plan_paid') or data['run_key']!=run_key or (data.get('expires_at') and data.get('requested_episodes') is None and time.time()>=data['expires_at']):
                raise ValueError('season_request_not_active')
            if episodes is not None:
                frozen=data.get('requested_episodes')
                if frozen is not None and frozen!=episodes:
                    raise ValueError('season_scope_changed')
                row=self.records.update(row,row['state'],{**data,'requested_episodes':episodes})
                return self.public(row)
            if result is not None:
                row=self.records.update(row,row['state'],{**data,'last_result':result,'result_run_key':run_key,'error_code':result.get('error_code')})
                return self.public(row)
            if request is None or request.action!='plan' or request.snapshot is None or request.payload is None:
                raise ValueError('invalid_request')
            snapshot=request.snapshot
            if (snapshot.identity.title_id!=data['title_id'] or snapshot.scope.season!=data['season'] or
                    snapshot.scope.resolution!=data['resolution'] or not snapshot.scope.allow_upgrade or
                    snapshot.release.coverage_kind not in ('season_pack','partial_pack','episode') or
                    not set(snapshot.scope.episodes).issubset(snapshot.release.covered_episodes) or
                    not set(snapshot.scope.episodes).issubset(data.get('requested_episodes') or [])):
                raise ValueError('subscription_scope_mismatch')
            torrent,magnet=decode_payload(request.payload.model_dump(),snapshot.release.claimed_infohash)
            hash_value=infohash(torrent,magnet)
            key=f"season:{request_id}:{hash_value}"
            record_key=hashlib.sha256(('acquire:'+self.service._key(key)).encode()).hexdigest()
        # Existing plan/start acquire the mutation lock and recheck active scope themselves.
        # Serialize pause/cancel with final authorization and creation using a consent lock.
        with self.records.db.lock('season-consent:'+request_id,timeout=5):
            current=self.owned(request_id)
            if current['state']!='active' or current['data']['run_key']!=run_key:
                raise ValueError('season_request_not_active')
            actor=self.service.accounts.actor_by_id(data['owner'])
            if not actor.can_download:raise ValueError('download_permission_required')
            previous=self.records.by_key(record_key)
            if previous:
                if not set(snapshot.scope.episodes).issubset(previous['data']['scope']['episodes']):
                    raise ValueError('subscription_existing_payload_requires_review')
                return self.service.job(previous['id'])
            plan=accept_cloud(request,self.service,season_id=request_id)
            frozen=self.service.service.records.get(plan['plan_id'],'plan')
            self.service.service.records.update(frozen,frozen['state'],{**frozen['data'],'season_request_id':request_id,'season_infohash':hash_value,'season_run_key':run_key})
            plan['revision']+=1
            return self.service.start(plan['plan_id'],plan['revision'],key)
