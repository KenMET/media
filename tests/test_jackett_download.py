import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext
from media_mcp.adapters.jackett import Jackett
from media_mcp.adapters.torrent import infohash
from media_mcp.application.controller import Controller
from test_acquire import MemoryRecords, data

MAGNET='magnet:?xt=urn:btih:'+'a'*40
BASE='http://127.0.0.1:18212'


def response(status=200, location=None, content=b'torrent'):
    result=Mock();result.status_code=status
    result.headers={} if location is None else {'Location':location}
    result.iter_content.return_value=[content]
    result.__enter__=Mock(return_value=result);result.__exit__=Mock(return_value=False)
    return result


class JackettDownloadTests(unittest.TestCase):
    def adapter(self, *responses):
        session=Mock();session.get.side_effect=responses
        adapter=Jackett(session);adapter.base=BASE
        return adapter

    def test_proxy_to_valid_magnet_is_not_fetched(self):
        adapter=self.adapter(response(302,MAGNET))
        self.assertEqual(adapter.torrent(BASE+'/download'),MAGNET)
        adapter.session.get.assert_called_once()
        self.assertFalse(adapter.session.get.call_args.kwargs['allow_redirects'])

    def test_direct_magnet_and_torrent_remain_supported(self):
        adapter=self.adapter(response(content=b'd4:infodee'))
        self.assertIsNone(adapter.torrent(MAGNET))
        self.assertEqual(adapter.torrent(BASE+'/download'),b'd4:infodee')

    def test_same_origin_relative_hop_then_magnet(self):
        adapter=self.adapter(response(307,'/resolved'),response(302,MAGNET))
        self.assertEqual(adapter.torrent(BASE+'/download'),MAGNET)
        self.assertEqual(adapter.session.get.call_args_list[1].args[0],BASE+'/resolved')

    def test_external_and_unsafe_handoffs_are_not_requested(self):
        for location in ('https://example.com/file','http://192.168.8.2/file',
                         '//evil.test/file','file:///etc/passwd',
                         'http://user:pass@127.0.0.1:18212/file',
                         'magnet:?dn=missing-hash','magnet:?xt=urn:btih:invalid',
                         '', 'bad\nheader'):
            with self.subTest(location=location):
                adapter=self.adapter(response(302,location))
                with self.assertRaises(ValueError):adapter.torrent(BASE+'/download')
                adapter.session.get.assert_called_once()

    def test_untrusted_initial_url_rejected(self):
        adapter=self.adapter()
        with self.assertRaises(ValueError):adapter.torrent('http://evil.test/file')
        adapter.session.get.assert_not_called()

    def test_redirect_loop_limit_and_payload_limit(self):
        adapter=self.adapter(response(302,'/download'))
        with self.assertRaisesRegex(ValueError,'redirect_loop'):adapter.torrent(BASE+'/download')
        adapter=self.adapter(*(response(302,'/'+str(i)) for i in range(4)))
        with self.assertRaisesRegex(ValueError,'redirect_limit'):adapter.torrent(BASE+'/download')
        adapter=self.adapter(response(content=b'x'*(8*1024*1024+1)))
        with self.assertRaisesRegex(ValueError,'torrent_too_large'):adapter.torrent(BASE+'/download')

    def test_controller_freezes_redirected_magnet_and_checks_claim(self):
        for claimed, expected in (('a'*40,'downloading'),('b'*40,'needs_review')):
            records=MemoryRecords();payload=data()
            payload['release'].update(download_url=BASE+'/download',claimed_infohash=claimed)
            row=records.put('acquisition',payload,'queued')
            downloader=Mock();downloader.find.return_value=None
            adapter=self.adapter(response(302,MAGNET))
            Controller(records,downloader,adapter,Mock())._tick(row)
            row=records.get(row['id']);self.assertEqual(row['state'],expected)
            if expected=='downloading':
                self.assertEqual(row['data']['magnet'],MAGNET)
                self.assertEqual(downloader.add.call_args.kwargs['magnet'],MAGNET)
                self.assertEqual(row['data']['infohash'],'a'*40)
            else:
                self.assertEqual(row['data']['error_code'],'indexer_infohash_mismatch')
                downloader.add.assert_not_called()

    def test_unknown_redirected_magnet_submission_is_not_repeated(self):
        records=MemoryRecords();payload=data();payload['release']['download_url']=BASE+'/download'
        row=records.put('acquisition',payload,'queued')
        adapter=self.adapter(response(302,MAGNET))
        downloader=Mock();downloader.find.return_value=None;downloader.add.side_effect=TimeoutError()
        controller=Controller(records,downloader,adapter,Mock())
        controller._tick(row);row=records.get(row['id'])
        self.assertEqual(row['state'],'submission_unknown')
        controller._tick(row)
        self.assertEqual(downloader.add.call_count,1)
        self.assertEqual(adapter.session.get.call_count,1)
