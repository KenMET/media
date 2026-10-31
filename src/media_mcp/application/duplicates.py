"""Review legacy duplicate targets without deleting source files or downloader tasks."""
import hashlib
import json
import os
from pathlib import Path
import time
from sqlalchemy import text

from media_mcp.application.collections import Collections, file_state, library_root
from media_mcp.config import contained
from media_mcp.runtime.state import media_mutation_lock, assert_mutation_lock
from media_mcp.runtime import version_changes
from media_mcp.storage.records import require_fresh


class Duplicates:
    def __init__(self,service):
        self.service=service;self.records=service.records;self.db=self.records.db
        self.library=Collections(service)

    @staticmethod
    def key(row):
        return (row['media_type'],row['media_tmdb_id'],row['season'],row['episode'])

    def rows(self):
        self.library.manage()
        return [dict(row) for row in self.db.execute("""SELECT * FROM media_link WHERE status='linked'
            AND media_type IN ('movie','tv') AND media_tmdb_id IS NOT NULL ORDER BY id""").mappings()]

    def freeze(self,row):
        if row['media_type']=='tv' and (row['season'] is None or row['episode'] is None):
            raise ValueError('duplicate_identity_requires_review')
        source=file_state(row['source_path'],'source');target=file_state(row['target_path'],'target')
        if not source or not target or source[:2]!=target[:2]:
            raise ValueError('duplicate_source_identity_requires_review')
        return {'id':row['id'],'identity':self.key(row),'source_path':row['source_path'],'target_path':row['target_path'],
                'source':source,'target':target,'updated_at':str(row['updated_at'])}

    def list(self):
        grouped={}
        for row in self.rows():
            grouped.setdefault(self.key(row),[]).append(row)
        groups=[]
        for identity,rows in grouped.items():
            if len(rows)<2:continue
            issue=None
            try:
                for row in rows:self.freeze(row)
            except ValueError as error:issue=str(error)
            groups.append({'title_id':f'{identity[0]}:{identity[1]}','season':identity[2],'episode':identity[3],
                'requires_review':issue,'versions':[{'id':row['id'],'name':row['media_name'],
                    'source_path':row['source_path'],'target_path':row['target_path'],'size':row['source_size']} for row in rows]})
        return {'groups':groups}

    def idle(self,files):
        paths={file[k] for file in files for k in ('source_path','target_path')}
        queue_exists=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_processing_job'").scalar()
        for row in (self.db.execute("SELECT path FROM media_processing_job WHERE state IN ('queued','retry','running')").mappings() if queue_exists else []):
            root=Path(row['path'])
            if any(str(root)==path or root in Path(path).parents for path in paths):
                raise ValueError('collection_operation_busy')
        for raw in self.db.execute("""SELECT data FROM media_mcp_record WHERE kind='library_task'
            AND state NOT IN ('completed','completed_with_warnings','failed','cancelled','deleted','needs_review')""").mappings():
            for file in json.loads(raw['data']).get('files',[]):
                if any(file.get(k) in paths for k in ('source_path','target_path')):
                    raise ValueError('collection_operation_busy')

    def preview(self,keep_id):
        self.library.manage()
        rows=self.rows();keep=next((row for row in rows if row['id']==keep_id),None)
        if keep is None:raise ValueError('record_not_found')
        rows=[row for row in rows if self.key(row)==self.key(keep)]
        if len(rows)<2:raise ValueError('no_duplicate_versions')
        with media_mutation_lock(self.db):
            snapshots=[self.freeze(row) for row in rows]
            self.idle(snapshots)
            targets={row['target_path'] for row in rows}
            if any(row['target_path'] in targets and self.key(row)!=self.key(keep) for row in self.rows()):
                raise ValueError('duplicate_shared_target_requires_review')
            row=self.records.put('duplicate_plan',{'owner':self.service.actor.id,'keep_id':keep_id,
                'files':snapshots,'expires_at':time.time()+900},'preview')
        return {'plan_id':row['id'],'keep_id':keep_id,'files':snapshots,
                'remove_targets':sorted(targets-{keep['target_path']})}

    def apply(self,plan_id,confirm):
        self.library.manage()
        if confirm is not True:raise ValueError('explicit_confirmation_required')
        with media_mutation_lock(self.db,timeout=5) as conn:
            version_changes.initialize(self.db)
            version_changes.recover_pending(conn)
            row=self.records.get(plan_id,'duplicate_plan');data=row['data']
            if data['owner']!=self.service.actor.id:raise ValueError('record_not_found')
            if row['state']=='applied':return data['receipt']
            require_fresh(data)
            current={item['id']:item for item in self.rows()}
            files=data['files']
            if any(file['id'] not in current or json.loads(json.dumps(self.freeze(current[file['id']])))!=file for file in files):
                raise ValueError('collection_changed_rebuild_plan')
            keep=current[data['keep_id']]
            group=[item for item in current.values() if self.key(item)==self.key(keep)]
            if {item['id'] for item in group}!={file['id'] for file in files}:
                raise ValueError('collection_changed_rebuild_plan')
            self.idle(files)
            selected={file['id'] for file in files}
            targets={file['target_path'] for file in files}
            # Include unknown identities too: no other record may share retired targets.
            others=self.db.execute('SELECT id,target_path FROM media_link').mappings()
            if any(other['id'] not in selected and other['target_path'] in targets for other in others):
                raise ValueError('duplicate_shared_target_requires_review')
            previous=[item for item in group if item['id']!=keep['id'] and item['target_path']!=keep['target_path']]
            # One journal entry per physical target, even when legacy rows share a target.
            previous=list({item['target_path']:item for item in previous}.values())
            conn.commit()
            change,payload=version_changes.prepare(conn,keep['source_path'],keep['target_path'],previous,preserve_target=True)
            shared=[sidecar for sidecar in payload['sidecars'] if Path(sidecar['video_target']).with_suffix('')==Path(keep['target_path']).with_suffix('')]
            payload['sidecars']=[sidecar for sidecar in payload['sidecars'] if sidecar not in shared]
            conn.execute(text('UPDATE media_version_change SET payload_json=:payload WHERE id=:id'),{'payload':json.dumps(payload),'id':change});conn.commit()
            committed=False
            try:
                for old in payload['previous']:
                    assert_mutation_lock();os.link(old['path'],old['backup'])
                for sidecar in payload['sidecars']:
                    foreign=self.db.execute("SELECT 1 FROM media_subtitle WHERE target_subtitle_path=:path AND matched_video_target_path!=:video LIMIT 1",{'path':sidecar['path'],'video':sidecar['video_target']}).scalar()
                    if foreign:raise ValueError('duplicate_shared_subtitle_requires_review')
                    archive=Path(sidecar['archive'])
                    if any(p.is_symlink() for p in (archive.parent,*archive.parents)):
                        raise ValueError('subtitle_archive_parent_symlink_rejected')
                    archive.parent.mkdir(parents=True,exist_ok=True)
                    if os.path.lexists(archive):raise ValueError('subtitle_archive_conflict')
                    assert_mutation_lock();os.replace(sidecar['path'],archive)
                receipt={'plan_id':plan_id,'kept_media_id':keep['id'],'retired_versions':len(group)-1,
                         'removed_targets':[old['path'] for old in payload['previous']]}
                with conn.begin():
                    for item in group:
                        if item['id']==keep['id']:continue
                        conn.execute(text("""UPDATE media_link SET status='unlinked',target_path='',target_path_hash=:hash,
                            target_exists=0,reason='duplicate_cleanup_confirmed',updated_at=CURRENT_TIMESTAMP WHERE id=:id"""),
                            {'hash':hashlib.sha256(b'').hexdigest(),'id':item['id']})
                    inventory_exists=conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_inventory'")).scalar()
                    for old in payload['previous']:
                        if inventory_exists:conn.execute(text('DELETE FROM media_inventory WHERE path=:path'),{'path':old['path']})
                        conn.execute(text('DELETE FROM media_library_classification WHERE path=:path'),{'path':old['path']})
                    for sidecar in payload['sidecars']:
                        conn.execute(text("""UPDATE media_subtitle SET target_subtitle_path=:archive,
                            target_subtitle_path_hash=:hash,status='superseded',updated_at=CURRENT_TIMESTAMP
                            WHERE target_subtitle_path=:path"""),{'archive':sidecar['archive'],
                            'hash':hashlib.sha256(sidecar['archive'].encode()).hexdigest(),'path':sidecar['path']})
                    conn.execute(text("UPDATE media_version_change SET state='committed' WHERE id=:id"),{'id':change})
                    updated=conn.execute(text("""UPDATE media_mcp_record SET state='applied',data=:data,
                        revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND revision=:revision"""),
                        {'data':json.dumps({**data,'receipt':receipt}),'id':plan_id,'revision':row['revision']})
                    if updated.rowcount!=1:raise RuntimeError('stale_job_revision')
                committed=True
                version_changes.recover_one(conn,change,payload,True)
                return receipt
            except BaseException:
                conn.rollback();version_changes.recover_one(conn,change,payload,committed);raise
