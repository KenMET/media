"""Select one preferred version while retaining every displaced source file."""
from __future__ import annotations
import json
import os
from pathlib import Path
import uuid
from sqlalchemy import text
from media_mcp.storage.media import _client, upsert_media_link
from media_mcp.ingest.domain.file_utils import create_hardlink_with_target
from media_mcp.ingest.domain.quality import probe_quality, compare_quality
from media_mcp.runtime.state import media_mutation_lock, assert_mutation_lock
from media_mcp.runtime import version_changes


def apply_preferred_media(source: str, target: str, metadata: dict, db_name: str):
    from media_mcp.application.identity import validate_identity
    from media_mcp.config import contained
    contained(source)
    validate_identity(metadata)
    if os.path.islink(source) or not os.path.isfile(source):
        return False, 'Source must be a regular file', None
    parents = (Path(target).parent,Path(source).parent)
    if any(part.is_symlink() for parent in parents for part in (parent,*parent.parents)):
        return False, 'Target parent symlink is not allowed', None
    db = _client(db_name)
    version_changes.initialize(db)
    with media_mutation_lock(db,timeout=5) as conn:
        conn.commit()
        version_changes.recover_pending(conn)
        params = {'source': source, 'target': target, 'kind': metadata['media_type'],
                  'tmdb':metadata.get('media_tmdb_id'), 'season':metadata.get('season'),
                  'episode':metadata.get('episode'), 'extra_type':metadata.get('extra_type'),
                  'extra_index':metadata.get('extra_index')}
        rows = conn.execute(text('''SELECT * FROM media_link WHERE status='linked' AND
            (target_path=:target OR (:tmdb IS NOT NULL AND media_type=:kind AND media_tmdb_id=:tmdb
             AND season IS :season AND episode IS :episode AND extra_type IS :extra_type AND extra_index IS :extra_index))'''), params).mappings().all()
        conn.commit()
        previous = [dict(row) for row in rows if row['source_path'] != source and os.path.isfile(row['target_path'])]
        # Resolve by actual inode; stale mappings may not establish a version's provenance.
        for row in previous:
            if not os.path.isfile(row['source_path']) or not os.path.samefile(row['source_path'],row['target_path']):
                return False, 'Existing version identity requires review', None
        if os.path.lexists(target) and not any(row['target_path']==target for row in previous):
            if os.path.islink(target) or not os.path.samefile(source,target):
                return False, 'Untracked target conflict requires review', None
        if not previous:
            assert_mutation_lock()
            conn.commit()
            ok,reason,actual=create_hardlink_with_target(source,target)
            if ok:
                upsert_media_link(db_name,source,actual,**metadata,status='linked',reason=reason)
            return ok,reason,actual
        candidate_identity = version_changes.identity(source)
        candidate = probe_quality(source)
        for row in previous:
            old_tmdb,new_tmdb=row.get('media_tmdb_id'),metadata.get('media_tmdb_id')
            if old_tmdb != new_tmdb or (row.get('media_type') and row['media_type']!=metadata['media_type']) or any(row.get(field)!=metadata.get(field) for field in ('season','episode','extra_type','extra_index')):
                return False, 'Different media identities share a target; review required', None
        for row in previous:
            current = probe_quality(row['target_path'],row['source_path'])
            comparison = compare_quality(candidate,current)
            if comparison != 1:
                reason = 'lower_or_equal_quality' if comparison in (-1,0) else 'quality_not_comparable'
                upsert_media_link(db_name,source,'',**metadata,status='unlinked',reason=reason+'; '+json.dumps({'candidate':candidate,'current':current}))
                return True, 'Unlinked lower or uncertain quality', ''
        if version_changes.identity(source)!=candidate_identity:
            return False, 'Source changed during quality probe', None
        assert_mutation_lock()
        conn.commit()
        change_id,payload=version_changes.prepare(conn,source,target,previous)
        committed=False
        try:
            for old in payload['previous']:
                os.link(old['path'],old['backup'])
            staged=target+'.phantom-new-'+change_id
            if os.path.lexists(target):
                os.link(source,staged)
                os.replace(staged,target)
                actual=target
                reason='Overwrite hardlink'
            else:
                ok,reason,actual=create_hardlink_with_target(source,target)
                if not ok:raise RuntimeError(reason)
                if actual!=target:
                    payload['target']=actual
                    conn.execute(text('UPDATE media_version_change SET payload_json=:payload WHERE id=:id'),{'id':change_id,'payload':json.dumps(payload)})
                    conn.commit()
            for sidecar in payload['sidecars']:
                archive_parent = Path(sidecar['archive']).parent
                if any(part.is_symlink() for part in (archive_parent,*archive_parent.parents)):
                    raise RuntimeError('subtitle_archive_parent_symlink_rejected')
                archive_parent.mkdir(parents=True,exist_ok=True)
                os.replace(sidecar['path'],sidecar['archive'])
            with conn.begin():
                for row in previous:
                    conn.execute(text("UPDATE media_link SET status='unlinked',target_path='',target_path_hash=:empty_hash,target_exists=0,reason='superseded_by_higher_quality',updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                        {'id':row['id'],'empty_hash':__import__('hashlib').sha256(b'').hexdigest()})
                    conn.execute(text("UPDATE media_subtitle SET status='superseded',updated_at=CURRENT_TIMESTAMP WHERE matched_video_target_path=:path"),{'path':row['target_path']})
                for sidecar in payload['sidecars']:
                    sidecar = {**sidecar,'path_hash':__import__('hashlib').sha256(sidecar['path'].encode()).hexdigest(),
                               'archive_hash':__import__('hashlib').sha256(sidecar['archive'].encode()).hexdigest()}
                    updated = conn.execute(text('UPDATE media_subtitle SET target_subtitle_path=:archive,target_subtitle_path_hash=:archive_hash WHERE target_subtitle_path=:path'),sidecar)
                    if updated.rowcount == 0:
                        conn.execute(text('''INSERT INTO media_subtitle
                            (source_subtitle_path_hash,target_subtitle_path_hash,source_subtitle_path,target_subtitle_path,
                             matched_video_source_path,matched_video_target_path,source_type,format,status,reason,created_at,updated_at)
                            VALUES(:path_hash,:archive_hash,:path,:archive,:video_source,:video_target,
                                   'version_archive',:format,'superseded','archived_with_displaced_source',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'''),sidecar)
                upsert_media_link(db_name,source,actual,**metadata,status='linked',reason=reason,_connection=conn)
                conn.execute(text("UPDATE media_version_change SET state='committed',updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':change_id})
            committed=True
            version_changes.recover_one(conn,change_id,payload,True)
            return True,reason,actual
        except Exception:
            conn.rollback()
            version_changes.recover_one(conn,change_id,payload,committed)
            raise
