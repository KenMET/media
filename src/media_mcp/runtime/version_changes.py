"""Crash recovery for the filesystem side of a preferred-version transaction."""
from __future__ import annotations
import json
import os
from pathlib import Path
import uuid
from functools import lru_cache
from sqlalchemy import text


@lru_cache(maxsize=16)
def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS media_version_change (
        id CHAR(32) PRIMARY KEY, state VARCHAR(16) NOT NULL,
        payload_json LONGTEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS pending_changes ON media_version_change(state,created_at)')


def identity(path):
    value=os.stat(path,follow_symlinks=False)
    return [int(value.st_dev),int(value.st_ino),int(value.st_size),int(value.st_mtime_ns)]


def prepare(conn,source,target,previous):
    change_id=uuid.uuid4().hex
    payload={'source':source,'source_identity':identity(source),'target':target,'previous':[],'sidecars':[]}
    for row in previous:
        old=row['target_path']
        payload['previous'].append({'path':old,'source':row['source_path'],'identity':identity(old),
            'backup':old+'.phantom-backup-'+change_id})
        archive=Path(row['source_path']).parent/'.phantom-subtitles'/str(row['id'])
        stem=Path(old).stem
        for entry in Path(old).parent.iterdir():
            if entry.suffix.lower() in {'.srt','.ass','.ssa','.vtt','.sup','.sub','.idx'} and (entry.stem==stem or entry.name.startswith(stem+'.')) and entry.is_file() and not entry.is_symlink():
                payload['sidecars'].append({'path':str(entry),'archive':str(archive/(change_id+'-'+entry.name)),
                    'identity':identity(entry),'video_source':row['source_path'],'video_target':old,'format':entry.suffix.lstrip('.')})
    conn.execute(text("INSERT INTO media_version_change(id,state,payload_json,created_at,updated_at) VALUES(:id,'prepared',:payload,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),{'id':change_id,'payload':json.dumps(payload)})
    conn.commit()
    return change_id,payload


def recover_one(conn,change_id,payload,committed):
    def matches(path,expected):
        try:return identity(path)==expected and not os.path.islink(path)
        except OSError:return False
    if committed:
        for old in payload['previous']:
            if old['path']!=payload['target'] and os.path.lexists(old['path']):
                if not matches(old['path'],old['identity']):
                    raise RuntimeError('version_cleanup_identity_changed')
                os.unlink(old['path'])
    else:
        # Restore only identities recorded before the swap. Never overwrite a
        # replacement supplied by an external process while Media was offline.
        for sidecar in reversed(payload['sidecars']):
            archived=sidecar['archive'];original=sidecar['path']
            if os.path.lexists(archived):
                if not matches(archived,sidecar['identity']) or os.path.lexists(original):
                    raise RuntimeError('subtitle_recovery_requires_review')
                os.replace(archived,original)
        for old in payload['previous']:
            current=old['path']
            if matches(current,old['identity']):
                continue
            if os.path.lexists(current) and not matches(current,payload['source_identity']):
                raise RuntimeError('version_recovery_requires_review')
            recovery_source=old['backup'] if matches(old['backup'],old['identity']) else old['source']
            if not matches(recovery_source,old['identity']):
                raise RuntimeError('original_version_unavailable')
            staged=current+'.recover-'+change_id
            if os.path.lexists(staged):
                if not matches(staged,old['identity']):raise RuntimeError('recovery_staging_conflict')
            else:os.link(recovery_source,staged)
            os.replace(staged,current)
        if not any(row['path']==payload['target'] for row in payload['previous']) and matches(payload['target'],payload['source_identity']):
            os.unlink(payload['target'])
    for old in payload['previous']:
        if os.path.lexists(old['backup']):
            if not matches(old['backup'],old['identity']):raise RuntimeError('version_backup_identity_changed')
            os.unlink(old['backup'])
    staged=payload['target']+'.phantom-new-'+change_id
    if os.path.lexists(staged):
        if not matches(staged,payload['source_identity']):raise RuntimeError('version_staging_identity_changed')
        os.unlink(staged)
    conn.execute(text("UPDATE media_version_change SET state='done',updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':change_id})
    conn.commit()


def recover_pending(conn):
    rows=conn.execute(text("SELECT id,state,payload_json FROM media_version_change WHERE state IN ('prepared','committed') ORDER BY created_at,id")).mappings().all()
    conn.commit()
    for row in rows:
        recover_one(conn,row['id'],json.loads(row['payload_json']),row['state']=='committed')
