"""Small direct TMDB adapter. All credentials are deployment inputs."""
import os
import re
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
        key = os.environ.get('TMDB_API_KEY', '').strip()
        if not key:
            raise RuntimeError('tmdb_not_configured')
        try:
            response = self.session.get('https://api.themoviedb.org/3/' + path,
                params={'api_key': key, 'language': 'zh-CN', **params}, timeout=20,
                allow_redirects=False)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('tmdb_unavailable') from None

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

    def search(self, query, kind, year=None):
        params = {'query': query, 'include_adult': 'false'}
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
