import unittest
from unittest.mock import Mock, patch
from media_mcp.monitor.qbittorrent import MediaMonitor

class StartupTest(unittest.TestCase):
    def monitor(self):
        with patch('media_mcp.monitor.qbittorrent.signal.signal'):
            return MediaMonitor(Mock(), Mock(), conn_dict={'host': 'test'})

    def test_failure_notifies_and_does_not_scan(self):
        m = self.monitor()
        with patch('media_mcp.monitor.qbittorrent.CodexMediaClient') as client, patch('media_mcp.monitor.qbittorrent.mcp_direct_call_ns', return_value=True) as notify, patch('media_mcp.monitor.qbittorrent.time.sleep', side_effect=lambda _: setattr(m, 'stop', True)), patch.object(m, '_get_client', return_value=Mock()) as qb:
            client.return_value.check_connection.side_effect = TimeoutError()
            m.run()
            self.assertIn('失败', notify.call_args.kwargs['title'])
            qb.return_value.torrents_info.assert_not_called()
            m.queue.put.assert_not_called()

    def test_success_check_precedes_started_notification(self):
        m = self.monitor()
        events = []
        def notify(*args, **kwargs):
            events.append(kwargs['content'])
            m.stop = True
            return True
        with patch('media_mcp.monitor.qbittorrent.CodexMediaClient') as client, patch('media_mcp.monitor.qbittorrent.mcp_direct_call_ns', side_effect=notify), patch.object(m, '_get_client', return_value=Mock()):
            client.return_value.check_connection.side_effect = lambda: events.append('checked')
            m.run()
        self.assertEqual('checked', events[0])
        self.assertIn('自检通过', events[1])
