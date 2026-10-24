import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from media_mcp.monitor.qbittorrent import MediaMonitor
from media_mcp.monitor.health import healthy


class DeliveryTests(unittest.TestCase):
    def monitor(self, **kwargs):
        with patch('media_mcp.monitor.qbittorrent.signal.signal'):
            return MediaMonitor(Mock(),Mock(),conn_dict={'host':'test'},**kwargs)

    def test_missing_source_retains_torrent_and_can_retry(self):
        monitor=self.monitor();monitor.client=Mock()
        torrent=SimpleNamespace(hash='a'*40,name='movie',content_path='/nonexistent-media-file')
        monitor._on_torrent_completed(torrent)
        monitor.client.torrents_delete.assert_not_called();monitor.queue.put.assert_not_called()
        self.assertNotIn(torrent.hash,monitor.completed_seen)

    def test_failed_delivery_is_not_seen(self):
        monitor=self.monitor(jobs=Mock());monitor.jobs.enqueue.side_effect=RuntimeError('db_down')
        with tempfile.NamedTemporaryFile() as file:
            torrent=SimpleNamespace(hash='a'*40,name='movie',completion_on=1,content_path=file.name)
            with self.assertRaises(RuntimeError):monitor._on_torrent_completed(torrent)
            self.assertNotIn(torrent.hash,monitor.completed_seen)
            monitor.jobs.enqueue.side_effect=None;monitor._on_torrent_completed(torrent)
            self.assertIn(torrent.hash,monitor.completed_seen)

    def test_health_rejects_missing_or_stale_worker(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ('monitor','ingest','subtitle'):Path(root,name).write_text('100')
            self.assertTrue(healthy(root,200));Path(root,'subtitle').write_text('0')
            self.assertFalse(healthy(root,200))

    def test_readded_hash_is_a_new_delivery(self):
        monitor=self.monitor(jobs=Mock())
        with tempfile.NamedTemporaryFile() as file:
            first=SimpleNamespace(hash='a'*40,name='movie',content_path=file.name,completion_on=1,added_on=1,state='uploading',progress=1)
            second=SimpleNamespace(**{**vars(first),'completion_on':2,'added_on':2})
            client=Mock();client.torrents_info.side_effect=[[first],[second]]
            sleeps=[]
            def tick(_):
                sleeps.append(1)
                if len(sleeps)==2:monitor.stop=True
            with patch.object(monitor,'_get_client',return_value=client),patch.object(monitor,'_check_codex_before_start',return_value=True),patch('media_mcp.monitor.qbittorrent.mcp_direct_call_ns',return_value=True),patch('media_mcp.monitor.qbittorrent.time.sleep',side_effect=tick),patch('media_mcp.runtime.worker.heartbeat'):
                monitor.run()
        self.assertEqual(monitor.jobs.enqueue.call_count,2)
        keys=[call.args[0] for call in monitor.jobs.enqueue.call_args_list]
        self.assertNotEqual(keys[0],keys[1])
