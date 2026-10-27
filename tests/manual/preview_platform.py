"""Disposable browser QA server. Fake providers, no downloader or worker, no real media."""
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import uvicorn

from media_mcp.platform.accounts import Accounts
from media_mcp.platform.api import create_app
from media_mcp.platform.service import PlatformService
from media_mcp.storage.media import _client
from media_mcp.storage.records import Records


class PreviewTMDB:
    titles = ('远山来信 · 测试作品','午夜航线 · 测试作品','岛屿漫游 · 测试作品',
              '秋日留声 · 测试作品','星海旅人 · 测试作品','风的另一边 · 测试作品')

    def get(self, path, **params):
        import re
        match = re.fullmatch(r'(movie|tv)/(\d+)(?:/season/(\d+))?', path)
        ident = int(match[2]) if match else 1
        if match and match[3]:
            return {'episodes':[{'episode_number':index,'name':f'测试第 {index} 集'} for index in range(1,4)]}
        item = {'id':1, 'title':'远山来信 · 测试作品', 'original_title':'Letters from the Mountain',
                'release_date':'2025-01-01', 'overview':'仅用于界面验证的虚构作品，不会访问真实资源站或下载器。',
                'original_language':'zh', 'vote_average':8.4, 'genres':[{'name':'剧情'}]}
        if path.startswith('trending/') or path.startswith('search/'):
            return {'results':[{**item,'id':index+1,'title':title} for index,title in enumerate(
                self.titles)]}
        item.update(id=ident, title=self.titles[(ident-1)%len(self.titles)])
        if match and match[1] == 'tv':
            item['seasons'] = [{'season_number':1,'name':'第一季 · 测试','episode_count':3}]
        return item

    def search(self, query, kind, year=None):
        from media_mcp.adapters.tmdb import TMDB
        delay = min(8, max(0, float(os.environ.get('MEDIA_PREVIEW_DELAY_SECONDS','0'))))
        if delay and query == 'slow-old':
            delay = 8
        elif delay and query == 'fast-new':
            delay = 1
        if delay:
            import time
            self.search_calls = getattr(self,'search_calls',0)+1
            print('preview_title_search_count='+str(self.search_calls),flush=True)
            time.sleep(delay)
            if query == 'fail-preview':
                raise RuntimeError('tmdb_unavailable')
        rows = [TMDB.identity(kind, row) for row in self.get('search/'+kind)['results']]
        return [{**row,'title':'['+query+'] '+row['title']} for row in rows] if delay else rows

    def detail(self, title_id):
        from media_mcp.adapters.tmdb import TMDB
        kind, ident = title_id.split(':')
        return TMDB.identity(kind, self.get(f'{kind}/{ident}'))


class PreviewIndexer:
    def search(self, query, kind=None):
        return {'releases':[{'name':query+' 2025 1080p WEB-DL', 'size':4*1024**3,
            'seeders':28,'resolution':1080,'indexer':'测试站点', 'indexer_id':'preview',
            'categories':[5000 if kind == 'tv' else 2000], 'download_url':'magnet:?xt=urn:btih:'+'a'*40}],
            'diagnostics':[{'site':'preview','status':'ok','raw_count':1}]}


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='media-platform-preview-') as directory:
        root = Path(directory)
        os.environ.update(MEDIA_DB_PATH=str(root/'state/media.sqlite3'), MEDIA_STATE_DIR=str(root/'state'),
            MEDIA_DOWNLOAD_ROOT=str(root/'downloads'), MEDIA_LIBRARY_ROOT=str(root/'library'),
            MEDIA_HEALTH_DIR=str(root/'health'), MEDIA_WEB_PUBLIC='false', MEDIA_ALLOWED_HOSTS='localhost',
            MEDIA_WEB_SECURE_COOKIE='false')
        records = Records(_client(None))
        records.initialize()
        accounts = Accounts(records.db)
        accounts.initialize()
        accounts.bootstrap('preview', 'preview-password-123', 'x'*32, 'x'*32)
        admin = accounts.login('preview','preview-password-123')[2]
        for username, download, manage in (('viewer',True,False),('observer',False,False),('librarian',False,True)):
            accounts.create_user(admin,username,'preview-password-123',
                                 can_download=download,can_manage_media=manage)
        with patch('media_mcp.platform.api.Catalog') as catalog_type:
            from media_mcp.platform.catalog import Catalog
            catalog_type.return_value = Catalog(records.db, tmdb=PreviewTMDB())
            app = create_app(accounts, records, lambda actor:PlatformService(
                actor, accounts, records, tmdb=PreviewTMDB(), indexer=PreviewIndexer()))
        uvicorn.run(app, host='0.0.0.0', port=18293, proxy_headers=False)
