"""Public-only administration against a fake Jackett and disposable private state."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from media_mcp.adapters.jackett import Jackett
from media_mcp.adapters.jackett_admin import JackettAdmin
from media_mcp.platform.indexers import IndexerCommand, invoke_indexer
from media_mcp.storage.indexer_settings import IndexerSettings


class FakeJackett:
    def __init__(self):
        self.sites={'public':('public',True),'available':('public',False),'private':('private',True),'semi':('semi-private',True)}
        self.config=[{'id':'freeleech','name':'Freeleech','type':'inputbool','value':False},
                     {'id':'mirror','name':'Mirror','type':'inputselect','value':'one','options':{'one':'One','two':'Two'}},
                     {'id':'password','type':'inputpassword','value':'secret-fixture'},
                     {'id':'cookie','type':'hiddendata','value':'cookie-fixture'}]
        self.authorized=True;self.calls=[];self.test_failed=False

    @staticmethod
    def response(status=200,body=None):
        response=requests.Response();response.status_code=status
        response._content=body if isinstance(body,bytes) else json.dumps(body).encode()
        return response

    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        if 'torznab' in url:
            xml='<indexers>'+''.join(f'<indexer id="{name}" configured="{str(configured).lower()}"><title>{name}</title><type>{kind}</type><language>en-US</language></indexer>' for name,(kind,configured) in self.sites.items())+'</indexers>'
            return self.response(body=xml.encode())
        if not self.authorized:return self.response(302)
        site=url.split('/indexers/')[1].split('/')[0]
        if method=='GET':return self.response(body=self.config)
        if method=='DELETE':self.sites[site]=(self.sites[site][0],False);return self.response(204)
        if url.endswith('/Test'):return self.response(500 if self.test_failed else 204)
        if method=='POST':
            for item in self.config:
                incoming=next((row for row in kwargs['json'] if row['id']==item['id']),None)
                if incoming:item.update(incoming)
            self.sites[site]=(self.sites[site][0],True)
            return self.response(204)
        raise AssertionError('Unexpected fake request')

    def post(self,url,data,**kwargs):
        self.authorized=data['password']=='fixture-password'
        return self.response(302)


class JackettAdminTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{'MEDIA_DB_PATH':str(self.root/'state/media.sqlite3'),'JACKETT_ADMIN_PASSWORD_FILE':str(self.root/'password'),'MEDIA_EXECUTION_ONLY':'false','JACKETT_API_KEY':'fixture-key'})
        env.start();self.addCleanup(env.stop)
        self.settings=IndexerSettings();self.fake=FakeJackett()
        self.manager=JackettAdmin(SimpleNamespace(configured=True,base='http://jackett.test',key='fixture-key'),self.fake,self.settings)

    def test_inventory_filters_private_sites_and_never_returns_credentials(self):
        result=self.manager.invoke('list')
        self.assertEqual([row['id'] for row in result['indexers']],['public','available'])
        self.assertNotIn('fixture-key',json.dumps(result));self.assertNotIn('cookie-fixture',json.dumps(result))
        for action in ('configuration','save','remove','enabled','test'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'jackett_public_indexer_required'):
                self.manager.invoke(action,'private')

    def test_inventory_loads_private_config_key_before_building_request(self):
        config=self.root/'ServerConfig.json'
        config.write_text(json.dumps({'APIKey':'lazy-fixture-key'}))
        with patch.dict(os.environ,{'JACKETT_API_KEY':'','JACKETT_CONFIG_FILE':str(config)}):
            manager=JackettAdmin(Jackett(remote=False),self.fake,self.settings)
            manager.inventory()
        self.assertEqual(self.fake.calls[0][2]['params']['apikey'],'lazy-fixture-key')

    def test_configuration_add_stale_edit_and_confirmed_remove(self):
        config=self.manager.invoke('configuration','available')
        self.assertEqual([field['id'] for field in config['fields']],['freeleech','mirror'])
        self.assertNotIn('secret-fixture',json.dumps(config))
        result=self.manager.invoke('save','available',revision=config['revision'],values={'freeleech':True,'mirror':'two'})
        self.assertTrue(next(row for row in result['indexers'] if row['id']=='available')['configured'])
        with self.assertRaisesRegex(ValueError,'jackett_settings_changed'):
            self.manager.invoke('save','available',revision=config['revision'])
        config=self.manager.invoke('configuration','available')
        with self.assertRaisesRegex(ValueError,'confirmation_required'):
            self.manager.invoke('remove','available',revision=config['revision'])
        self.manager.invoke('remove','available',revision=config['revision'],confirm=True)
        self.assertFalse(self.fake.sites['available'][1]);self.assertTrue(self.fake.sites['private'][1])
        self.assertEqual(next(row for row in self.fake.config if row['id']=='password')['value'],'secret-fixture')

    def test_disabled_search_survives_restart_and_is_used_by_real_search_adapter(self):
        self.manager.invoke('enabled','public',enabled=False,revision=0)
        self.assertIn('public',IndexerSettings().get()['disabled'])
        with self.assertRaisesRegex(ValueError,'jackett_settings_changed'):
            self.manager.invoke('enabled','public',enabled=True,revision=0)
        config=self.root/'Jackett/ServerConfig.json';config.parent.mkdir();config.write_text('{}')
        sites=config.parent/'Indexers';sites.mkdir()
        for site in ('public','private'):(sites/(site+'.json')).write_text('{}')
        with patch.dict(os.environ,{'JACKETT_CONFIG_FILE':str(config)}):
            adapter=Jackett(remote=False);adapter._search_site=Mock(return_value=[])
            result=adapter.search('Example')
        self.assertEqual([row['site'] for row in result['diagnostics']],['private'])

    def test_tests_record_safe_status_and_missing_login_is_explicit(self):
        self.fake.test_failed=True
        result=self.manager.invoke('test','public')
        self.assertEqual(next(row for row in result['indexers'] if row['id']=='public')['test']['status'],'jackett_operation_failed')
        self.fake.authorized=False
        with patch.dict(os.environ,{'JACKETT_ADMIN_PASSWORD':''}),self.assertRaisesRegex(ValueError,'jackett_admin_auth_required'):
            self.manager.invoke('configuration','public')
        (self.root/'password').write_text('fixture-password\n')
        with patch.dict(os.environ,{},clear=False):
            self.manager.invoke('configuration','public')

    def test_schema_requires_confirmation_and_rejects_paths_and_unknown_fields(self):
        from pydantic import ValidationError
        for payload in ({'action':'remove','site':'public','revision':'a'*64},
                        {'action':'test','site':'../private'},
                        {'action':'enabled','site':'public','enabled':False},
                        {'action':'test','site':'public','delete_files':True}):
            with self.subTest(payload=payload),self.assertRaises(ValidationError):IndexerCommand.model_validate(payload)
        self.assertEqual(invoke_indexer(self.manager,IndexerCommand(action='list'))['revision'],0)
