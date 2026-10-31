"""Bounded discovery providers with explicit source identity and stale-cache reporting."""
import json
import os
import re
import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from media_mcp.adapters.tmdb import TMDB


class Catalog:
    def __init__(self, db, tmdb=None, session=None, clock=time.time):
        self.db, self.tmdb = db, tmdb or TMDB()
        self.session, self.clock = session or requests.Session(), clock
        self.lock = threading.Lock()
        db.execute('''CREATE TABLE IF NOT EXISTS platform_catalog_cache (
            key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at REAL NOT NULL,
            attempted_at REAL NOT NULL DEFAULT 0, error_code TEXT, source_updated_at REAL)''')
        with db.lock('catalog-schema', timeout=30):
            if not db.column_exists('platform_catalog_cache', 'source_updated_at'):
                db.execute('ALTER TABLE platform_catalog_cache ADD COLUMN source_updated_at REAL')

    @staticmethod
    def tmdb_item(kind, row):
        poster = row.get('poster_path')
        return {**TMDB.identity(kind, row), 'overview':row.get('overview', ''),
                'poster_url':'https://image.tmdb.org/t/p/w342'+poster
                    if isinstance(poster, str) and re.fullmatch(r'/[A-Za-z0-9_.-]+', poster) else None,
                'rating':row.get('vote_average'), 'rating_source':'TMDB', 'source':'tmdb'}

    def detail(self, title_id):
        from media_mcp.config import parse_title_id
        kind, ident = parse_title_id(title_id)
        key = 'detail:'+title_id
        with self.lock:
            now = self.clock()
            cached = self.db.execute('SELECT * FROM platform_catalog_cache WHERE key=:key',
                                     {'key':key}).mappings().first()
            if cached and (now-cached['fetched_at'] < 86400 or
                           cached['error_code'] and now-cached['attempted_at'] < 300):
                return json.loads(cached['payload'])
            try:
                row = self.tmdb.get(f'{kind}/{ident}')
                if row.get('id') != ident:raise ValueError('provider_identity_mismatch')
                result = {**self.tmdb_item(kind, row), 'genres':[g['name'] for g in row.get('genres', [])],
                          'seasons':[{'season':s['season_number'], 'name':s.get('name'),
                                      'episodes':s.get('episode_count')} for s in row.get('seasons', [])
                                     if type(s.get('season_number')) is int and 0 <= s['season_number'] <= 99]}
            except (RuntimeError, requests.RequestException):
                if cached:
                    self.db.execute('UPDATE platform_catalog_cache SET attempted_at=:now,error_code=:error WHERE key=:key',
                                    {'now':now,'error':'tmdb_unavailable','key':key})
                    return json.loads(cached['payload'])
                raise
            self.db.execute('''INSERT INTO platform_catalog_cache(key,payload,fetched_at,attempted_at)
                VALUES(:key,:payload,:now,:now) ON CONFLICT(key) DO UPDATE SET
                payload=excluded.payload,fetched_at=excluded.fetched_at,attempted_at=excluded.attempted_at,error_code=NULL''',
                {'key':key,'payload':json.dumps(result,ensure_ascii=False),'now':now})
            return result

    def discover(self, source='tmdb', kind='movie', window='week'):
        if source not in ('tmdb', 'douban', 'simkl') or kind not in ('movie', 'tv') or window not in ('day', 'week','top') or window=='top' and source!='tmdb':
            raise ValueError('invalid_catalog_request')
        key = f'{source}:{kind}:{window}'
        with self.lock:
            now = self.clock()
            cached = self.db.execute('SELECT * FROM platform_catalog_cache WHERE key=:key',
                                      {'key':key}).mappings().first()
            ttl = 3600 if source == 'simkl' else 10800
            if cached and ((not cached['error_code'] and now-cached['fetched_at'] < ttl)
                           or now-cached['attempted_at'] < 300):
                return self._response(source, cached)
            error = None
            updated = cached['source_updated_at'] if cached else None
            try:
                if source == 'tmdb':
                    raw = self.tmdb.get(f'{kind}/top_rated' if window=='top' else f'trending/{kind}/{window}').get('results', [])
                    items = [self.tmdb_item(kind, item) for item in raw[:40]]
                elif source == 'simkl':
                    items, updated = self._simkl(kind, window, now)
                else:
                    items = self._douban(kind)
                if not items:
                    raise RuntimeError('catalog_empty_response')
            except Exception as exc:
                candidate = str(exc)
                error = candidate if candidate in ('douban_unavailable', 'douban_invalid_response',
                    'tmdb_not_configured', 'tmdb_unavailable', 'catalog_empty_response',
                    'simkl_unavailable', 'simkl_invalid_response', 'simkl_outdated') else 'catalog_unavailable'
                items = json.loads(cached['payload']) if cached else []
                updated = cached['source_updated_at'] if cached else None
            fetched = now if not error else (cached['fetched_at'] if cached else 0)
            self.db.execute('''INSERT INTO platform_catalog_cache(key,payload,fetched_at,attempted_at,error_code,source_updated_at)
                VALUES(:key,:payload,:fetched,:attempted,:error,:updated) ON CONFLICT(key) DO UPDATE SET
                payload=excluded.payload,fetched_at=excluded.fetched_at,attempted_at=excluded.attempted_at,
                error_code=excluded.error_code,source_updated_at=excluded.source_updated_at''',
                {'key':key, 'payload':json.dumps(items, ensure_ascii=False),
                'fetched':fetched, 'attempted':now, 'error':error, 'updated':updated})
            return self._response(source, {'payload':json.dumps(items), 'fetched_at':fetched,
                                          'error_code':error, 'source_updated_at':updated})

    def _response(self, source, row):
        return {'source':source, 'items':json.loads(row['payload']), 'fetched_at':row['fetched_at'] or None,
                'source_updated_at':row['source_updated_at'],
                'stale':bool(row['error_code']), 'error_code':row['error_code'],
                'status':'stale' if row['error_code'] and row['fetched_at'] else (
                    'unavailable' if row['error_code'] else 'ready')}

    def _simkl(self, kind, window, now):
        category = 'movies' if kind == 'movie' else 'tv'
        period = 'today' if window == 'day' else 'week'
        url = f'https://data.simkl.in/discover/trending/{category}/{period}_100.json'
        try:
            with self.session.get(url, headers={'User-Agent':'MediaMCP/0.3 (self-hosted media catalog)'},
                                  timeout=15, stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError('simkl_unavailable')
                modified = parsedate_to_datetime(response.headers.get('Last-Modified', ''))
                if modified.tzinfo is None:
                    raise ValueError('missing_timezone')
                updated = modified.timestamp()
                if not now-172800 <= updated <= now+3600:
                    raise RuntimeError('simkl_outdated')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2*1024*1024:
                        raise RuntimeError('simkl_invalid_response')
                    chunks.append(chunk)
                rows = json.loads(b''.join(chunks))
        except requests.RequestException:
            raise RuntimeError('simkl_unavailable') from None
        except (ValueError, TypeError, OverflowError):
            raise RuntimeError('simkl_invalid_response') from None
        if not isinstance(rows, list):
            raise RuntimeError('simkl_invalid_response')
        items = []
        for rank, row in enumerate(rows[:40], 1):
            if not isinstance(row, dict) or not isinstance(row.get('title'), str) or not row['title'].strip():
                continue
            ids = row.get('ids')
            if not isinstance(ids, dict) or not re.fullmatch(r'[1-9][0-9]{0,15}', str(ids.get('simkl_id', ''))):
                continue
            tmdb = str(ids.get('tmdb', ''))
            title_id = f'{kind}:{tmdb}' if re.fullmatch(r'[1-9][0-9]{0,11}', tmdb) else None
            poster = row.get('poster')
            poster_url = ('https://wsrv.nl/?url=https://simkl.in/posters/'+poster+'_m.webp&q=90'
                if isinstance(poster, str) and re.fullmatch(r'[0-9]{1,4}/[A-Za-z0-9]{1,64}', poster) else None)
            try:
                date = datetime.strptime(row.get('release_date', ''), '%m/%d/%Y').date().isoformat()
            except (ValueError, TypeError):
                date = None
            ratings = row.get('ratings')
            rating = ratings.get('simkl', {}).get('rating') if isinstance(ratings, dict) and isinstance(ratings.get('simkl'), dict) else None
            if type(rating) not in (int, float) or not 0 <= rating <= 10:
                rating = None
            items.append({'source':'simkl', 'source_id':str(ids['simkl_id']), 'title':row['title'][:200],
                'original_title':row['title'][:200], 'kind':kind, 'title_id':title_id, 'date':date,
                'poster_url':poster_url, 'rating':rating, 'rating_source':'SIMKL', 'rank':rank,
                'source_url':f"https://simkl.com/{category}/{ids['simkl_id']}",
                'requires_identity_match':title_id is None})
        return items, updated

    def _douban(self, kind):
        # A configured provider must implement the same subjects response contract.
        # No cookie harvesting, login emulation or challenge bypass is performed.
        endpoint = os.environ.get('MEDIA_DOUBAN_ENDPOINT') or 'https://movie.douban.com/j/search_subjects'
        try:
            with self.session.get(endpoint, params={'type':kind, 'tag':'热门', 'page_limit':40, 'page_start':0},
                    timeout=12, stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError('douban_unavailable')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2*1024*1024:
                        raise RuntimeError('douban_invalid_response')
                    chunks.append(chunk)
                raw = json.loads(b''.join(chunks))
        except (requests.RequestException, ValueError):
            raise RuntimeError('douban_unavailable') from None
        if not isinstance(raw, dict) or not isinstance(raw.get('subjects'), list):
            raise RuntimeError('douban_invalid_response')
        items = []
        for row in raw['subjects'][:40]:
            if not isinstance(row, dict) or not re.fullmatch(r'[0-9]{1,16}', str(row.get('id', ''))):
                continue
            title = row.get('title')
            if not isinstance(title, str) or not title.strip():
                continue
            cover = row.get('cover', '')
            if not isinstance(cover, str) or not re.match(r'^https://[A-Za-z0-9.-]+\.doubanio\.com/', cover):
                cover = None
            items.append({'source':'douban', 'source_id':str(row['id']), 'title':title[:200], 'kind':kind,
                'title_id':None, 'poster_url':cover, 'rating':str(row.get('rate', ''))[:12],
                'rating_source':'豆瓣', 'source_url':f"https://movie.douban.com/subject/{row['id']}/",
                'requires_identity_match':True})
        return items
