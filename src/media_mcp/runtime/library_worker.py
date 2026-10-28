"""Durable collection maintenance, with the existing lease and mutation fences."""
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import time
from sqlalchemy import text

from media_mcp.application.collections import Collections, mapping_state
from media_mcp.runtime.state import MediaJobs,media_mutation_lock,assert_mutation_lock,media_job_guard
from media_mcp.runtime.worker import heartbeat
from media_mcp.storage.records import Records


def repair_mapping(library,jobs,conn,file,operation):
    from media_mcp.runtime import version_changes
    from media_mcp.storage.media import upsert_media_link
    from media_mcp.config import contained
    from media_mcp.application.collections import library_root,file_state
    target=operation['target_path'];source=file['source_path']
    contained(target,library_root(),exists=False)
    if operation['action']=='refresh_record':
        current=next((f for f in library.files() if f['key']==file['key']),None)
        if current and current.get('status')=='unlinked':
            raise ValueError('version_selection_required')
        observed=library.freeze(current) if current else None
        expected=json.loads(json.dumps(file))
        if observed:
            for key in ('status','reason','fail_stage'):
                observed['metadata'].pop(key,None)
                expected['metadata'].pop(key,None)
        if observed!=expected:
            raise ValueError('collection_changed_rebuild_plan')
        if mapping_state(file)['status']!='linked':
            raise ValueError('collection_changed_rebuild_plan')
        assert_mutation_lock()
        conn.execute(text("""UPDATE media_link SET status='linked',source_exists=1,target_exists=1,
            fail_stage=NULL,reason='library_mapping_checked',updated_at=CURRENT_TIMESTAMP WHERE id=:id"""),{'id':file['media_id']})
        conn.commit()
        return {'key':file['key'],'state':'completed','record_refreshed':True}
    version_changes.initialize(jobs.db)
    assert_mutation_lock()
    version_changes.recover_pending(conn)
    if os.path.lexists(target):
        existing=jobs.db.execute('SELECT * FROM media_link WHERE source_path=:source AND target_path=:target',{'source':source,'target':target}).mappings().first()
        expected_title=file['title_id']
        if (not existing or existing['status']!='linked' or (file['media_id'] and existing['id']!=file['media_id']) or
            f"{existing['media_type']}:{existing['media_tmdb_id']}"!=expected_title or
            existing['season']!=file['season'] or existing['episode']!=file['episode'] or
            file_state(source,'source')!=file['state']['source'] or
            file_state(target,'target')[:2]!=file['state']['source'][:2]):
            raise ValueError('collection_target_changed')
        return {'key':file['key'],'state':'completed','recovered':True}
    library.validate([file])
    if jobs.db.execute('SELECT id FROM media_link WHERE target_path=:target AND id!=:id',{'target':target,'id':file['media_id'] or -1}).first():
        raise ValueError('collection_target_owned')
    current=next(f for f in library.files() if f['key']==file['key'])
    Path(target).parent.mkdir(parents=True,exist_ok=True)
    contained(target,library_root(),exists=False)
    change,payload=version_changes.prepare(conn,source,target,[])
    try:
        assert_mutation_lock()
        os.link(source,target)
        metadata={key:current.get(key) for key in ('media_type','media_tmdb_id','media_name','base_title','alt_name','year','season','episode')}
        annotation=current.get('identity')
        if annotation:
            identity=annotation['identity']
            metadata.update(media_type=identity['kind'],media_tmdb_id=identity['tmdb_id'],media_name=identity['title'],
                base_title=identity['title'],alt_name=identity.get('original_title'),original_language=identity.get('original_language'),
                year=int(identity['date'][:4]) if identity.get('date') else None)
        assert_mutation_lock()
        if file['media_id']:
            fingerprint=file_state(source,'source')
            conn.execute(text('''UPDATE media_link SET target_path=:target,target_path_hash=:hash,
                source_exists=1,target_exists=1,source_size=:size,target_size=:size,
                source_inode=:inode,target_inode=:inode,status='linked',reason='library_mapping_repair',
                updated_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {'target':target,'hash':hashlib.sha256(target.encode()).hexdigest(),'size':fingerprint[2],
                 'inode':fingerprint[1],'id':file['media_id']})
        else:
            upsert_media_link(None,source,target,**metadata,status='linked',reason='library_mapping_repair',_connection=conn)
        conn.execute(text("UPDATE media_version_change SET state='committed',updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':change})
        conn.commit()
    except BaseException:
        conn.rollback()
        assert_mutation_lock()
        version_changes.recover_one(conn,change,payload,False)
        raise
    version_changes.recover_one(conn,change,payload,True)
    return {'key':file['key'],'state':'completed'}


def process_task(jobs,job,subtitle_agent=None):
    from media_mcp.platform.accounts import Accounts
    from media_mcp.platform.service import PlatformService
    from media_mcp.runtime import version_changes
    from media_mcp.storage.media import upsert_media_link
    records=Records(jobs.db)
    row=jobs.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND json_extract(data,'$.processing_key')=:key",{'key':job['delivery_key']}).mappings().first()
    if not row:
        raise ValueError('library_task_not_found')
    row=records.decode(row)
    if row['state'] in ('completed','completed_with_warnings','needs_review'):
        return
    accounts=Accounts(jobs.db);actor=accounts.actor_by_id(row['data']['owner'])
    if not actor.can_manage_media:
        raise ValueError('media_management_permission_required')
    library=Collections(PlatformService(actor,accounts,records))
    def lease():
        if not jobs.db.execute("SELECT id FROM media_processing_job WHERE id=:id AND owner=:owner AND state='running' AND lease_until>CURRENT_TIMESTAMP",job).first():
            raise RuntimeError('media_job_lease_lost')
    lease()
    row=records.update(row,'running')
    data=row['data'];completed={item['key'] for item in data['results']}
    for file in data['files']:
        if file['key'] in completed:
            continue
        lease()
        try:
            with media_job_guard(lease),media_mutation_lock(jobs.db) as conn:
                # Permission changes and file changes after queueing both fail closed.
                fresh=accounts.actor_by_id(data['owner'])
                if not fresh.can_manage_media:
                    raise ValueError('media_management_permission_required')
                if data['action']=='mapping':
                    operation=next(op for op in data['operations'] if op['key']==file['key'])
                    result=repair_mapping(library,jobs,conn,file,operation)
                else:
                    library.validate([file])
                    if subtitle_agent is None:
                        from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
                        subtitle_agent=SubtitleAgent(defer_ai_usage=True)
                    path=file['source_path'] if file['state']['source'] else file['target_path']
                    rows=jobs.db.execute("""SELECT id FROM media_link WHERE (source_path=:path OR target_path=:path)
                        AND status IN ('linked','source_missing','target_missing')""",{'path':path}).mappings().all()
                    if {row['id'] for row in rows}!={file['media_id']}:
                        raise ValueError('collection_mapping_ambiguous')
                    # Already hold the mutation lock; the agent releases/revalidates it for external I/O.
                    summary=subtitle_agent._run_path_summary_locked(path,send_notify=False)
                    counts={key:summary[key] for key in ('handled','media_count','sidecar_count','skipped','failed','missing','review') if type(summary.get(key)) is int}
                    incomplete=summary.get('media_count')!=1 or not summary.get('handled') or summary.get('failed') or summary.get('missing') or summary.get('review')
                    result={'key':file['key'],'state':'needs_review' if incomplete else 'completed','summary':counts}
                assert_mutation_lock()
        except Exception as error:
            if str(error) in ('media_job_lease_lost','media_mutation_lock_lost','media_mutation_scope_invalidated'):
                raise
            code=str(error) if isinstance(error,ValueError) else type(error).__name__
            result={'key':file['key'],'state':'needs_review','error_code':code if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,100}',code) else type(error).__name__}
        lease()
        data['results'].append(result)
        row=records.update(row,'running',data)
    lease()
    state='completed_with_warnings' if data.get('blocked') or any(item['state']!='completed' for item in data['results']) else 'completed'
    records.update(row,state,data)


def run_library_worker():
    jobs=MediaJobs();jobs.reset_after_fork();jobs.initialize()
    while True:
        heartbeat('library')
        job=jobs.claim('library')
        if not job:
            time.sleep(2);continue
        done=threading.Event()
        def renew():
            while not done.wait(20):
                try:
                    if not jobs.renew(job):os._exit(1)
                    heartbeat('library')
                except Exception:os._exit(1)
        thread=threading.Thread(target=renew,daemon=True);thread.start()
        error=None
        try:
            process_task(jobs,job)
        except Exception as exc:
            error=type(exc).__name__
            if jobs.renew(job):
                records=Records(jobs.db)
                row=jobs.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND json_extract(data,'$.processing_key')=:key",{'key':job['delivery_key']}).mappings().first()
                if row:
                    row=records.decode(row)
                    records.update(row,'needs_review',{**row['data'],'error_code':error})
        finally:
            done.set();thread.join(timeout=2)
        jobs.finish(job,error=error,review_required=bool(error),result=json.dumps({'error':error}))
        heartbeat('library')
