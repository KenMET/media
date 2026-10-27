"""Live read-only catalog acceptance; SQLite is always temporary, no media access."""
import json
import os
from pathlib import Path
import tempfile
import time

from media_mcp.platform.catalog import Catalog
from media_mcp.adapters.tmdb import TMDB
from media_mcp.storage.client import DatabaseClient


def main():
    with tempfile.TemporaryDirectory(prefix='media-live-catalog-') as directory:
        os.environ['MEDIA_DB_PATH'] = str(Path(directory)/'catalog.sqlite3')
        catalog = Catalog(DatabaseClient(), tmdb=TMDB(remote=False))
        checks = []
        for source in ('simkl', 'tmdb'):
            for kind in ('movie','tv'):
                for window in ('day','week'):
                    result = catalog.discover(source, kind, window)
                    assert result['status'] == 'ready', (source,kind,window,result['error_code'])
                    assert result['items'] and time.time()-result['fetched_at'] < 120
                    if source == 'simkl':
                        assert 0 <= time.time()-result['source_updated_at'] <= 172800
                    checks.append({'source':source,'kind':kind,'window':window,
                        'count':len(result['items']),'fetched_at':result['fetched_at'],
                        'source_updated_at':result['source_updated_at'],
                        'sample_titles':[row['title'] for row in result['items'][:3]]})
            sample = next(row for row in result['items'] if row['title_id'])
            detail = catalog.detail(sample['title_id'])
            assert detail['title_id'] == sample['title_id'] and detail['title']
        print(json.dumps({'acceptance':'passed','checks':checks,
                          'real_provider_requests':True,'media_or_downloader_used':False},ensure_ascii=False))


if __name__ == '__main__':
    main()
