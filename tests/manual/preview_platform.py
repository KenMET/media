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
                'original_language':'zh', 'vote_average':8.4, 'poster_path':f'/preview-{ident}.jpg', 'genres':[{'name':'剧情'}]}
        if path.startswith('trending/') or path.startswith('search/'):
            return {'results':[{**item,'id':index+1,'title':title} for index,title in enumerate(
                self.titles)]}
        item.update(id=ident, title=self.titles[(ident-1)%len(self.titles)])
        if match and match[1] == 'tv':
            item['seasons'] = [{'season_number':n,'name':f'第 {n} 季 · 测试','episode_count':3} for n in (1,2)]
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
        (root/'.acceptance').write_text('media-collection-preview')
        if os.environ.get('MEDIA_PREVIEW_MANIFEST'):
            import json
            manifest=Path(os.environ['MEDIA_PREVIEW_MANIFEST'])
            manifest.write_text(json.dumps({'root':str(root),'source':str(root/'downloads'),'library':str(root/'library')}))
            manifest.chmod(0o600)
        os.environ.update(MEDIA_DB_PATH=str(root/'state/media.sqlite3'), MEDIA_STATE_DIR=str(root/'state'),
            MEDIA_DOWNLOAD_ROOT=str(root/'downloads'), MEDIA_LIBRARY_ROOT=str(root/'library'),
            MEDIA_HEALTH_DIR=str(root/'health'), MEDIA_WEB_PUBLIC='false', MEDIA_ALLOWED_HOSTS='localhost',
            MEDIA_WEB_SECURE_COOKIE='false')
        # Existing-file discovery fixtures; these bytes are never playable media.
        downloads, library = root/'downloads', root/'library'
        downloads.mkdir(); library.mkdir()
        if os.environ.get('MEDIA_PREVIEW_EMPTY') != 'true':
            (downloads/'Letters.from.the.Mountain.2025.mkv').write_bytes(b'disposable-preview-video')
            if os.environ.get('MEDIA_PREVIEW_NO_LINKS') == 'true':
                (library/'远山来信 (2025).mkv').write_bytes(b'independent-library-file')
            else:
                os.link(downloads/'Letters.from.the.Mountain.2025.mkv', library/'远山来信 (2025).mkv')
            (library/'远山来信 (2025).zh.srt').write_text('1\n00:00:01,000 --> 00:00:02,000\n测试字幕\n')
            (downloads/'Midnight.Route.S01E01.1080p.mkv').write_bytes(b'unorganized-preview-video')
            (library/'岛屿漫游 (2024).mp4').write_bytes(b'library-only-preview-video')
            (library/'尚未匹配的字幕.ass').write_text('[Script Info]\nTitle: Preview')
            (downloads/'失效的软链接.mkv').symlink_to(downloads/'missing.mkv')
        records = Records(_client(None))
        records.initialize()
        accounts = Accounts(records.db)
        accounts.initialize()
        accounts.bootstrap('preview', 'preview-password-123', 'x'*32, 'x'*32)
        admin = accounts.login('preview','preview-password-123')[2]
        for username, download, manage in (('viewer',True,False),('observer',False,False),('librarian',False,True)):
            accounts.create_user(admin,username,'preview-password-123',
                                 can_download=download,can_manage_media=manage)
        if os.environ.get('MEDIA_PREVIEW_COLLECTIONS')=='true':
            from media_mcp.storage.media import upsert_media_link,upsert_media_subtitle
            from media_mcp.application.collections import digest
            for season,episode in ((1,1),(1,2),(2,1)):
                source=downloads/f'Island.S{season:02d}E{episode:02d}.mkv'
                source.write_bytes(b'preview-episode')
                target=library/'series/岛屿漫游'/f'第{season:02d}季'/f'岛屿漫游 - S{season:02d}E{episode:02d} - 2025.mkv'
                target.parent.mkdir(parents=True,exist_ok=True);os.link(source,target)
                upsert_media_link(None,str(source),str(target),media_name=target.stem,status='linked')
                if season==1 and episode==1:
                    subtitle=target.with_suffix('.zh.srt');subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\n测试字幕\n')
                    upsert_media_subtitle(None,str(subtitle),str(subtitle),matched_video_source_path=str(source),matched_video_target_path=str(target),language='zh',format='srt',status='verified')
            for ident in (1,2,4,5):
                title=PreviewTMDB().detail('movie:'+str(ident))
                source=downloads/f'Preview.Movie.{ident}.mkv';source.write_bytes(b'preview-movie')
                target=library/'movie'/(title['title']+' - 2025.mkv');target.parent.mkdir(exist_ok=True);os.link(source,target)
                upsert_media_link(None,str(source),str(target),media_name=title['title'],media_type='movie',media_tmdb_id=ident,year=2025,status='linked')
                records.put('library_title',{'identity':title,'overview':'用于界面验收的虚构作品。'},key_hash=digest('library-title:'+title['title_id']))

            # A fixture worker uses the real durable queue and hardlink repair, with a fake subtitle engine.
            import threading,time
            from media_mcp.runtime.state import MediaJobs
            from media_mcp.runtime.library_worker import process_task
            from unittest.mock import Mock
            def process_preview_jobs():
                jobs=MediaJobs();jobs.initialize()
                agent=Mock();agent._run_path_summary_locked.return_value={'handled':1,'media_count':1,'failed':0,'missing':0,'review':0}
                while True:
                    job=jobs.claim('library')
                    if job:
                        process_task(jobs,job,agent);jobs.finish(job)
                    time.sleep(.2)
            threading.Thread(target=process_preview_jobs,daemon=True).start()
        with patch('media_mcp.platform.api.Catalog') as catalog_type:
            from media_mcp.platform.catalog import Catalog
            catalog_type.return_value = Catalog(records.db, tmdb=PreviewTMDB())
            app = create_app(accounts, records, lambda actor:PlatformService(
                actor, accounts, records, tmdb=PreviewTMDB(), indexer=PreviewIndexer()))
        uvicorn.run(app, host='127.0.0.1', port=18293, proxy_headers=False)
