"""Small direct TMDB adapter. All credentials are deployment inputs."""
import os
import requests


class TMDB:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def get(self, path, **params):
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
        return {'title_id': f"{kind}:{row['id']}", 'kind': kind, 'tmdb_id': row['id'],
                'title': row.get('title') or row.get('name'),
                'original_title': row.get('original_title') or row.get('original_name'),
                'date': row.get('release_date') or row.get('first_air_date') or None,
                'original_language': row.get('original_language')}

    def search(self, query, kind, year=None):
        params = {'query': query, 'include_adult': 'false'}
        if year:
            params['year' if kind == 'movie' else 'first_air_date_year'] = year
        return [self.identity(kind, item) for item in self.get('search/' + kind, **params).get('results', [])]

    def detail(self, title_id):
        from media_mcp.config import parse_title_id
        kind, ident = parse_title_id(title_id)
        return self.identity(kind, self.get(f'{kind}/{ident}'))
