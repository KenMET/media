"""Object authorization around the existing application, not a second downloader."""
import hashlib
import re

from media_mcp.application.acquire import MediaService
from media_mcp.storage.records import Records
from media_mcp.platform.limits import Budget, limited


class ScopedRecords(Records):
    def __init__(self, records, actor, accounts, entry):
        super().__init__(records.db)
        self.actor, self.accounts, self.entry = actor, accounts, entry

    def put(self, kind, data, *args, **kwargs):
        data = {**data, '_platform_owner':self.actor.id, '_platform_entry':self.entry}
        if kind == 'acquisition':
            group=data.get('season_request_id')
            if group:
                consent=Records(self.db).get(group)
                if consent['kind'] not in ('season_request','season_subscription') or consent['state']!='active' or consent['data']['owner']!=self.actor.id:
                    raise ValueError('season_request_not_active')
            Budget(self.db,self.accounts.clock).admit_job(self.actor.id,group=group)
        return super().put(kind, data, *args, **kwargs)

    def get(self, ident, kind=None):
        row = super().get(ident, kind)
        if (not self.actor.admin and row['data'].get('_platform_owner') != self.actor.id
                and not (row['kind'] == 'acquisition' and self.accounts.allowed(
                    self.actor, 'task', ident, manage=True))):
            raise ValueError('record_not_found')
        return row


class PlatformService:
    def __init__(self, actor, accounts, records, *, tmdb=None, indexer=None, entry='web'):
        self.actor, self.accounts, self.records = actor, accounts, records
        self.service = MediaService(ScopedRecords(records, actor, accounts, entry), tmdb, indexer)

    def _key(self, key):
        if not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise ValueError('idempotency_key_length_8_to_128')
        return hashlib.sha256((self.actor.id+':'+key).encode()).hexdigest()

    def _download_permission(self):
        if not self.actor.can_download:
            raise ValueError('download_permission_required')

    def _task(self, job_id, manage=False):
        row = self.records.get(job_id, 'acquisition')
        if (not self.actor.admin and row['data'].get('_platform_owner') != self.actor.id
                and not self.accounts.allowed(self.actor, 'task', job_id, manage=manage)):
            raise ValueError('record_not_found')
        return row

    @limited('search')
    def search_titles(self, query, kind='all', year=None):
        return self.service.search_titles(query, kind, year)

    @limited('search')
    def search_releases(self, title_id, season=None, episodes=None, resolution=None):
        self._download_permission()
        return self.service.search_releases(title_id, season, episodes, resolution)

    @limited('plan')
    def plan(self, release_id):
        self._download_permission()
        return self.service.plan(release_id)

    def plan_for_season(self,release_id,request_id):
        from media_mcp.application.subscriptions import SeasonRequests
        self._download_permission()
        consent=SeasonRequests(self).owned(request_id)
        data=consent['data']
        release=self.service.records.get(release_id,'release')['data']
        if (consent['state']!='active' or not data.get('plan_paid') or
                release['identity']['title_id']!=data['title_id'] or release['scope']['season']!=data['season'] or
                release['scope']['resolution']!=data['resolution'] or
                not set(release['scope']['episodes']).issubset(data.get('requested_episodes') or [])):
            raise ValueError('subscription_scope_mismatch')
        return self.service.plan(release_id)

    def start(self, plan_id, revision, idempotency_key):
        self._download_permission()
        # All ownership is persisted in the acquisition record before worker visibility.
        result = self.service.start(plan_id, revision, self._key(idempotency_key))
        self.accounts.event(self.actor, 'download_requested', 'task', result['job_id'])
        return result

    def duplicates(self):
        from media_mcp.application.duplicates import Duplicates
        return Duplicates(self).list()

    def duplicate_preview(self, keep_id):
        from media_mcp.application.duplicates import Duplicates
        return Duplicates(self).preview(keep_id)

    def duplicate_apply(self, plan_id, confirm):
        from media_mcp.application.duplicates import Duplicates
        return Duplicates(self).apply(plan_id,confirm)

    def season_request(self, title_id, season, resolution, idempotency_key):
        from media_mcp.application.subscriptions import SeasonRequests
        return SeasonRequests(self).create(title_id,season,resolution,idempotency_key)

    def season_acquire(self, title_id, season, resolution, idempotency_key):
        from media_mcp.application.subscriptions import SeasonRequests
        from media_mcp.runtime.subscription_worker import check_season
        from media_mcp.platform.cloud import CloudRequest
        claim=self.season_request(title_id,season,resolution,idempotency_key)
        def call(payload):
            request=payload.get('request')
            if request:payload={**payload,'request':CloudRequest.model_validate(request)}
            return SeasonRequests(self).execute(**payload)
        return check_season(claim,call,self.records.db,self.service.tmdb,self.service.indexer)

    def subscription_create(self, title_id, season, resolution, idempotency_key):
        from media_mcp.application.subscriptions import SeasonRequests
        return SeasonRequests(self).create(title_id,season,resolution,idempotency_key,subscribe=True)

    def subscriptions(self):
        from media_mcp.application.subscriptions import SeasonRequests
        return SeasonRequests(self).list()

    def subscription_change(self, request_id, revision, state):
        from media_mcp.application.subscriptions import SeasonRequests
        return SeasonRequests(self).change(request_id,revision,state)

    def job(self, job_id):
        row = self._task(job_id)
        result = self.service.public_job(row)
        result['can_delete']=(self.actor.can_download and row['state']!='deleted' and
            (self.actor.admin or row['data'].get('_platform_owner')==self.actor.id or
             self.accounts.allowed(self.actor,'task',job_id,manage=True)))
        result.update(owner_id=row['data'].get('_platform_owner'),
                      entry=row['data'].get('_platform_entry', 'legacy'),
                      created_at=str(row.get('created_at', '')), updated_at=str(row.get('updated_at', '')))
        return result

    def jobs(self, after='', limit=30):
        if after and not re.fullmatch(r'[a-f0-9]{32}', after):
            raise ValueError('invalid_cursor')
        limit = min(max(int(limit), 1), 100)
        cursor=self._task(after) if after else None
        terminal=('completed','completed_with_warnings','failed','cancelled')
        after_ended=int(cursor['state'] in terminal) if cursor else 0
        rows = self.records.db.execute('''WITH visible AS (
            SELECT r.id,r.created_at,CASE WHEN r.state IN
                ('completed','completed_with_warnings','failed','cancelled') THEN 1 ELSE 0 END AS ended
            FROM media_mcp_record r WHERE r.kind='acquisition' AND r.state!='deleted' AND
            (:admin=1 OR json_extract(r.data,'$._platform_owner')=:user OR EXISTS
                (SELECT 1 FROM platform_access a WHERE a.kind='task' AND a.object_id=r.id AND a.user_id=:user)))
            SELECT id FROM visible WHERE :after='' OR ended>:ended OR (ended=:ended AND (
                created_at<(SELECT created_at FROM media_mcp_record WHERE id=:after) OR
                (created_at=(SELECT created_at FROM media_mcp_record WHERE id=:after) AND id<:after)))
            ORDER BY ended,created_at DESC,id DESC LIMIT :limit''',
            {'after':after,'ended':after_ended,'admin':int(self.actor.admin),'user':self.actor.id,'limit':limit}).mappings().all()
        return {'jobs':[self.job(row['id']) for row in rows],
                'next_cursor':rows[-1]['id'] if len(rows) == limit else None}

    def retry(self, job_id, revision):
        self._download_permission()
        self._task(job_id, manage=True)
        result = self.service.retry(job_id, revision)
        self.accounts.event(self.actor, 'processing_retry', 'task', job_id)
        return result

    def _media_allowed(self, item, manage=False):
        if manage:
            # Per-item legacy access must never bypass the account's feature switch.
            return self.actor.can_manage_media
        if self.accounts.allowed(self.actor, 'media', item['id'], manage=manage):
            return True
        # Derived ownership follows the exact recorded source tree, not merely a matching title.
        row = self.records.db.execute('''SELECT id FROM media_mcp_record
            WHERE kind='acquisition' AND json_extract(data,'$._platform_owner')=:user
            AND (json_extract(data,'$.source_path')=:source OR
                substr(:source,1,length(json_extract(data,'$.source_path'))+1)=
                json_extract(data,'$.source_path')||'/') LIMIT 1''',
            {'user':self.actor.id, 'source':item['source_path']}).first()
        return bool(row)

    def library(self, title_id):
        # The application keeps the complete view for global duplicate/conflict checks.
        result = self.service.library(title_id)
        allowed = []
        for item in result['media']:
            full = self.records.db.execute('SELECT * FROM media_link WHERE id=:id',
                                           {'id':item['id']}).mappings().one()
            if self._media_allowed(full):
                allowed.append({**{k:v for k,v in item.items() if self.actor.admin or k != 'target_path'},
                                'subtitles':self._subtitle_records(full)})
        active = []
        for job in result['active_jobs']:
            try:
                active.append(self.job(job['job_id']))
            except ValueError:
                pass
        return {**result, 'media':allowed, 'active_jobs':active}

    def media(self, after=0, limit=30):
        # Scan a bounded batch and return a scan cursor, including when all entries are filtered.
        limit = min(max(int(limit), 1), 100)
        rows = self.records.db.execute('SELECT * FROM media_link WHERE id>:after ORDER BY id LIMIT :limit',
            {'after':int(after), 'limit':limit}).mappings().all()
        fields = ('id','media_type','media_tmdb_id','media_name','season','episode','status','reason')
        return {'media':[{**{key:row.get(key) for key in fields},'subtitles':self._subtitle_records(row)}
                         for row in rows if self._media_allowed(row)],
                'next_cursor':rows[-1]['id'] if len(rows) == limit else None}

    def _inventory(self):
        if not self.actor.admin:
            raise ValueError('permission_denied')
        from media_mcp.storage.inventory import Inventory
        return Inventory(self.records)

    def _collections(self):
        from media_mcp.application.collections import Collections
        return Collections(self)

    def collections(self,after='',limit=24,query='',kind='all'):
        return self._collections().list(after,limit,query,kind)

    def collection(self,collection_id):
        return self._collections().detail(collection_id)

    def collection_identify(self,collection_id,title_id,selection=None,season=None,season_override=None,assignments=None):
        from media_mcp.application.collections import prepare_identity
        from media_mcp.platform.api import LibraryIdentitySnapshot
        library=self._collections()
        context=library.identity_context(collection_id,selection,season)
        snapshot=prepare_identity(self.service.tmdb,context,title_id,season_override,assignments)
        return library.identity_preview(context['context_id'],LibraryIdentitySnapshot.model_validate(snapshot).model_dump())

    def library_auto(self,idempotency_key,collection_id=None,scope='pending'):
        from media_mcp.application.library_auto import LibraryAuto
        return LibraryAuto(self._collections()).queue(idempotency_key,collection_id,scope)

    def _analysis(self):
        from media_mcp.application.library_analysis import LibraryAnalysis
        return LibraryAnalysis(self._collections())

    def collection_analyze(self,collection_id,idempotency_key,selection=None,season=None,folder=False):
        return self._analysis().queue(collection_id,idempotency_key,selection,season,folder)

    def collection_analysis_plan(self,plan_id):
        return self._analysis().plan(plan_id)

    def collection_analysis_apply(self,plan_id,selection):
        return self._analysis().apply(plan_id,selection)

    def collection_classify(self,collection_id,category,selection=None,season=None):
        return self._collections().classify(collection_id,category,selection,season)

    def collection_identity_apply(self,plan_id):
        result=self._collections().identity_apply(plan_id)
        self.accounts.event(self.actor,'collection_identified','collection',result['collection_id'])
        return result

    def collection_mapping_plan(self,collection_id,selection=None,season=None):
        return self._collections().mapping_preview(collection_id,selection,season)

    def collection_mapping_apply(self,plan_id,idempotency_key):
        return self._collections().queue_mapping(plan_id,idempotency_key)

    def collection_subtitles(self,collection_id,idempotency_key,selection=None,season=None,mode='missing'):
        return self._collections().queue_subtitles(collection_id,idempotency_key,selection,season,mode)

    def collection_task(self,job_id):
        return self._collections().task(job_id)

    def _library_tasks(self):
        from media_mcp.application.library_tasks import LibraryTasks
        return LibraryTasks(self)

    def library_tasks(self,after='',limit=10):return self._library_tasks().list(after,limit)

    def library_task_status(self,job_id):return self._library_tasks().task(job_id)

    def library_session_recover(self,job_id):return self._library_tasks().recover_session(job_id)

    def library_task_details(self,job_id,after=0,limit=25,issues_only=False):
        return self._library_tasks().details(job_id,after,limit,issues_only)

    def library_auto_status(self,idempotency_key):return self._library_tasks().lookup_auto(idempotency_key)

    def download_submission_status(self,idempotency_key):
        key=hashlib.sha256(('acquire:'+self._key(idempotency_key)).encode()).hexdigest()
        row=self.records.by_key(key)
        return {'found':bool(row),'task':self.job(row['id']) if row else None}

    def inventory_scan(self):
        result = self._inventory().scan(self.actor.id)
        self.accounts.event(self.actor, 'inventory_scanned', 'inventory', result['scan_id'])
        return result

    def inventory_preview(self, scan_id, after=0, limit=50):
        return self._inventory().preview(scan_id, self.actor.id, after, limit)

    def inventory_import(self, scan_id):
        result = self._inventory().adopt(scan_id, self.actor.id)
        self.accounts.event(self.actor, 'inventory_imported', 'inventory', scan_id)
        return result

    def inventory(self, after=0, limit=50):
        return self._inventory().list(after, limit)

    def _subtitle_records(self, media):
        rows = [dict(row) for row in self.records.db.execute('''SELECT language,status,format,target_subtitle_path
            FROM media_subtitle WHERE matched_video_target_path=:target ORDER BY id''',
            {'target':media['target_path']}).mappings()]
        known = {row.pop('target_subtitle_path') for row in rows}
        if self.records.db.table_exists('media_inventory'):
            observed = self.records.db.execute('''SELECT path FROM media_inventory WHERE
                scan_id=(SELECT id FROM media_mcp_record WHERE kind='inventory_scan' AND state='imported'
                         ORDER BY updated_at DESC,rowid DESC LIMIT 1)
                AND json_extract(data,'$.kind')='subtitle' AND json_extract(data,'$.video_path')=:target''',
                {'target':media['target_path']}).mappings()
            rows.extend({'language':None, 'status':'discovered', 'format':path['path'].rsplit('.',1)[-1]}
                        for path in observed if path['path'] not in known)
        return rows

    def subtitles(self, media_id, idempotency_key):
        row = self.records.db.execute('SELECT * FROM media_link WHERE id=:id',
                                      {'id':int(media_id)}).mappings().first()
        if not row or not self._media_allowed(row, manage=True):
            raise ValueError('linked_media_not_found')
        result = self.service.subtitles(media_id, self._key(idempotency_key))
        self.accounts.event(self.actor, 'subtitles_requested', 'task', result['job_id'])
        return result

    def download_delete_preview(self,job_id):
        from media_mcp.application.deletion import Deletions
        return Deletions(self).download_preview(job_id)

    def collection_delete_preview(self,collection_id,selection=None,season=None):
        from media_mcp.application.deletion import Deletions
        return Deletions(self).collection_preview(collection_id,selection,season)

    def library_task_delete_preview(self,job_id):
        from media_mcp.application.deletion import Deletions
        return Deletions(self).task_preview(job_id)

    def deletion_apply(self,plan_id,confirm):
        from media_mcp.application.deletion import Deletions
        return Deletions(self).apply(plan_id,confirm)
