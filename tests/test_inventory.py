"""Acceptance of existing resources uses only disposable media and SQLite."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient
from media_mcp.platform.api import create_app
from media_mcp.platform.service import PlatformService
from media_mcp.storage.inventory import Inventory
from media_mcp.storage.media import upsert_media_link
import test_platform


class InventoryTests(unittest.TestCase):
    setUp = test_platform.PlatformTests.setUp

    def fixture(self):
        self.source = Path(os.environ['MEDIA_DOWNLOAD_ROOT']); self.source.mkdir()
        self.target = Path(os.environ['MEDIA_LIBRARY_ROOT']); self.target.mkdir()
        (self.source/'original.mkv').write_bytes(b'original-video')
        os.link(self.source/'original.mkv', self.target/'Collection.mkv')
        (self.target/'Collection.zh.srt').write_text('existing subtitle')
        (self.source/'Loose.mp4').write_bytes(b'not-yet-organized')
        (self.target/'Only.mkv').write_bytes(b'only-library-copy')
        (self.target/'unknown.srt').write_text('unmatched')
        (self.source/'alias.mkv').symlink_to(self.target/'Only.mkv')
        self.inventory = Inventory(self.records)
        return self.inventory

    def test_preview_adoption_idempotency_preserves_all_bytes_and_task_identity(self):
        inv = self.fixture()
        before = {str(p): (p.read_bytes(),p.stat().st_ino) for root in (self.source,self.target)
                  for p in root.iterdir() if not p.is_symlink()}
        result = inv.scan(self.admin.id)
        self.assertEqual(result['summary'], {'paired':2,'unorganized':1,'library_only':1,
                                             'subtitle_matched':1,'subtitle_unmatched':1})
        self.assertEqual(result['skipped_count'],1)
        self.assertEqual(inv.list()['items'],[])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),0)
        inv.adopt(result['scan_id'],self.admin.id)
        inv.adopt(result['scan_id'],self.admin.id)
        self.assertEqual(len(inv.list()['items']),6)
        mapping=self.db.execute('SELECT * FROM media_link').mappings().one()
        self.assertEqual(mapping['source_path'],str(self.source/'original.mkv'))
        self.assertEqual(mapping['target_path'],str(self.target/'Collection.mkv'))
        self.assertIsNone(mapping['media_tmdb_id'])
        subtitle_records=PlatformService(self.admin,self.accounts,self.records).media()['media'][0]['subtitles']
        self.assertEqual(subtitle_records,[{'language':None,'status':'discovered','format':'srt'}])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='acquisition'").scalar(),0)
        second=inv.scan(self.admin.id)
        inv.adopt(second['scan_id'],self.admin.id)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),1)
        for path,(data,inode) in before.items():
            self.assertEqual(Path(path).read_bytes(),data)
            self.assertEqual(Path(path).stat().st_ino,inode)
        linked=[item for item in inv.list()['items'] if item['status']=='linked']
        self.assertEqual(len(linked),2)
        video=next(item for item in linked if item['role']=='library')
        self.assertEqual(video['subtitles'],[str(self.target/'Collection.zh.srt')])

    def test_stale_file_or_mapping_rejects_import_without_partial_writes(self):
        inv=self.fixture();scan=inv.scan(self.admin.id)
        (self.source/'Loose.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'inventory_changed_rescan'):
            inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(inv.list()['items'],[])
        scan=inv.scan(self.admin.id)
        upsert_media_link(None,str(self.source/'Loose.mp4'),str(self.target/'Else.mp4'),status='target_missing')
        with self.assertRaisesRegex(ValueError,'inventory_changed_rescan'):
            inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(inv.list()['items'],[])

    def test_missing_sources_conflicts_missing_both_and_ambiguous_links(self):
        inv=self.fixture()
        upsert_media_link(None,str(self.source/'gone.mkv'),str(self.target/'Only.mkv'),status='source_missing')
        upsert_media_link(None,str(self.source/'Loose.mp4'),str(self.target/'Collection.mkv'),status='linked')
        upsert_media_link(None,str(self.source/'lost.mkv'),str(self.target/'lost.mkv'),status='broken')
        os.link(self.source/'original.mkv',self.target/'Another.mkv')
        scan=inv.scan(self.admin.id)
        by_path={item['path']:item for item in scan['items']}
        self.assertEqual(by_path[str(self.target/'Only.mkv')]['status'],'source_missing')
        self.assertEqual(by_path[str(self.source/'Loose.mp4')]['status'],'conflict')
        self.assertEqual(by_path[str(self.source/'lost.mkv')]['status'],'missing_both')
        self.assertEqual(by_path[str(self.source/'original.mkv')]['status'],'ambiguous')
        inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),3)

    def test_missing_overlapping_and_symlink_roots_rejected(self):
        inv=Inventory(self.records)
        with self.assertRaisesRegex(ValueError,'inventory_root_unavailable'):inv.scan(self.admin.id)
        self.source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);self.source.mkdir()
        with patch.dict(os.environ,MEDIA_LIBRARY_ROOT=str(self.source)):
            with self.assertRaisesRegex(ValueError,'inventory_roots_overlap'):inv.scan(self.admin.id)
        alias=self.source.parent/'alias';alias.symlink_to(self.source,target_is_directory=True)
        with patch.dict(os.environ,MEDIA_DOWNLOAD_ROOT=str(alias)):
            with self.assertRaisesRegex(ValueError,'inventory_root_unavailable'):inv.scan(self.admin.id)

    def test_complete_scan_required_expiry_owner_and_pagination(self):
        inv=self.fixture()
        with patch('media_mcp.storage.inventory.MAX_ENTRIES',1):
            with self.assertRaisesRegex(ValueError,'inventory_scan_limit'):inv.scan(self.admin.id)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_mcp_record WHERE kind='inventory_scan'").scalar(),0)
        scan=inv.scan(self.admin.id)
        with self.assertRaisesRegex(ValueError,'permission_denied'):inv.adopt(scan['scan_id'],self.alice.id)
        with self.assertRaisesRegex(ValueError,'permission_denied'):inv.preview(scan['scan_id'],self.alice.id)
        page=inv.preview(scan['scan_id'],self.admin.id,0,2)
        self.assertEqual(page['next_cursor'],2)
        with patch('media_mcp.storage.inventory.time.time',return_value=10**12):
            with self.assertRaisesRegex(ValueError,'inventory_preview_expired'):inv.adopt(scan['scan_id'],self.admin.id)

    def test_transaction_rollback(self):
        inv=self.fixture();scan=inv.scan(self.admin.id)
        with patch('media_mcp.storage.inventory.upsert_media_link',side_effect=RuntimeError('injected_failure')):
            with self.assertRaisesRegex(RuntimeError,'injected_failure'):inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_inventory').scalar(),0)
        self.assertEqual(self.records.get(scan['scan_id'])['state'],'preview')

    def test_paths_outside_roots_are_not_marked_missing_and_review_is_preserved(self):
        inv=self.fixture()
        upsert_media_link(None,str(self.source.parent/'outside.mkv'),str(self.target/'Only.mkv'),status='linked')
        upsert_media_link(None,str(self.source/'Loose.mp4'),str(self.target/'no-target.mp4'),status='needs_review',reason='retain_review')
        scan=inv.scan(self.admin.id)
        self.assertEqual(scan['summary']['outside_roots'],1)
        inv.adopt(scan['scan_id'],self.admin.id)
        rows=self.db.execute('SELECT source_path,status,reason FROM media_link').mappings().all()
        outside=next(row for row in rows if row['source_path'].endswith('/outside.mkv'))
        self.assertEqual(outside['status'],'linked')
        review=next(row for row in rows if row['source_path'].endswith('/Loose.mp4'))
        self.assertEqual(review['status'],'needs_review')
        self.assertEqual(review['reason'],'retain_review')

    def test_device_identity_and_lock_loss_fence(self):
        inv=self.fixture();scan=inv.scan(self.admin.id)
        discovery=inv._discover()
        a=next(f for f in discovery['files'] if f['path'].endswith('/original.mkv'))
        b=next(f for f in discovery['files'] if f['path'].endswith('/Collection.mkv'))
        b['fingerprint'][0]=a['fingerprint'][0]+1
        self.assertNotIn('paired',{item['status'] for item in inv._items(discovery)})
        with patch('media_mcp.storage.inventory.assert_mutation_lock',side_effect=[None,RuntimeError('media_mutation_lock_lost')]):
            with self.assertRaisesRegex(RuntimeError,'media_mutation_lock_lost'):inv.adopt(scan['scan_id'],self.admin.id)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_inventory').scalar(),0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),0)

    def test_excluded_files_and_symlinks_do_not_become_missing(self):
        inv=self.fixture()
        upsert_media_link(None,str(self.source/'alias.mkv'),str(self.target/'Only.mkv'),status='linked')
        (self.source/'disc.iso').write_bytes(b'existing-disc')
        upsert_media_link(None,str(self.source/'disc.iso'),str(self.target/'disc.iso'),status='linked')
        scan=inv.scan(self.admin.id)
        self.assertEqual(scan['summary']['excluded_mapping'],2)
        inv.adopt(scan['scan_id'],self.admin.id)
        statuses=self.db.execute("SELECT status FROM media_link WHERE source_path LIKE '%alias.mkv' OR source_path LIKE '%disc.iso'").scalars().all()
        self.assertEqual(statuses,['linked','linked'])

    def test_http_admin_csrf_import_and_normal_user_denial(self):
        self.fixture()
        app=create_app(self.accounts,self.records)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()['data']
            headers={'x-csrf-token':login['csrf']}
            payload={'operation':'inventory_scan','arguments':{}}
            self.assertEqual(client.post('/api/command',json=payload).status_code,403)
            response=client.post('/api/command',json=payload,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            scan=response.json()['data']
            response=client.post('/api/command',json={'operation':'inventory_import','arguments':{'scan_id':scan['scan_id']}},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            response=client.post('/api/command',json={'operation':'inventory','arguments':{}},headers=headers)
            self.assertEqual(len(response.json()['data']['items']),6)
            login=client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'}).json()['data']
            for operation,args in [('inventory',{}),('inventory_scan',{}),('inventory_preview',{'scan_id':scan['scan_id']}),('inventory_import',{'scan_id':scan['scan_id']})]:
                response=client.post('/api/command',json={'operation':operation,'arguments':args},headers={'x-csrf-token':login['csrf']})
                self.assertEqual(response.status_code,403,response.text)

if __name__=='__main__':unittest.main()
