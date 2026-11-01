"""Small direct TMDB adapter. All credentials are deployment inputs."""
import os
import re
import unicodedata
import time
import requests


class TMDB:
    def __init__(self, session=None, *, remote=True):
        self.session = session or requests.Session()
        self.remote = remote

    def get(self, path, **params):
        if os.environ.get('MEDIA_EXECUTION_ONLY') == 'true':
            raise ValueError('cloud_search_only')
        if self.remote:
            from media_mcp.platform.transport import provider_remote
            remote = provider_remote()
            if remote:
                return remote.call('/internal/provider', {'operation':'tmdb', 'arguments':{'path':path,'params':params}})
        try:
            return self.clean_titles(path, params, self._request(path, params))
        except (requests.RequestException, ValueError):
            raise RuntimeError('tmdb_unavailable') from None

    def _request(self, path, params, timeout=20):
        key = os.environ.get('TMDB_API_KEY', '').strip()
        if not key:
            raise RuntimeError('tmdb_not_configured')
        response = self.session.get('https://api.themoviedb.org/3/' + path,
            params={'api_key': key, 'language': 'zh-CN', **params}, timeout=timeout,
            allow_redirects=False)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def polluted_title(value):
        if not isinstance(value, str):
            return False
        text = unicodedata.normalize('NFKC', value).lower()
        text = re.sub(r'[\u200b-\u200d\ufeff]', '', text)
        domains = re.findall(r'(?:[a-z0-9-]+\.)+(?:com|net|org|cc|tv|xyz|top|vip)(?![a-z])', text)
        return bool(domains and (any(re.search(r'\d{5,}', domain) for domain in domains)
                    or re.search(r'\u6deb\u7247|\u9ec4\u6f2b|\u514d\u8d39\u89c2\u770b|\u5907\u7528\u7f51\u5740|\u52a0\u7fa4', text)))

    def clean_titles(self, path, params, payload):
        """Prefer clean Chinese alternatives by exact ID before original-language fallbacks."""
        fields = ('title', 'name', 'original_title', 'original_name')
        rows = payload.get('results', []) if isinstance(payload.get('results'), list) else [payload]
        chinese = params.get('language', 'zh-CN') in ('zh-CN', 'zh-TW', 'zh-HK')
        has_chinese = lambda value: isinstance(value, str) and bool(re.search(r'[\u3400-\u9fff]', value))
        primary = lambda row: 'title' if 'title' in row else 'name'
        damaged = lambda row: any(self.polluted_title(row.get(field)) for field in fields)
        needs_chinese = lambda row: chinese and not has_chinese(row.get(primary(row)))
        pending = [row for row in rows if damaged(row) or needs_chinese(row)]
        deadline = time.monotonic() + 24
        languages = ['zh-TW', 'zh-HK', 'en-US'] if chinese else []
        for language in languages:
            remaining = deadline - time.monotonic()
            if not pending or remaining <= 0:
                break
            if language == params.get('language'):
                continue
            if language == 'en-US' and not any(damaged(row) for row in pending):
                break
            try:
                translated = self._request(path, {**params, 'language': language}, min(8, remaining))
                candidates = translated.get('results', []) if isinstance(translated.get('results'), list) else [translated]
                matched = {row['id']: row for row in candidates if row.get('id') is not None}
            except (RuntimeError, requests.RequestException, ValueError):
                continue
            for row in pending:
                fallback = matched.get(row.get('id'), {})
                for field in fields:
                    repair = self.polluted_title(row.get(field))
                    localize = field == primary(row) and needs_chinese(row)
                    if not repair and not localize:
                        continue
                    choices = [fallback.get(field), fallback.get('title'), fallback.get('name')]
                    clean = [value for value in choices if isinstance(value, str) and value.strip()
                             and not self.polluted_title(value)]
                    preferred = [value for value in clean if has_chinese(value)] if localize else clean
                    if preferred or (repair or not row.get(field)) and clean:
                        row[field] = (preferred or clean)[0]
            pending = [row for row in pending if damaged(row) or needs_chinese(row)]
        for row in rows:
            for field in fields:
                if self.polluted_title(row.get(field)):
                    row[field] = next((row.get(name) for name in fields if isinstance(row.get(name), str)
                                       and row[name].strip() and not self.polluted_title(row[name])), None)
        if isinstance(payload.get('results'), list):
            payload['results'] = [row for row in rows if row.get('title') or row.get('name')]
        elif not (payload.get('title') or payload.get('name')):
            raise RuntimeError('tmdb_unavailable')
        return payload

    @staticmethod
    def identity(kind, row):
        poster = row.get('poster_path')
        return {'title_id': f"{kind}:{row['id']}", 'kind': kind, 'tmdb_id': row['id'],
                'title': row.get('title') or row.get('name'),
                'original_title': row.get('original_title') or row.get('original_name'),
                'date': row.get('release_date') or row.get('first_air_date') or None,
                'original_language': row.get('original_language'),
                'poster_url':'https://image.tmdb.org/t/p/w342'+poster
                    if isinstance(poster, str) and re.fullmatch(r'/[A-Za-z0-9_.-]+', poster) else None,
                'rating':row.get('vote_average'), 'rating_source':'TMDB'}

    def search(self, query, kind='all', year=None):
        params = {'query': query, 'include_adult': 'false'}
        if kind == 'all':
            return [self.identity(item['media_type'],item)
                    for item in self.get('search/multi',**params).get('results',[])
                    if item.get('media_type') in ('movie','tv')]
        if year:
            params['year' if kind == 'movie' else 'first_air_date_year'] = year
        return [self.identity(kind, item) for item in self.get('search/' + kind, **params).get('results', [])]

    def detail(self, title_id):
        from media_mcp.config import parse_title_id
        kind, ident = parse_title_id(title_id)
        row = self.get(f'{kind}/{ident}')
        result = self.identity(kind, row)
        if row.get('original_language') and row['original_language'] != 'en':
            try:
                english = self.get(f'{kind}/{ident}', language='en-US')
                title = english.get('title') or english.get('name')
                if english.get('id') == ident and isinstance(title, str) and title.strip():
                    result['english_title'] = title[:200]
            except RuntimeError:
                # An unavailable translation must not hide the original identity.
                pass
        return result
