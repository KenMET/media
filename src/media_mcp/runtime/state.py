"""SQLite durable jobs and cross-process filesystem mutation fencing."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import uuid
from sqlalchemy import text
from media_mcp.storage.client import DatabaseClient

_active_mutation_lock=ContextVar('media_mutation_lock',default=None)
_invalidated_mutation_scope=ContextVar('media_mutation_scope_invalidated',default=False)
_job_guard=ContextVar('media_job_guard',default=None)


@contextmanager
def media_job_guard(validate):
    token=_job_guard.set(validate)
    try:yield
    finally:_job_guard.reset(token)


def assert_mutation_lock():
    guard=_job_guard.get()
    if guard:guard()
    if _invalidated_mutation_scope.get():raise RuntimeError('media_mutation_scope_invalidated')
    active=_active_mutation_lock.get()
    if active:active[0].check()


def mutation_lock_is_active():return _active_mutation_lock.get() is not None


@contextmanager
def release_mutation_lock_for_io(validate=None):
    active=_active_mutation_lock.get()
    if active is None:
        yield
        return
    lock,conn=active
    assert_mutation_lock()
    conn.commit()
    lock.release()
    token=_active_mutation_lock.set(None)
    try:yield
    finally:
        _active_mutation_lock.reset(token)
        try:
            lock.acquire(timeout=5)
            if validate is not None and not validate():raise RuntimeError('media_changed_during_model_call')
        except Exception:
            _invalidated_mutation_scope.set(True)
            raise


@contextmanager
def media_mutation_lock(db,timeout=0):
    with db.lock('mutations',timeout) as lock, db.isolated_connection() as conn:
        token=_active_mutation_lock.set((lock,conn))
        invalid=_invalidated_mutation_scope.set(False)
        try:yield conn
        finally:
            _active_mutation_lock.reset(token)
            _invalidated_mutation_scope.reset(invalid)


class MediaJobs:
    def __init__(self,db_name=None):self.db=DatabaseClient(db_name)
    def reset_after_fork(self):self.db.engine.dispose(close=False)

    def initialize(self):
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_processing_job (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_key TEXT NOT NULL, stage TEXT NOT NULL,
            path TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT NOT NULL,
            owner TEXT,lease_until TEXT,error TEXT,result_json TEXT,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
            UNIQUE(delivery_key,stage))''')
        self.db.execute('CREATE INDEX IF NOT EXISTS due_jobs ON media_processing_job(stage,state,next_attempt_at)')

    def enqueue(self,key,path,stage='ingest'):
        if stage not in ('ingest','subtitle','library'):raise ValueError('invalid_media_stage')
        self.db.execute('''INSERT OR IGNORE INTO media_processing_job
            (delivery_key,stage,path,state,next_attempt_at,created_at,updated_at)
            VALUES(:key,:stage,:path,'queued',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)''',
            {'key':hashlib.sha256(key.encode()).hexdigest(),'stage':stage,'path':path})

    def claim(self,stage):
        owner=uuid.uuid4().hex
        with self.db.begin() as conn:
            row=conn.execute(text('''SELECT * FROM media_processing_job WHERE stage=:stage AND
                ((state IN ('queued','retry') AND next_attempt_at<=CURRENT_TIMESTAMP)
                OR (state='running' AND lease_until<CURRENT_TIMESTAMP)) ORDER BY id LIMIT 1'''),{'stage':stage}).mappings().first()
            if not row:return None
            conn.execute(text('''UPDATE media_processing_job SET state='running',owner=:owner,
                attempts=attempts+1,lease_until=datetime('now','+120 seconds'),updated_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {'owner':owner,'id':row['id']})
            return {**row,'owner':owner,'attempts':row['attempts']+1}

    def renew(self,job):
        return self.db.execute('''UPDATE media_processing_job SET lease_until=datetime('now','+120 seconds'),
            updated_at=CURRENT_TIMESTAMP WHERE id=:id AND owner=:owner AND state='running' AND lease_until>CURRENT_TIMESTAMP''',job).rowcount==1

    def finish(self,job,*,error=None,result='{}',review_required=False,retry_delay_seconds=None):
        if retry_delay_seconds is None and error=='model_quota_waiting':
            from media_mcp.runtime.quota_wait import QUOTA_CHECK_SECONDS
            retry_delay_seconds=QUOTA_CHECK_SECONDS
        delay=int(retry_delay_seconds) if retry_delay_seconds is not None else min(3600,30*2**min(int(job['attempts']),7))
        if delay < 0:raise ValueError('invalid_retry_delay')
        with self.db.begin() as conn:
            owned=conn.execute(text('''SELECT id FROM media_processing_job WHERE id=:id AND owner=:owner
                AND state='running' AND lease_until>CURRENT_TIMESTAMP'''),job).first()
            if not owned:raise RuntimeError('media_job_lease_lost')
            conn.execute(text('''UPDATE media_processing_job SET state=:state,error=:error,result_json=:result,
                next_attempt_at=datetime('now',:delay),owner=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE id=:id AND owner=:owner AND state='running' '''),
                {**job,'state':'needs_review' if review_required else ('retry' if error else 'succeeded'),
                 'error':error,'result':result,'delay':f'+{delay} seconds'})
            if job['stage']=='ingest':
                counts=json.loads(result)
                if job['attempts']==1 or counts.get('created',0)+counts.get('relinked',0)>0:
                    conn.execute(text('''INSERT INTO media_processing_job
                        (delivery_key,stage,path,state,next_attempt_at,created_at,updated_at)
                        VALUES(:delivery_key,'subtitle',:path,'queued',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                        ON CONFLICT(delivery_key,stage) DO UPDATE SET
                        state=CASE WHEN state='running' THEN state ELSE 'queued' END,
                        next_attempt_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP'''),job)
