"""One short tick per owned acquisition. file locks serialize controllers."""
import base64
import hashlib
import time
from pathlib import Path
from sqlalchemy import text
from media_mcp.adapters.download import Downloader
from media_mcp.adapters.jackett import Jackett
from media_mcp.adapters.torrent import infohash
from media_mcp.config import contained, download_root
from media_mcp.runtime.state import MediaJobs


class Controller:
    def __init__(self, records, downloader=None, indexer=None, jobs=None):
        self.records = records
        self.downloader = downloader or Downloader()
        self.indexer = indexer or Jackett()
        self.jobs = jobs or MediaJobs()

    def tick(self, job_id):
        try:
            with self.records.db.lock('acquire:'+job_id):
                row = self.records.get(job_id, 'acquisition')
                if (row['data'].get('retry_at') or 0) > time.time():
                    return
                self._tick(row)
        except RuntimeError as exc:
            if str(exc)!='media_busy_retry_later':raise

    def _tick(self, row):
        data = dict(row['data'])
        state = row['state']
        if state == 'queued':
            try:
                url = data['release']['download_url']
                torrent = self.indexer.torrent(url)
                if isinstance(torrent, str):
                    # Jackett may hand off its trusted proxy URL to a magnet.
                    url, torrent = torrent, None
                hash_value = infohash(torrent, url if torrent is None else None)
                claimed = data['release'].get('claimed_infohash')
                if claimed and claimed.lower() != hash_value:
                    raise ValueError('indexer_infohash_mismatch')
                # Freeze payload before submission. Never fetch a replacement after an unknown add.
                data.update({'infohash': hash_value, 'torrent_base64': base64.b64encode(torrent).decode() if torrent else None,
                             'magnet': url if torrent is None else None, 'error_code': None, 'retry_at': None})
                # Do not adopt an existing task silently: it may be owned by another workflow.
                self.downloader.prepare()
                if self.downloader.find(hash_value):
                    self.records.update(row, 'needs_review', {**data, 'error_code': 'torrent_already_exists'})
                    return
                row = self.records.update(row, 'submitting', {**data, 'submission_attempted': True})
            except ValueError as exc:
                self.records.update(row, 'needs_review', {**data, 'error_code': str(exc)})
                return
            except Exception:
                self.records.update(row, 'queued', {**data, 'error_code': 'prepare_download_unavailable', 'retry_at': time.time()+60})
                return
            data = row['data']
            try:
                self.downloader.add(hash_value=data['infohash'], job_id=row['id'],
                    torrent=base64.b64decode(data['torrent_base64']) if data['torrent_base64'] else None,
                    magnet=data['magnet'])
            except Exception:
                self.records.update(row, 'submission_unknown', {**data, 'error_code': 'download_submission_outcome_unknown'})
                return
            self.records.update(row, 'downloading', {**data, 'torrent_base64': None})
            return
        if state in ('submitting', 'submission_unknown', 'downloading'):
            try:
                torrent = self.downloader.find(data['infohash'])
            except Exception:
                self.records.update(row, state, {**data, 'error_code': 'downloader_unavailable', 'retry_at': time.time()+30})
                return
            if torrent is None:
                self.records.update(row, 'submission_unknown' if state in ('submitting','submission_unknown') else 'needs_review',
                    {**data, 'error_code': 'download_submission_outcome_unknown' if state != 'downloading' else 'torrent_missing'})
                return
            # Matching hash is not enough: ensure the recovered add is this job's task.
            if (torrent.get('category') != __import__('os').environ.get('MEDIA_TORRENT_CATEGORY', 'media-mcp') or
                'media-mcp-'+row['id'] not in {t.strip() for t in torrent.get('tags','').split(',')}):
                self.records.update(row, 'needs_review', {**data, 'error_code': 'torrent_owner_mismatch'})
                return
            data.update({'progress': torrent['progress'], 'error_code': None, 'retry_at': None, 'torrent_base64': None})
            if torrent['progress'] < 1 or torrent['state'] in ('moving','checkingDL','checkingUP','checkingResumeData'):
                self.records.update(row, 'downloading', data)
                return
            try:
                path = contained(torrent['content_path'])
                files = self.downloader.files(data['infohash'])
                if not files or any(float(f.get('progress', 0)) < 1 for f in files if int(f.get('priority', 1)) != 0):
                    raise ValueError('download_files_incomplete')
                for item in files:
                    name = item['name']
                    if Path(name).is_absolute() or '..' in Path(name).parts:
                        raise ValueError('unsafe_torrent_member')
                    contained(str(Path(torrent['save_path']) / name))
                if path.is_dir():
                    for child in path.rglob('*'):
                        contained(str(child))
                elif not path.is_file():
                    raise ValueError('source_not_regular_file')
            except (OSError, ValueError, KeyError):
                self.records.update(row, 'needs_review', {**data, 'error_code': 'download_path_or_manifest_invalid'})
                return
            delivery = 'acquire:' + row['id']
            # Persist association first; crash before enqueue is recovered by the next tick.
            data.update({'source_path': str(path), 'delivery_hash': hashlib.sha256(delivery.encode()).hexdigest()})
            row = self.records.update(row, 'enqueue_processing', data)
            state = 'enqueue_processing'
        if state == 'enqueue_processing':
            self.jobs.enqueue('acquire:' + row['id'], data['source_path'], stage='subtitle' if data.get('workflow')=='subtitle' else 'ingest')
            self.records.update(row, 'processing', data)
            return
        if state == 'processing':
            results = self.records.db.execute('SELECT stage,state,error,result_json FROM media_processing_job WHERE delivery_key=:key',
                {'key': data['delivery_hash']}).mappings().all()
            data['processing'] = [dict(item) for item in results]
            if any(item['state']=='needs_review' for item in results):
                self.records.update(row, 'needs_review', {**data, 'error_code': 'processing_needs_review'})
            elif len(results)==(1 if data.get('workflow')=='subtitle' else 2) and all(item['state']=='succeeded' for item in results):
                identity, scope = data['identity'], data['scope']
                links = self.records.db.execute("""SELECT source_path,target_path,season,episode FROM media_link
                    WHERE status='linked' AND media_type=:kind AND media_tmdb_id=:tmdb
                    AND (source_path=:path OR substr(source_path,1,LENGTH(:prefix))=:prefix)""",
                    {'kind':identity['kind'],'tmdb':identity['tmdb_id'], 'path':data['source_path'],
                     'prefix':data['source_path'].rstrip('/')+'/'}).mappings().all()
                try:
                    if not links:
                        raise ValueError('no_linked_media')
                    for item in links:
                        contained(item['source_path'])
                        if not __import__('os').path.samefile(item['source_path'],item['target_path']):
                            raise ValueError('hardlink_postcondition_failed')
                    if identity['kind']=='tv' and not set(scope['episodes']).issubset(
                            {item['episode'] for item in links if item['season']==scope['season']}):
                        raise ValueError('requested_episodes_missing')
                except (OSError,ValueError):
                    self.records.update(row,'needs_review',{**data,'error_code':'library_postcondition_requires_review'})
                    return
                self.records.update(row, 'completed', {**data, 'result': 'media_and_subtitles_processed', 'error_code': None})
            else:
                self.records.update(row, 'processing', data)
