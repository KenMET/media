"""qBittorrent adapter for owned downloads, never delete or alter unrelated tasks."""
import os
import qbittorrentapi
from media_mcp.config import download_root


class Downloader:
    def __init__(self, client=None):
        self.client = client or qbittorrentapi.Client(
            host=os.environ.get('QBITTORRENT_URL', 'http://127.0.0.1:18211'),
            username=os.environ.get('QBITTORRENT_USERNAME', ''),
            password=os.environ.get('QBITTORRENT_PASSWORD', ''), REQUESTS_ARGS={'timeout': 15})

    def prepare(self):
        """Ensure our category exists without modifying existing category settings."""
        if os.environ.get('QBITTORRENT_USERNAME') or os.environ.get('QBITTORRENT_PASSWORD'):
            self.client.auth_log_in()
        category = os.environ.get('MEDIA_TORRENT_CATEGORY', 'media-mcp')
        if category not in self.client.torrents_categories():
            try:
                self.client.torrents_create_category(name=category, save_path=str(download_root()))
            except qbittorrentapi.Conflict409Error:
                if category not in self.client.torrents_categories():
                    raise

    def find(self, hash_value):
        if os.environ.get('QBITTORRENT_USERNAME') or os.environ.get('QBITTORRENT_PASSWORD'):
            self.client.auth_log_in()
        rows = self.client.torrents_info(torrent_hashes=hash_value)
        if not rows:
            return None
        row = rows[0]
        return {'hash': row.hash, 'progress': float(row.progress), 'state': str(row.state),
                'content_path': str(row.content_path), 'category': row.category,
                'tags': str(row.tags), 'save_path': str(row.save_path)}

    def add(self, *, hash_value, job_id, torrent=None, magnet=None):
        if self.find(hash_value):
            return 'existing'
        kwargs = {'save_path': str(download_root()), 'category': os.environ.get('MEDIA_TORRENT_CATEGORY', 'media-mcp'),
                  'tags': 'media-mcp-' + job_id, 'use_auto_torrent_management': False}
        response = self.client.torrents_add(**kwargs,
            **({'torrent_files': torrent} if torrent is not None else {'urls': magnet}))
        if str(response).lower() != 'ok.':
            raise RuntimeError('download_submission_rejected')
        return 'submitted'

    def files(self, hash_value):
        return [dict(row) for row in self.client.torrents_files(torrent_hash=hash_value)]
