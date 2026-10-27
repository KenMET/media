import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from media_mcp.platform.accounts import Accounts, Actor
from media_mcp.platform.api import create_app
from media_mcp.platform.service import PlatformService
from media_mcp.storage.client import DatabaseClient
from media_mcp.storage.media import _client
from media_mcp.storage.records import Records


class PlatformTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        env = patch.dict(os.environ, {
            'MEDIA_DB_PATH':str(root/'state/media.sqlite3'),
            'MEDIA_DOWNLOAD_ROOT':str(root/'downloads'), 'MEDIA_LIBRARY_ROOT':str(root/'library'),
            'MEDIA_WEB_PUBLIC':'false', 'MEDIA_WEB_SECURE_COOKIE':'false',
            'MEDIA_WEB_BOOTSTRAP_TOKEN':'test-bootstrap-token-32-characters-long',
        })
        env.start()
        self.addCleanup(env.stop)
        self.db = _client(None)
        self.accounts = Accounts(self.db)
        self.accounts.initialize()
        self.admin = self.accounts.bootstrap('owner', 'owner-password-123',
            os.environ['MEDIA_WEB_BOOTSTRAP_TOKEN'], os.environ['MEDIA_WEB_BOOTSTRAP_TOKEN'])
        first = self.accounts.create_user(self.admin, 'alice', 'alice-password-123')
        second = self.accounts.create_user(self.admin, 'bobby', 'bobby-password-123')
        self.alice = Actor(first['id'], 'alice', 'user')
        self.bob = Actor(second['id'], 'bobby', 'user')
        self.records = Records(self.db)
        self.records.initialize()

    def test_bootstrap_one_time_sessions_csrf_and_revocation(self):
        with self.assertRaisesRegex(ValueError, 'bootstrap_closed'):
            self.accounts.bootstrap('other', 'password-123456', 'x'*32, 'x'*32)
        token, csrf, actor = self.accounts.login('alice', 'alice-password-123')
        self.assertEqual(self.accounts.authenticate(token, csrf), actor)
        saved = self.db.execute('SELECT * FROM platform_session').mappings().one()
        self.assertNotEqual(saved['token_hash'], token)
        self.assertNotEqual(saved['csrf_hash'], csrf)
        with self.assertRaisesRegex(ValueError, 'csrf_failed'):
            self.accounts.authenticate(token, 'incorrect')
        self.accounts.update_user(self.admin, actor.id, enabled=False, role='user')
        with self.assertRaisesRegex(ValueError, 'authentication_required'):
            self.accounts.authenticate(token)
        with self.assertRaisesRegex(ValueError, 'last_admin_required'):
            self.accounts.update_user(self.admin, self.admin.id, enabled=False, role='admin')

    def test_capabilities_are_independent_and_revoke_existing_credentials(self):
        session,_,old = self.accounts.login('alice','alice-password-123')
        api = self.accounts.create_api_token(old,'before-permission-change')
        self.accounts.update_user(self.admin,old.id,enabled=True,role='user',
                                  can_download=False,can_manage_media=True)
        with self.assertRaisesRegex(ValueError,'authentication_required'):
            self.accounts.authenticate(session)
        with self.assertRaisesRegex(ValueError,'authentication_required'):
            self.accounts.verify_api_token(api['token'])
        _,_,fresh = self.accounts.login('alice','alice-password-123')
        self.assertFalse(fresh.can_download)
        self.assertTrue(fresh.can_manage_media)
        service = PlatformService(fresh,self.accounts,self.records)
        for call in (lambda:service.search_releases('movie:1'),lambda:service.plan('a'*32),
                     lambda:service.start('a'*32,1,'request-key-123'),lambda:service.retry('a'*32,1)):
            with self.assertRaisesRegex(ValueError,'download_permission_required'):
                call()

    def test_media_manager_access_does_not_expose_other_users_private_jobs(self):
        self.accounts.update_user(self.admin,self.bob.id,enabled=True,role='user',
                                  can_download=False,can_manage_media=True)
        manager=self.accounts.actor_by_id(self.bob.id)
        self.assertTrue(self.accounts.allowed(manager,'media','123',manage=True))
        self.assertFalse(self.accounts.allowed(manager,'task','123',manage=True))
        other=PlatformService(self.alice,self.accounts,self.records).service.records.put(
            'acquisition',{'identity':{'title_id':'movie:1'}},'queued')
        service=PlatformService(manager,self.accounts,self.records)
        self.assertEqual(service.jobs()['jobs'],[])
        with self.assertRaisesRegex(ValueError,'record_not_found'):
            service.job(other['id'])

    def test_admin_has_all_capabilities_and_only_admin_can_change_them(self):
        self.assertTrue(Actor('admin','admin','admin',False,False).can_download)
        self.assertTrue(Actor('admin','admin','admin',False,False).can_manage_media)
        with self.assertRaisesRegex(ValueError,'permission_denied'):
            self.accounts.update_user(self.alice,self.alice.id,enabled=True,role='admin',
                                      can_download=True,can_manage_media=True)
        app=create_app(self.accounts,self.records)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            result=client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'}).json()
            response=client.patch('/api/users/'+self.alice.id,json={'role':'admin','enabled':True,
                'can_download':True,'can_manage_media':True},headers={'x-csrf-token':result['data']['csrf']})
            self.assertEqual(response.status_code,403)

    def test_existing_users_migrate_without_gaining_media_management(self):
        # Reproduce the previous platform schema while keeping the existing account rows.
        self.db.execute('ALTER TABLE platform_user DROP COLUMN can_download')
        self.db.execute('ALTER TABLE platform_user DROP COLUMN can_manage_media')
        self.accounts.initialize()
        current=self.accounts.actor_by_id(self.alice.id)
        self.assertTrue(current.can_download)
        self.assertFalse(current.can_manage_media)
        self.assertEqual(current.username,'alice')

    def test_new_user_capabilities_are_visible_in_web_login_and_user_management(self):
        created=self.accounts.create_user(self.admin,'viewer','viewer-password-123',
                                         can_download=False,can_manage_media=True)
        _,_,actor=self.accounts.login('viewer','viewer-password-123')
        self.assertFalse(actor.can_download);self.assertTrue(actor.can_manage_media)
        saved=next(row for row in self.accounts.users(self.admin) if row['id']==created['id'])
        self.assertEqual(saved['can_download'],0);self.assertEqual(saved['can_manage_media'],1)

    def test_setup_status_exposes_only_initialization_state(self):
        app=create_app(self.accounts,self.records)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            self.assertEqual(client.get('/api/auth/setup-status').json()['data'],{'initialized':True})
            self.db.execute('DELETE FROM platform_user')
            self.assertEqual(client.get('/api/auth/setup-status').json()['data'],{'initialized':False})

    def test_generic_login_errors_and_password_change_invalidates_sessions(self):
        for name in ('missing', 'alice'):
            with self.assertRaisesRegex(ValueError, 'invalid_credentials'):
                self.accounts.login(name, 'wrong-password-123')
        token, _, actor = self.accounts.login('alice', 'alice-password-123')
        self.accounts.change_password(actor, 'alice-password-123', 'new-password-456')
        with self.assertRaisesRegex(ValueError, 'authentication_required'):
            self.accounts.authenticate(token)
        self.accounts.login('alice', 'new-password-456')

    def test_peer_login_limit_cannot_be_evaded_by_changing_usernames(self):
        for index in range(10):
            with self.assertRaisesRegex(ValueError, 'invalid_credentials'):
                self.accounts.login(f'unknown{index}', 'wrong-password-123', '192.0.2.1')
        with self.assertRaisesRegex(ValueError, 'login_rate_limited'):
            self.accounts.login('alice', 'alice-password-123', '192.0.2.1')

    def test_owner_grants_legacy_privacy_and_cross_user_plan_denial(self):
        alice = PlatformService(self.alice, self.accounts, self.records)
        bob = PlatformService(self.bob, self.accounts, self.records)
        legacy = self.records.put('acquisition', {}, 'queued')
        owned = alice.service.records.put('acquisition', {'identity':{'title_id':'movie:1'}}, 'queued')
        self.assertEqual(alice.job(owned['id'])['owner_id'], self.alice.id)
        self.assertEqual(len(bob.jobs()['jobs']), 0)
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            bob.job(owned['id'])
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            alice.job(legacy['id'])
        plan = alice.service.records.put('plan', {'expires_at':9999999999})
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            bob.start(plan['id'], 1, 'shared-client-key')
        self.accounts.grant(self.admin, 'task', owned['id'], self.bob.id, 'read')
        self.assertEqual(bob.job(owned['id'])['job_id'], owned['id'])
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            bob.retry(owned['id'], 1)
        self.accounts.grant(self.admin, 'task', owned['id'], self.bob.id, 'none')
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            bob.job(owned['id'])
        self.assertNotEqual(alice._key('shared-client-key'), bob._key('shared-client-key'))
        self.assertEqual(len(self.accounts.events(self.bob)), 2)

    def test_http_requires_session_csrf_and_rejects_actor_forgery(self):
        app = create_app(self.accounts, self.records)
        with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234)) as client:
            self.assertEqual(client.get('/api/auth/me').status_code, 401)
            response = client.post('/api/auth/login', json={'username':'alice','password':'alice-password-123'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('HttpOnly', response.headers['set-cookie'])
            csrf = response.json()['data']['csrf']
            command = {'operation':'jobs','arguments':{}}
            self.assertEqual(client.post('/api/command', json=command).status_code, 403)
            headers = {'x-csrf-token':csrf}
            self.assertEqual(client.post('/api/command', json=command, headers=headers).status_code, 200)
            forged = {'operation':'jobs','arguments':{'actor_id':self.admin.id}}
            self.assertEqual(client.post('/api/command', json=forged, headers=headers).status_code, 400)
            cross = {**headers, 'origin':'https://attacker.invalid'}
            self.assertEqual(client.post('/api/command', json=command, headers=cross).status_code, 403)
            self.assertEqual(client.get('/api/users').status_code, 403)
            self.assertEqual(client.post('/api/auth/logout', json={}, headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/auth/me').status_code, 401)

    def test_public_web_requires_exact_hosts(self):
        with patch.dict(os.environ, {'MEDIA_WEB_PUBLIC':'true','MEDIA_ALLOWED_HOSTS':''}):
            with self.assertRaisesRegex(ValueError, 'exact_allowed_hosts'):
                create_app(self.accounts, self.records)

    def test_mcp_token_uses_same_user_and_revokes_with_password_or_account(self):
        token = self.accounts.create_api_token(self.alice, 'test-client')
        actor, expiry = self.accounts.verify_api_token(token['token'])
        self.assertEqual(actor.id, self.alice.id)
        self.assertGreater(expiry, self.accounts.clock())
        self.assertNotIn('token', self.accounts.api_tokens(self.alice)[0])
        self.accounts.revoke_api_token(self.bob, token['id'])
        self.accounts.verify_api_token(token['token'])
        self.accounts.revoke_api_token(self.alice, token['id'])
        with self.assertRaisesRegex(ValueError, 'authentication_required'):
            self.accounts.verify_api_token(token['token'])
        token = self.accounts.create_api_token(self.alice, 'test-client')
        self.accounts.change_password(self.alice, 'alice-password-123', 'new-password-456')
        self.assertEqual(self.accounts.api_tokens(self.alice), [])
        with self.assertRaisesRegex(ValueError, 'authentication_required'):
            self.accounts.verify_api_token(token['token'])

    def test_media_read_grant_does_not_authorize_subtitle_mutation(self):
        from media_mcp.storage.media import upsert_media_link, upsert_media_subtitle
        source = Path(os.environ['MEDIA_DOWNLOAD_ROOT'])/'fixture.mkv'
        target = Path(os.environ['MEDIA_LIBRARY_ROOT'])/'fixture.mkv'
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        source.write_bytes(b'fixture')
        os.link(source,target)
        upsert_media_link(None,str(source),str(target),media_type='movie',media_tmdb_id=1,status='linked')
        upsert_media_subtitle(None,'fixture.srt','fixture.zh.srt',matched_video_target_path=str(target),
                             language='zh-CN',status='linked',format='srt')
        media_id = self.db.execute('SELECT id FROM media_link').scalar()
        service = PlatformService(self.bob,self.accounts,self.records)
        self.assertEqual(service.media()['media'],[])
        self.accounts.grant(self.admin,'media',str(media_id),self.bob.id,'read')
        visible = service.media()['media'][0]
        self.assertNotIn('source_path',visible)
        self.assertEqual(visible['subtitles'][0]['language'],'zh-CN')
        with self.assertRaisesRegex(ValueError,'linked_media_not_found'):
            service.subtitles(media_id,'subtitle-request-001')
        self.accounts.grant(self.admin,'media',str(media_id),self.bob.id,'manage')
        with self.assertRaisesRegex(ValueError,'linked_media_not_found'):
            service.subtitles(media_id,'subtitle-request-001')
        self.accounts.update_user(self.admin,self.bob.id,enabled=True,role='user',can_manage_media=True)
        service=PlatformService(self.accounts.actor_by_id(self.bob.id),self.accounts,self.records)
        self.assertEqual(service.subtitles(media_id,'subtitle-request-001')['stage'],'enqueue_processing')
