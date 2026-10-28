"""Read-only disk discovery, frozen previews and transactional inventory adoption.

Discovery never identifies torrents or infers TMDB identities. Unpaired files live
in their own inventory instead of inventing source/target media mappings.
"""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import stat
import time

from sqlalchemy import text

from media_mcp.runtime.state import media_mutation_lock, assert_mutation_lock
from media_mcp.storage.media import upsert_media_link

VIDEO = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.m2ts', '.wmv', '.webm'}
SUBTITLE = {'.srt', '.ass', '.ssa', '.vtt', '.sup', '.sub', '.idx'}
MAX_ENTRIES = 20000


class Inventory:
    def __init__(self, records):
        self.records, self.db = records, records.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL UNIQUE,
            data TEXT NOT NULL, scan_id TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def _discover(self):
        roots = [Path(os.environ.get('MEDIA_DOWNLOAD_ROOT', '/data/downloads')).absolute(),
                 Path(os.environ.get('MEDIA_LIBRARY_ROOT', '/data/media_hub')).absolute()]
        # A symlink root or overlapping roots makes ownership ambiguous.
        for root in roots:
            if root != root.resolve() or not root.is_dir():
                raise ValueError('inventory_root_unavailable')
        if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
            raise ValueError('inventory_roots_overlap')
        files, skipped, visited = [], [], 0
        started = time.monotonic()

        def failed(_error):
            raise ValueError('inventory_scan_unreadable')

        for role, root in zip(('download', 'library'), roots):
            for directory, dirs, names in os.walk(root, followlinks=False, onerror=failed):
                visited += len(dirs) + len(names)
                if visited > MAX_ENTRIES or time.monotonic()-started > 25:
                    raise ValueError('inventory_scan_limit')
                for name in list(dirs):
                    item = Path(directory)/name
                    if item.is_symlink():
                        skipped.append(str(item)); dirs.remove(name)
                for name in sorted(names):
                    path = Path(directory)/name
                    try:
                        info = path.lstat()
                    except OSError:
                        raise ValueError('inventory_scan_unreadable') from None
                    if not stat.S_ISREG(info.st_mode):
                        skipped.append(str(path)); continue
                    suffix = path.suffix.lower()
                    if suffix not in VIDEO | SUBTITLE:
                        continue
                    files.append({'path':str(path), 'role':role,
                                  'kind':'video' if suffix in VIDEO else 'subtitle',
                                  'fingerprint':[info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]})
        files.sort(key=lambda item:item['path'])
        mappings = [dict(row) for row in self.db.execute('''SELECT id, source_path, target_path,
            status, updated_at FROM media_link ORDER BY id''').mappings()]
        return {'roots':[str(p) for p in roots], 'data_directory':os.environ.get('MEDIA_DATA_DIR', './data'),
                'files':files, 'skipped':sorted(skipped), 'mappings':mappings}

    @staticmethod
    def _digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _items(discovery):
        videos = [f for f in discovery['files'] if f['kind'] == 'video']
        by_identity = defaultdict(list)
        by_path = {f['path']:f for f in videos}
        for item in videos:
            by_identity[tuple(item['fingerprint'][:2])].append(item)
        mappings = discovery['mappings']
        source_map = {m['source_path']:m for m in mappings}
        target_map = {m['target_path']:m for m in mappings}
        skipped_paths = set(discovery['skipped'])
        def mapping_in_scope(mapping):
            return all(value and Path(value).is_absolute() and '..' not in Path(value).parts
                       and Path(value) != Path(root) and Path(value).is_relative_to(root)
                       for value, root in zip((mapping['source_path'],mapping['target_path']),discovery['roots']))
        def mapping_excluded(mapping):
            paths = (mapping['source_path'], mapping['target_path'])
            return any(Path(value).suffix.lower() not in VIDEO or
                       any(str(parent) in skipped_paths for parent in (Path(value), *Path(value).parents))
                       for value in paths)
        items = []
        for file in videos:
            item = {**file, 'name':Path(file['path']).stem, 'subtitles':[], 'peers':[], 'media_id':None}
            mapping = source_map.get(file['path']) or target_map.get(file['path'])
            if mapping:
                source, target = by_path.get(mapping['source_path']), by_path.get(mapping['target_path'])
                item['media_id'] = mapping['id']
                item['status'] = ('linked' if source and target and source['fingerprint'][:2] == target['fingerprint'][:2]
                                  else 'conflict' if source and target
                                  else 'target_missing' if source else 'source_missing')
                if mapping['status'] not in ('linked', 'source_missing', 'target_missing', 'broken'):
                    item['status'] = 'needs_review'
                if mapping_excluded(mapping):
                    item['status'] = 'excluded_mapping'
                if not mapping_in_scope(mapping):
                    item['status'] = 'outside_roots'
            else:
                peers = [f['path'] for f in by_identity[tuple(file['fingerprint'][:2])] if f['role'] != file['role']]
                item['peers'] = peers
                item['status'] = ('paired' if len(peers) == 1 and len(by_identity[tuple(file['fingerprint'][:2])]) == 2
                                  else 'ambiguous' if peers else 'unorganized' if file['role'] == 'download' else 'library_only')
                if item['status'] == 'paired' and any(peer in source_map or peer in target_map for peer in peers):
                    item['status'] = 'conflict'
            items.append(item)
        video_names = defaultdict(list)
        for video in items:
            path = Path(video['path'])
            video_names[(str(path.parent),path.stem)].append(video)
        for subtitle in (f for f in discovery['files'] if f['kind'] == 'subtitle'):
            path = Path(subtitle['path'])
            # Longest exact basename prefix wins; language/translation is deliberately unknown.
            stem, matches = path.stem, []
            while stem:
                matches = video_names.get((str(path.parent),stem), [])
                if matches:
                    break
                stem = stem.rpartition('.')[0]
            if len(matches) == 1:
                matches[0]['subtitles'].append(subtitle['path'])
            items.append({**subtitle, 'name':path.name, 'status':'subtitle_matched' if len(matches) == 1 else 'subtitle_unmatched',
                          'video_path':matches[0]['path'] if len(matches) == 1 else None})
        for mapping in mappings:
            if mapping['source_path'] not in by_path and mapping['target_path'] not in by_path:
                items.append({'path':mapping['source_path'], 'target_path':mapping['target_path'],
                              'kind':'record', 'role':'database', 'name':Path(mapping['source_path']).name,
                              'media_id':mapping['id'], 'status':('outside_roots' if not mapping_in_scope(mapping)
                               else 'excluded_mapping' if mapping_excluded(mapping) else 'missing_both')})
        return items

    def scan(self, owner):
        # Serialize scans across HTTP requests without blocking a filesystem writer.
        with self.db.lock('inventory-scan', timeout=0):
            discovery = self._discover()
            items = self._items(discovery)
            data = {'owner':owner, 'expires_at':time.time()+1800, 'discovery':discovery,
                    'digest':self._digest(discovery), 'items':items,
                    'summary':dict(Counter(item['status'] for item in items))}
            row = self.records.put('inventory_scan', data, 'preview')
            return self.preview(row['id'], owner)

    def preview(self, scan_id, owner, after=0, limit=50):
        row = self.records.get(scan_id, 'inventory_scan')
        data = row['data']
        if data['owner'] != owner:
            raise ValueError('permission_denied')
        items = data['items']
        return {'scan_id':row['id'], 'state':'empty' if not items else row['state'], 'summary':data['summary'],
                'total':len(items), 'roots':data['discovery']['roots'],
                'data_directory':data['discovery'].get('data_directory'),
                'skipped':data['discovery']['skipped'][:50], 'skipped_count':len(data['discovery']['skipped']),
                'items':items[after:after+limit], 'next_cursor':after+limit if after+limit < len(items) else None}

    def adopt(self, scan_id, owner):
        with media_mutation_lock(self.db, timeout=0):
            row = self.records.get(scan_id, 'inventory_scan')
            data = row['data']
            if data['owner'] != owner:
                raise ValueError('permission_denied')
            if not data['items']:
                raise ValueError('inventory_empty_scan')
            if row['state'] == 'imported':
                return {'scan_id':scan_id, 'state':'imported', 'total':len(data['items']),
                        **data.get('receipt', {})}
            if data['expires_at'] < time.time():
                raise ValueError('inventory_preview_expired')
            if self._digest(self._discover()) != data['digest']:
                raise ValueError('inventory_changed_rescan')
            assert_mutation_lock()
            # No filesystem writes, task submissions, or metadata-provider requests.
            with self.db.begin() as conn:
                refreshed = set()
                links_created = 0
                for item in data['items']:
                    conn.execute(text('''INSERT INTO media_inventory(path,data,scan_id) VALUES(:path,:data,:scan)
                        ON CONFLICT(path) DO UPDATE SET data=excluded.data,scan_id=excluded.scan_id,updated_at=CURRENT_TIMESTAMP'''),
                        {'path':item['path'], 'data':json.dumps(item, ensure_ascii=False), 'scan':scan_id})
                    if item.get('media_id') and item['media_id'] not in refreshed and item['status'] in (
                            'linked', 'source_missing', 'target_missing', 'missing_both', 'conflict'):
                        refreshed.add(item['media_id'])
                        status = 'broken' if item['status'] in ('missing_both', 'conflict') else item['status']
                        conn.execute(text('''UPDATE media_link SET status=:status,
                            source_exists=:source_exists,target_exists=:target_exists,
                            reason=CASE WHEN status=:status THEN reason ELSE :reason END,
                            updated_at=CURRENT_TIMESTAMP WHERE id=:id
                            AND status IN ('linked','source_missing','target_missing','broken')'''),
                            {'id':item['media_id'], 'status':status,
                             'source_exists':int(item['status'] not in ('source_missing','missing_both')),
                             'target_exists':int(item['status'] not in ('target_missing','missing_both')),
                             'reason':None if status == 'linked' else 'disk_inventory_import; '+item['status']})
                    if item['status'] == 'paired' and item['role'] == 'download':
                        source, target = item['path'], item['peers'][0]
                        # Do not claim paths already owned by another mapping.
                        conflict = conn.execute(text('''SELECT id FROM media_link WHERE source_path=:source OR
                            target_path=:target OR source_path=:target OR target_path=:source'''),
                            {'source':source, 'target':target}).first()
                        if not conflict:
                            upsert_media_link(None, source, target, filename=Path(source).name,
                                              media_name=Path(target).stem, status='linked',
                                              reason='disk_inventory_import; identity_unverified', _connection=conn)
                            links_created += 1
                indexed = conn.execute(text('SELECT COUNT(*) FROM media_inventory WHERE scan_id=:id'),
                                       {'id':scan_id}).scalar_one()
                if indexed != len({item['path'] for item in data['items']}):
                    raise RuntimeError('inventory_import_verification_failed')
                data['receipt'] = {'indexed_count':indexed, 'media_links_created':links_created}
                # Retain older inventory as history; only the latest complete import is displayed.
                assert_mutation_lock()
                conn.execute(text('''UPDATE media_mcp_record SET state='imported',data=:data,revision=revision+1,
                    updated_at=CURRENT_TIMESTAMP WHERE id=:id'''), {'id':scan_id, 'data':json.dumps(data,ensure_ascii=False)})
            return {'scan_id':scan_id, 'state':'imported', 'total':len(data['items']), **data['receipt']}

    def list(self, after=0, limit=50):
        latest = self.db.execute("SELECT id,data,updated_at FROM media_mcp_record WHERE kind='inventory_scan' AND state='imported' ORDER BY updated_at DESC,rowid DESC LIMIT 1").mappings().first()
        scan_id = latest['id'] if latest else ''
        data = json.loads(latest['data']) if latest else {}
        rows = self.db.execute('''SELECT id,data FROM media_inventory WHERE scan_id=:scan AND id>:after ORDER BY id LIMIT :limit''',
                               {'scan':scan_id, 'after':after, 'limit':limit}).mappings().all()
        total = self.db.execute('SELECT COUNT(*) FROM media_inventory WHERE scan_id=:scan', {'scan':scan_id}).scalar()
        return {'items':[json.loads(row['data']) for row in rows],
                'next_cursor':rows[-1]['id'] if len(rows) == limit else None, 'scan_id':scan_id or None,
                'total':total, 'summary':data.get('summary', {}), 'roots':data.get('discovery',{}).get('roots',[]),
                'data_directory':data.get('discovery',{}).get('data_directory'),
                'imported_at':latest['updated_at'] if latest else None, **data.get('receipt',{})}
