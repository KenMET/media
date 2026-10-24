"""Local SQLite persistence. No database server or database credentials."""
from __future__ import annotations
from contextlib import contextmanager
from functools import lru_cache
import fcntl
import hashlib
import os
from pathlib import Path
import time
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.pool import NullPool


def database_path():
    return Path(os.environ.get('MEDIA_DB_PATH') or
                str(Path(os.environ.get('MEDIA_STATE_DIR','/state'))/'media.sqlite3')).resolve()


@lru_cache(maxsize=16)
def _engine(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    engine=create_engine('sqlite:///'+path, poolclass=NullPool,
        connect_args={'timeout':30,'check_same_thread':False}, hide_parameters=True)
    @event.listens_for(engine,'connect')
    def configure(conn,_):
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
    with engine.connect() as conn:
        conn.exec_driver_sql('PRAGMA journal_mode=WAL')
    os.chmod(path,0o600)
    return engine


class FileLock:
    def __init__(self,path,timeout=0):
        self.path=Path(path)
        self.timeout=timeout
        self.handle=None
        self.held=False
        self.pid=os.getpid()

    def acquire(self,timeout=None):
        if self.handle is None:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.handle=open(self.path,'a+b')
        deadline=time.monotonic()+(self.timeout if timeout is None else timeout)
        while True:
            try:
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.held=True
                self.check()
                return self
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('media_busy_retry_later') from None
                time.sleep(.05)

    def check(self):
        if not self.held or self.handle is None or self.handle.closed or os.getpid()!=self.pid:
            raise RuntimeError('media_mutation_lock_lost')
        try:
            a,b=os.fstat(self.handle.fileno()),self.path.stat()
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):raise RuntimeError('media_mutation_lock_lost')
        except OSError:raise RuntimeError('media_mutation_lock_lost') from None

    def release(self):
        if self.handle and not self.handle.closed:
            fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        self.held=False

    def close(self):
        self.release()
        if self.handle:self.handle.close()


class DatabaseClient:
    def __init__(self,db_name=None,**_):
        self.path=database_path()
        self.db_name=str(self.path)
        self.engine=_engine(str(self.path))

    def _guard(self):
        if os.environ.get('MEDIA_TEST_NO_EXTERNAL')=='1':
            raise RuntimeError('database access disabled for this test process')

    def ensure_database(self):
        self._guard()

    def execute(self,sql,params=None):
        self._guard()
        with self.engine.begin() as conn:
            result=conn.execute(text(sql),params or {})
            if result.returns_rows:
                rows=result.freeze()()
                rows.rowcount=result.rowcount
                return rows
            return result

    def executemany(self,sql,rows):
        self._guard()
        with self.engine.begin() as conn:return conn.execute(text(sql),rows)

    @contextmanager
    def begin(self):
        self._guard()
        with self.engine.connect() as conn:
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @contextmanager
    def isolated_connection(self):
        self._guard()
        with self.engine.connect() as conn:yield conn

    @contextmanager
    def lock(self,name,timeout=0):
        path=self.path.parent/'locks'/(hashlib.sha256((str(self.path)+':'+name).encode()).hexdigest()+'.lock')
        lock=FileLock(path,timeout)
        try:
            lock.acquire()
            yield lock
        finally:lock.close()

    def table_exists(self,name):return inspect(self.engine).has_table(name)
    def column_exists(self,table,column):return any(c['name']==column for c in inspect(self.engine).get_columns(table))
    def index_exists(self,table,index):return any(i['name']==index for i in inspect(self.engine).get_indexes(table))
