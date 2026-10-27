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
            Budget(self.db,self.accounts.clock).admit_job(self.actor.id)
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
    def search_titles(self, query, kind, year=None):
        return self.service.search_titles(query, kind, year)

    @limited('search')
    def search_releases(self, title_id, season=None, episodes=None, resolution=None):
        self._download_permission()
        return self.service.search_releases(title_id, season, episodes, resolution)

    @limited('plan')
    def plan(self, release_id):
        self._download_permission()
        return self.service.plan(release_id)

    def start(self, plan_id, revision, idempotency_key):
        self._download_permission()
        # All ownership is persisted in the acquisition record before worker visibility.
        result = self.service.start(plan_id, revision, self._key(idempotency_key))
        self.accounts.event(self.actor, 'download_requested', 'task', result['job_id'])
        return result

    def job(self, job_id):
        row = self._task(job_id)
        result = self.service.public_job(row)
        result.update(owner_id=row['data'].get('_platform_owner'),
                      entry=row['data'].get('_platform_entry', 'legacy'),
                      created_at=str(row.get('created_at', '')), updated_at=str(row.get('updated_at', '')))
        return result

    def jobs(self, after='', limit=30):
        if after and not re.fullmatch(r'[a-f0-9]{32}', after):
            raise ValueError('invalid_cursor')
        limit = min(max(int(limit), 1), 100)
        if after:
            self._task(after)
        rows = self.records.db.execute('''SELECT r.id FROM media_mcp_record r
            WHERE r.kind='acquisition' AND (:after='' OR
                r.created_at<(SELECT created_at FROM media_mcp_record WHERE id=:after) OR
                (r.created_at=(SELECT created_at FROM media_mcp_record WHERE id=:after) AND r.id<:after)) AND
            (:admin=1 OR json_extract(r.data,'$._platform_owner')=:user OR EXISTS
                (SELECT 1 FROM platform_access a WHERE a.kind='task' AND a.object_id=r.id AND a.user_id=:user))
            ORDER BY r.created_at DESC,r.id DESC LIMIT :limit''', {'after':after, 'admin':int(self.actor.admin),
                                          'user':self.actor.id, 'limit':limit}).mappings().all()
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

    def _subtitle_records(self, media):
        return [dict(row) for row in self.records.db.execute('''SELECT language,status,format
            FROM media_subtitle WHERE matched_video_target_path=:target ORDER BY id''',
            {'target':media['target_path']}).mappings()]

    def subtitles(self, media_id, idempotency_key):
        row = self.records.db.execute('SELECT * FROM media_link WHERE id=:id',
                                      {'id':int(media_id)}).mappings().first()
        if not row or not self._media_allowed(row, manage=True):
            raise ValueError('linked_media_not_found')
        result = self.service.subtitles(media_id, self._key(idempotency_key))
        self.accounts.event(self.actor, 'subtitles_requested', 'task', result['job_id'])
        return result
