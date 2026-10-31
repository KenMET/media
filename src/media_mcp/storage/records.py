"""Durable acquisition records alongside the migrated MySQL processing jobs."""
import json
import time
import uuid
from sqlalchemy import text
from .client import DatabaseClient


class Records:
    def __init__(self, db=None):
        self.db = db or DatabaseClient(connect_timeout_seconds=5, read_timeout_seconds=15)

    def initialize(self):
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_mcp_record (
            id CHAR(32) PRIMARY KEY, kind VARCHAR(24) NOT NULL,
            data LONGTEXT NOT NULL, state VARCHAR(32) NOT NULL,
            revision INT NOT NULL DEFAULT 1, key_hash CHAR(64) UNIQUE,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        )''')
        self.db.execute('CREATE INDEX IF NOT EXISTS kind_state ON media_mcp_record(kind,state)')

    def put(self, kind, data, state='ready', key_hash=None, ident=None):
        ident = ident or uuid.uuid4().hex
        self.db.execute('''INSERT INTO media_mcp_record
            (id,kind,data,state,key_hash,created_at,updated_at)
            VALUES(:id,:kind,:data,:state,:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)''',
            {'id': ident, 'kind': kind, 'data': json.dumps(data, ensure_ascii=False),
             'state': state, 'key': key_hash})
        return self.get(ident, kind)

    @staticmethod
    def decode(row):
        if not row:
            raise ValueError('record_not_found')
        return {**dict(row), 'data': json.loads(row['data'])}

    def get(self, ident, kind=None):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise ValueError('invalid_record_id')
        row = self.db.execute('SELECT * FROM media_mcp_record WHERE id=:id', {'id': ident}).mappings().first()
        value = self.decode(row)
        if kind and value['kind'] != kind:
            raise ValueError('record_kind_mismatch')
        return value

    def by_key(self, key):
        row = self.db.execute('SELECT * FROM media_mcp_record WHERE key_hash=:key', {'key': key}).mappings().first()
        return self.decode(row) if row else None

    def update(self, row, state, data=None):
        count = self.db.execute('''UPDATE media_mcp_record SET state=:state,data=:data,
            revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND revision=:revision''',
            {**row, 'state': state, 'data': json.dumps(data if data is not None else row['data'], ensure_ascii=False)}).rowcount
        if count != 1:
            raise RuntimeError('stale_job_revision')
        return self.get(row['id'])

    def list(self, kind, limit=30, after=''):
        rows = self.db.execute('''SELECT * FROM media_mcp_record WHERE kind=:kind AND id>:after
            ORDER BY id LIMIT :limit''', {'kind': kind, 'after': after, 'limit': min(max(limit, 1), 100)}).mappings().all()
        return [self.decode(row) for row in rows]

    def active(self, title_id=None):
        rows = self.db.execute("""SELECT * FROM media_mcp_record WHERE kind='acquisition'
            AND state NOT IN ('completed','completed_with_warnings','needs_review','failed','cancelled','deleted')
            AND (:title_id IS NULL OR json_extract(data,'$.identity.title_id')=:title_id)
            ORDER BY updated_at,id LIMIT 100""", {'title_id':title_id}).mappings().all()
        return [self.decode(row) for row in rows]

    def processing_context(self, delivery_hash):
        row = self.db.execute("""SELECT * FROM media_mcp_record WHERE kind='acquisition'
            AND json_extract(data,'$.delivery_hash')=:key LIMIT 1""",
            {'key':delivery_hash}).mappings().first()
        return self.decode(row)['data'] if row else None


def require_fresh(data):
    if data.get('expires_at', 0) <= time.time():
        raise ValueError('snapshot_expired_search_again')
