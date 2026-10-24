#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite-backed media store used by the media agent and TMDB helpers.

Backed by the local SQLite DatabaseClient (SQLAlchemy). Public function signatures and return shapes are
unchanged: every function takes ``db_name`` first, reads return plain dicts.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text

from .client import DatabaseClient

MEDIA_DB = os.environ.get('MEDIA_DB_NAME') or 'media'

# Cache one client+schema-ensure per resolved db name (DatabaseClient pools its
# own connections, so this just avoids re-running the DDL on every call).
_clients: dict[str, DatabaseClient] = {}


def _client(db_name: str | None) -> DatabaseClient:
    from .client import database_path
    name = str(database_path())
    client = _clients.get(name)
    if client is None:
        client = DatabaseClient(db_name=name,connect_timeout_seconds=5,read_timeout_seconds=15)
        with client.lock('schema',timeout=10):
            _init_schema(client)
        _clients[name] = client
    return client


def _utc_now() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _file_stat(path: Optional[str]) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {'exists': 0, 'size': None, 'inode': None, 'device':None, 'modified_ns':None}
    st = os.stat(path)
    return {'exists': 1, 'size': st.st_size, 'inode': getattr(st, 'st_ino', None), 'device':st.st_dev, 'modified_ns':st.st_mtime_ns}


def _path_hash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _init_schema(db: DatabaseClient) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS media_link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path_hash CHAR(64) NOT NULL,
            target_path_hash CHAR(64) NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            filename VARCHAR(512),
            source_exists INTEGER NOT NULL DEFAULT 1,
            target_exists INTEGER NOT NULL DEFAULT 1,
            media_type VARCHAR(32),
            media_tmdb_id BIGINT,
            season_tmdb_id BIGINT,
            episode_tmdb_id BIGINT,
            title_guess VARCHAR(512),
            media_name VARCHAR(512),
            base_title VARCHAR(512),
            alt_name VARCHAR(512),
            original_language VARCHAR(32),
            origin_country VARCHAR(64),
            year INT,
            season INT,
            episode INT,
            extra_type VARCHAR(32),
            extra_index INT,
            extension VARCHAR(32),
            confidence REAL,
            status VARCHAR(64) NOT NULL DEFAULT 'linked',
            fail_stage VARCHAR(255),
            reason TEXT,
            agent_payload_json TEXT,
            agent_result_json TEXT,
            source_size BIGINT,
            target_size BIGINT,
            source_inode BIGINT,
            target_inode BIGINT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uniq_media_link_source_hash UNIQUE (source_path_hash)
        )""",
        """CREATE INDEX IF NOT EXISTS idx_media_link_source_hash ON media_link (source_path_hash)""",
        """CREATE INDEX IF NOT EXISTS idx_media_link_target_hash ON media_link (target_path_hash)""",
        """CREATE INDEX IF NOT EXISTS idx_media_link_status ON media_link (status)""",
        """CREATE INDEX IF NOT EXISTS idx_media_link_tmdb ON media_link (media_type, media_tmdb_id)""",
        """CREATE TABLE IF NOT EXISTS tmdb_cache (
            cache_key VARCHAR(255) PRIMARY KEY,
            lookup_kind VARCHAR(64) NOT NULL,
            media_type VARCHAR(32),
            tmdb_id BIGINT,
            season INT,
            episode INT,
            query VARCHAR(512),
            year INT,
            language VARCHAR(32),
            region VARCHAR(32),
            request_json TEXT,
            response_json TEXT NOT NULL,
            normalized_json TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_tmdb_cache_lookup_kind ON tmdb_cache (lookup_kind)""",
        """CREATE INDEX IF NOT EXISTS idx_tmdb_cache_tmdb ON tmdb_cache (media_type, tmdb_id)""",
        """CREATE INDEX IF NOT EXISTS idx_tmdb_cache_query ON tmdb_cache (media_type, query, year)""",
        """CREATE INDEX IF NOT EXISTS idx_tmdb_cache_episode ON tmdb_cache (media_type, tmdb_id, season, episode)""",
        """CREATE TABLE IF NOT EXISTS media_subtitle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_subtitle_path_hash CHAR(64) NOT NULL,
            target_subtitle_path_hash CHAR(64) NOT NULL,
            source_subtitle_path TEXT NOT NULL,
            target_subtitle_path TEXT NOT NULL,
            matched_video_source_path TEXT,
            matched_video_target_path TEXT NOT NULL,
            source_type VARCHAR(32),
            stream_index INT,
            codec VARCHAR(64),
            media_type VARCHAR(32),
            media_tmdb_id BIGINT,
            season INT,
            episode INT,
            language VARCHAR(64),
            subtitle_type VARCHAR(64),
            format VARCHAR(32),
            confidence REAL,
            status VARCHAR(64) NOT NULL,
            reason TEXT,
            source_size BIGINT,
            target_size BIGINT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uniq_media_subtitle_source_target_hash UNIQUE (source_subtitle_path_hash, target_subtitle_path_hash)
        )""",
        """CREATE INDEX IF NOT EXISTS idx_media_subtitle_target_hash ON media_subtitle (target_subtitle_path_hash)""",
        """CREATE INDEX IF NOT EXISTS idx_media_subtitle_video_target ON media_subtitle (matched_video_target_path)""",
        """CREATE INDEX IF NOT EXISTS idx_media_subtitle_status ON media_subtitle (status)""",
        """CREATE INDEX IF NOT EXISTS idx_media_subtitle_language ON media_subtitle (language)""",
    ]
    for statement in statements:
        db.execute(statement)


def upsert_media_link(db_name: str, source_path: str, target_path: str, **kwargs):
    now = _utc_now()
    src = _file_stat(source_path)
    dst = _file_stat(target_path)
    payload = _json_object(kwargs.get('agent_result_json'))
    payload['_source_fingerprint'] = [src['device'],src['inode'],src['size'],src['modified_ns']] if src['exists'] else None
    kwargs['agent_result_json'] = json.dumps(payload,ensure_ascii=False)
    connection = kwargs.pop('_connection', None)
    execute = (lambda sql, params: connection.execute(text(sql), params)) if connection is not None else _client(db_name).execute
    execute(
        """
        INSERT INTO media_link (
            source_path_hash, target_path_hash, source_path, target_path, filename,
            source_exists, target_exists,
            media_type, media_tmdb_id, season_tmdb_id, episode_tmdb_id,
            title_guess, media_name, base_title, alt_name, original_language, origin_country,
            year, season, episode, extra_type, extra_index, extension, confidence, status, fail_stage, reason,
            agent_payload_json, agent_result_json,
            source_size, target_size, source_inode, target_inode,
            created_at, updated_at
        ) VALUES (
            :source_path_hash, :target_path_hash, :source_path, :target_path, :filename,
            :source_exists, :target_exists,
            :media_type, :media_tmdb_id, :season_tmdb_id, :episode_tmdb_id,
            :title_guess, :media_name, :base_title, :alt_name, :original_language, :origin_country,
            :year, :season, :episode, :extra_type, :extra_index, :extension, :confidence, :status, :fail_stage, :reason,
            :agent_payload_json, :agent_result_json,
            :source_size, :target_size, :source_inode, :target_inode,
            :created_at, :updated_at
        )
        ON CONFLICT(source_path_hash) DO UPDATE SET
            source_path=excluded.source_path,
            target_path=excluded.target_path,
            target_path_hash=excluded.target_path_hash,
            filename=excluded.filename,
            source_exists=excluded.source_exists,
            target_exists=excluded.target_exists,
            media_type=excluded.media_type,
            media_tmdb_id=excluded.media_tmdb_id,
            season_tmdb_id=excluded.season_tmdb_id,
            episode_tmdb_id=excluded.episode_tmdb_id,
            title_guess=excluded.title_guess,
            media_name=excluded.media_name,
            base_title=excluded.base_title,
            alt_name=excluded.alt_name,
            original_language=excluded.original_language,
            origin_country=excluded.origin_country,
            year=excluded.year,
            season=excluded.season,
            episode=excluded.episode,
            extra_type=excluded.extra_type,
            extra_index=excluded.extra_index,
            extension=excluded.extension,
            confidence=excluded.confidence,
            status=excluded.status,
            fail_stage=excluded.fail_stage,
            reason=excluded.reason,
            agent_payload_json=excluded.agent_payload_json,
            agent_result_json=excluded.agent_result_json,
            source_size=excluded.source_size,
            target_size=excluded.target_size,
            source_inode=excluded.source_inode,
            target_inode=excluded.target_inode,
            updated_at=excluded.updated_at
        """,
        {
            'source_path_hash': _path_hash(source_path),
            'target_path_hash': _path_hash(target_path) or hashlib.sha256(b'').hexdigest(),
            'source_path': source_path,
            'target_path': target_path,
            'filename': kwargs.get('filename') or os.path.basename(source_path or ''),
            'source_exists': src['exists'],
            'target_exists': dst['exists'],
            'media_type': kwargs.get('media_type'),
            'media_tmdb_id': kwargs.get('media_tmdb_id'),
            'season_tmdb_id': kwargs.get('season_tmdb_id'),
            'episode_tmdb_id': kwargs.get('episode_tmdb_id'),
            'title_guess': kwargs.get('title_guess'),
            'media_name': kwargs.get('media_name'),
            'base_title': kwargs.get('base_title'),
            'alt_name': kwargs.get('alt_name'),
            'original_language': kwargs.get('original_language'),
            'origin_country': kwargs.get('origin_country'),
            'year': kwargs.get('year'),
            'season': kwargs.get('season'),
            'episode': kwargs.get('episode'),
            'extra_type': kwargs.get('extra_type'),
            'extra_index': kwargs.get('extra_index'),
            'extension': kwargs.get('extension'),
            'confidence': kwargs.get('confidence'),
            'status': kwargs.get('status', 'linked'),
            'fail_stage': kwargs.get('fail_stage'),
            'reason': kwargs.get('reason'),
            'agent_payload_json': kwargs.get('agent_payload_json'),
            'agent_result_json': kwargs.get('agent_result_json'),
            'source_size': src['size'],
            'target_size': dst['size'],
            'source_inode': src['inode'],
            'target_inode': dst['inode'],
            'created_at': now,
            'updated_at': now,
        },
    )


def _get_media_link(db_name: str, hash_column: str, path_column: str, value: str):
    row = _client(db_name).execute(
        f"SELECT * FROM media_link WHERE {hash_column} = :hash AND {path_column} = :value ORDER BY updated_at DESC LIMIT 1",
        {'hash': _path_hash(value), 'value': value},
    ).fetchone()
    return dict(row._mapping) if row is not None else None


def get_media_link_by_source(db_name: str, source_path: str):
    return _get_media_link(db_name, 'source_path_hash', 'source_path', source_path)


def get_media_link_by_target(db_name: str, target_path: str):
    return _get_media_link(db_name, 'target_path_hash', 'target_path', target_path)


def get_canonical_media_title(db_name: str, media_type: str, media_tmdb_id: int):
    if media_tmdb_id is None:
        return None
    row = _client(db_name).execute(
        """
        SELECT media_name, base_title, alt_name, target_path, updated_at
          FROM media_link
         WHERE media_type = :media_type AND media_tmdb_id = :media_tmdb_id
           AND base_title IS NOT NULL AND base_title != ''
         ORDER BY CASE WHEN status = 'linked' THEN 0 ELSE 1 END, updated_at ASC
         LIMIT 1
        """,
        {'media_type': media_type, 'media_tmdb_id': media_tmdb_id},
    ).fetchone()
    return dict(row._mapping) if row is not None else None


def get_tmdb_cache(db_name: str, lookup_kind: str, cache_key: str):
    row = _client(db_name).execute(
        """
        SELECT cache_key, lookup_kind, media_type, tmdb_id, season, episode, query, year,
               language, region, request_json, response_json, normalized_json,
               created_at, updated_at
          FROM tmdb_cache
         WHERE lookup_kind = :lookup_kind AND cache_key = :cache_key
        """,
        {'lookup_kind': lookup_kind, 'cache_key': cache_key},
    ).fetchone()
    if row is None:
        return None
    row = dict(row._mapping)
    row['request'] = json.loads(row['request_json']) if row.get('request_json') else None
    row['response'] = json.loads(row['response_json']) if row.get('response_json') else None
    row['normalized'] = json.loads(row['normalized_json']) if row.get('normalized_json') else None
    return row


def upsert_tmdb_cache(
    db_name: str,
    lookup_kind: str,
    cache_key: str,
    response: dict,
    request: dict | None = None,
    normalized: dict | None = None,
    **kwargs,
):
    now = _utc_now()
    _client(db_name).execute(
        """
        INSERT INTO tmdb_cache (
            cache_key, lookup_kind, media_type, tmdb_id, season, episode, query, year,
            language, region, request_json, response_json, normalized_json,
            created_at, updated_at
        ) VALUES (
            :cache_key, :lookup_kind, :media_type, :tmdb_id, :season, :episode, :query, :year,
            :language, :region, :request_json, :response_json, :normalized_json,
            :created_at, :updated_at
        )
        ON CONFLICT(cache_key) DO UPDATE SET
            lookup_kind=excluded.lookup_kind,
            media_type=excluded.media_type,
            tmdb_id=excluded.tmdb_id,
            season=excluded.season,
            episode=excluded.episode,
            query=excluded.query,
            year=excluded.year,
            language=excluded.language,
            region=excluded.region,
            request_json=excluded.request_json,
            response_json=excluded.response_json,
            normalized_json=excluded.normalized_json,
            updated_at=excluded.updated_at
        """,
        {
            'cache_key': cache_key,
            'lookup_kind': lookup_kind,
            'media_type': kwargs.get('media_type'),
            'tmdb_id': kwargs.get('tmdb_id'),
            'season': kwargs.get('season'),
            'episode': kwargs.get('episode'),
            'query': kwargs.get('query'),
            'year': kwargs.get('year'),
            'language': kwargs.get('language'),
            'region': kwargs.get('region'),
            'request_json': json.dumps(request, ensure_ascii=False) if request is not None else None,
            'response_json': json.dumps(response, ensure_ascii=False),
            'normalized_json': json.dumps(normalized, ensure_ascii=False) if normalized is not None else None,
            'created_at': now,
            'updated_at': now,
        },
    )


def list_media_links(db_name: str, limit: int = 200):
    rows = _client(db_name).execute(
        "SELECT source_path, target_path, media_type, media_name, confidence, status, updated_at FROM media_link ORDER BY updated_at DESC LIMIT :limit",
        {'limit': limit},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def list_media_links_by_keyword(db_name: str, keyword: str) -> list[dict[str, Any]]:
    rows = _client(db_name).execute(
        """
        SELECT id, source_path, target_path, media_type, media_tmdb_id, media_name, base_title,
               alt_name, original_language, origin_country, season, episode, status,
               agent_payload_json, agent_result_json
          FROM media_link
         WHERE source_path LIKE :kw ESCAPE '=' OR target_path LIKE :kw ESCAPE '=' OR media_name LIKE :kw ESCAPE '=' OR base_title LIKE :kw ESCAPE '=' OR alt_name LIKE :kw ESCAPE '='
         ORDER BY updated_at DESC, id DESC
        """,
        {'kw':'%'+str(keyword).replace('=','==').replace('%','=%').replace('_','=_')+'%'},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def list_media_links_by_source_prefix(db_name: str, source_prefix: str) -> list[dict[str, Any]]:
    prefix = source_prefix.rstrip('/')
    rows = _client(db_name).execute(
        """
        SELECT id, source_path, target_path, media_type, media_tmdb_id,
               media_name, base_title, alt_name, original_language, origin_country,
               year, season, episode, extension, confidence, status,
               agent_payload_json, agent_result_json
         FROM media_link
         WHERE (source_path = :source_prefix OR source_path LIKE :source_like)
           AND status IN ('linked', 'source_missing', 'target_missing')
         ORDER BY media_type, season, episode, updated_at DESC, id DESC
        """,
        {'source_prefix': prefix, 'source_like': f'{prefix}/%'},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def list_media_links_by_target_prefix(db_name: str, target_prefix: str) -> list[dict[str, Any]]:
    prefix = target_prefix.rstrip('/')
    rows = _client(db_name).execute(
        """
        SELECT id, source_path, target_path, media_type, media_tmdb_id,
               media_name, base_title, alt_name, original_language, origin_country,
               year, season, episode, extension, confidence, status,
               agent_payload_json, agent_result_json
         FROM media_link
         WHERE (target_path = :target_prefix OR target_path LIKE :target_like)
           AND status IN ('linked', 'source_missing', 'target_missing')
         ORDER BY media_type, season, episode, updated_at DESC, id DESC
        """,
        {'target_prefix': prefix, 'target_like': f'{prefix}/%'},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def delete_media_links_by_ids(db_name: str, ids: list[int]) -> int:
    if not ids:
        return 0
    if len(ids)>10000 or any(type(value) is not int or value<=0 for value in ids):
        raise ValueError('invalid_media_link_ids')
    params = {f'id_{index}':value for index,value in enumerate(ids)}
    placeholders = ','.join(':'+key for key in params)
    return int(_client(db_name).execute(f'DELETE FROM media_link WHERE id IN ({placeholders})',params).rowcount or 0)


def delete_media_links_by_keyword(db_name: str, keyword: str) -> int:
    return _client(db_name).execute(
        "DELETE FROM media_link WHERE source_path LIKE :kw ESCAPE '=' OR target_path LIKE :kw ESCAPE '=' OR media_name LIKE :kw ESCAPE '=' OR base_title LIKE :kw ESCAPE '=' OR alt_name LIKE :kw ESCAPE '='",
        {'kw':'%'+str(keyword).replace('=','==').replace('%','=%').replace('_','=_')+'%'},
    ).rowcount


def upsert_media_subtitle(db_name: str, source_subtitle_path: str, target_subtitle_path: str, **kwargs):
    now = _utc_now()
    src = _file_stat(source_subtitle_path.split('#', 1)[0] if source_subtitle_path else None)
    dst = _file_stat(target_subtitle_path.split('#', 1)[0] if target_subtitle_path else None)
    _client(db_name).execute(
        """
        INSERT INTO media_subtitle (
            source_subtitle_path_hash, target_subtitle_path_hash,
            source_subtitle_path, target_subtitle_path,
            matched_video_source_path, matched_video_target_path,
            source_type, stream_index, codec,
            media_type, media_tmdb_id, season, episode,
            language, subtitle_type, format, confidence, status, reason,
            source_size, target_size, created_at, updated_at
        ) VALUES (
            :source_subtitle_path_hash, :target_subtitle_path_hash,
            :source_subtitle_path, :target_subtitle_path,
            :matched_video_source_path, :matched_video_target_path,
            :source_type, :stream_index, :codec,
            :media_type, :media_tmdb_id, :season, :episode,
            :language, :subtitle_type, :format, :confidence, :status, :reason,
            :source_size, :target_size, :created_at, :updated_at
        )
        ON CONFLICT(source_subtitle_path_hash,target_subtitle_path_hash) DO UPDATE SET
            source_subtitle_path=excluded.source_subtitle_path,
            target_subtitle_path=excluded.target_subtitle_path,
            matched_video_source_path=excluded.matched_video_source_path,
            matched_video_target_path=excluded.matched_video_target_path,
            source_type=excluded.source_type,
            stream_index=excluded.stream_index,
            codec=excluded.codec,
            media_type=excluded.media_type,
            media_tmdb_id=excluded.media_tmdb_id,
            season=excluded.season,
            episode=excluded.episode,
            language=excluded.language,
            subtitle_type=excluded.subtitle_type,
            format=excluded.format,
            confidence=excluded.confidence,
            status=excluded.status,
            reason=excluded.reason,
            source_size=excluded.source_size,
            target_size=excluded.target_size,
            updated_at=excluded.updated_at
        """,
        {
            'source_subtitle_path_hash': _path_hash(source_subtitle_path),
            'target_subtitle_path_hash': _path_hash(target_subtitle_path),
            'source_subtitle_path': source_subtitle_path,
            'target_subtitle_path': target_subtitle_path,
            'matched_video_source_path': kwargs.get('matched_video_source_path'),
            'matched_video_target_path': kwargs.get('matched_video_target_path'),
            'source_type': kwargs.get('source_type'),
            'stream_index': kwargs.get('stream_index'),
            'codec': kwargs.get('codec'),
            'media_type': kwargs.get('media_type'),
            'media_tmdb_id': kwargs.get('media_tmdb_id'),
            'season': kwargs.get('season'),
            'episode': kwargs.get('episode'),
            'language': kwargs.get('language'),
            'subtitle_type': kwargs.get('subtitle_type'),
            'format': kwargs.get('format'),
            'confidence': kwargs.get('confidence'),
            'status': kwargs.get('status', 'linked'),
            'reason': kwargs.get('reason'),
            'source_size': src['size'],
            'target_size': dst['size'],
            'created_at': now,
            'updated_at': now,
        },
    )


def list_media_subtitles_by_video(db_name: str, matched_video_target_path: str) -> list[dict[str, Any]]:
    rows = _client(db_name).execute(
        """
        SELECT *
          FROM media_subtitle
         WHERE matched_video_target_path = :target_path
         ORDER BY updated_at DESC, id DESC
        """,
        {'target_path': matched_video_target_path},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def refresh_media_link_status(db_name: str, source_path: str = None, target_path: str = None) -> int:
    where = []
    params: dict[str, Any] = {}
    if source_path:
        where.append("source_path_hash = :src_hash AND source_path = :src_path")
        params['src_hash'] = _path_hash(source_path)
        params['src_path'] = source_path
    if target_path:
        where.append("target_path_hash = :dst_hash AND target_path = :dst_path")
        params['dst_hash'] = _path_hash(target_path)
        params['dst_path'] = target_path
    where.append("status NOT IN ('failed', 'needs_review')")
    sql = "SELECT * FROM media_link"
    if where:
        sql += " WHERE " + " AND ".join(where)

    now = _utc_now()
    updated = 0
    # Read-then-conditional-writes must commit together.
    with _client(db_name).begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        for row in rows:
            src = _file_stat(row['source_path'])
            dst = _file_stat(row['target_path'])
            if src['exists'] and dst['exists'] and src['inode'] is not None and src['inode'] == dst['inode']:
                status = 'linked'
                reason = None
            elif src['exists'] and not dst['exists']:
                status = 'target_missing'
                reason = 'target file missing'
            elif not src['exists'] and dst['exists']:
                status = 'source_missing'
                reason = 'source file missing'
            else:
                status = 'broken'
                reason = 'source and target missing or inode mismatch'

            conn.execute(
                text(
                    """
                    UPDATE media_link
                       SET source_exists = :source_exists, target_exists = :target_exists,
                           source_size = :source_size, target_size = :target_size,
                           source_inode = :source_inode, target_inode = :target_inode,
                           status = :status, reason = :reason, updated_at = :updated_at
                     WHERE id = :id
                    """
                ),
                {
                    'source_exists': src['exists'],
                    'target_exists': dst['exists'],
                    'source_size': src['size'],
                    'target_size': dst['size'],
                    'source_inode': src['inode'],
                    'target_inode': dst['inode'],
                    'status': status,
                    'reason': reason,
                    'updated_at': now,
                    'id': row['id'],
                },
            )
            updated += 1
    return updated


def add_failed_case(db_name: str, source_path: str, filename: str = None,
                    parsed_json: str = None, result_json: str = None,
                    fail_stage: str = None, reason: str = None):
    source = source_path or filename or 'unknown'
    existing = get_media_link_by_source(db_name, source)
    parsed = _json_object(parsed_json)
    result = _json_object(result_json)
    is_subtitle_failure = str(fail_stage or '').startswith('subtitle_')
    review_stages = ('validate', 'codex_validate', 'low_confidence')

    if existing:
        if is_subtitle_failure:
            status = existing.get('status') or 'linked'
        elif str(fail_stage or '').startswith(review_stages):
            status = 'needs_review'
        else:
            status = 'failed'
        _client(db_name).execute(
            """
            UPDATE media_link
               SET filename = :filename,
                   status = :status,
                   fail_stage = :fail_stage,
                   reason = :reason,
                   agent_payload_json = COALESCE(:parsed_json, agent_payload_json),
                   agent_result_json = COALESCE(:result_json, agent_result_json),
                   updated_at = :updated_at
             WHERE id = :id
            """,
            {
                'filename': filename or existing.get('filename') or os.path.basename(source),
                'status': status,
                'fail_stage': fail_stage,
                'reason': reason,
                'parsed_json': parsed_json,
                'result_json': result_json,
                'updated_at': _utc_now(),
                'id': existing.get('id'),
            },
        )
        return

    target = (
        result.get('hardlink_path')
        or result.get('target_path')
        or result.get('matched_video_target_path')
        or source
    )
    title = result.get('title') if isinstance(result.get('title'), dict) else {}
    status = 'needs_review' if str(fail_stage or '').startswith(review_stages) else 'failed'
    upsert_media_link(
        db_name,
        source,
        target,
        filename=filename or os.path.basename(source),
        media_type=result.get('kind') or result.get('media_type') or parsed.get('media_type'),
        media_tmdb_id=result.get('tmdb_id') or result.get('media_tmdb_id'),
        title_guess=parsed.get('title_guess'),
        media_name=result.get('media_name') or title.get('zh'),
        base_title=result.get('base_title') or title.get('base'),
        alt_name=result.get('alt_name') or title.get('original'),
        original_language=result.get('original_language'),
        origin_country=result.get('origin_country'),
        year=result.get('year') or parsed.get('year'),
        season=result.get('season') or parsed.get('season'),
        episode=result.get('episode') or parsed.get('episode'),
        extra_type=result.get('extra_type') or parsed.get('extra_type'),
        extra_index=result.get('extra_index') or parsed.get('extra_index'),
        extension=parsed.get('extension') or os.path.splitext(source)[1],
        confidence=result.get('confidence'),
        status=status,
        fail_stage=fail_stage,
        reason=reason,
        agent_payload_json=parsed_json,
        agent_result_json=result_json,
    )


def list_failed_cases(db_name: str, limit: int = 200, since: str = None):
    sql = """
        SELECT source_path, filename, fail_stage, reason, created_at
          FROM media_link
         WHERE (status IN ('failed', 'needs_review') OR fail_stage IS NOT NULL)
    """
    params: dict[str, Any] = {}
    if since:
        sql += " AND updated_at >= :since"
        params['since'] = since
    sql += " ORDER BY updated_at DESC, id DESC LIMIT :limit"
    params['limit'] = limit
    rows = _client(db_name).execute(sql, params).fetchall()
    return [dict(r._mapping) for r in rows]
