"""Public-indexer administration with server-owned credentials and bounded requests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
import requests

from media_mcp.adapters.jackett import Jackett
from media_mcp.storage.indexer_settings import IndexerSettings


class JackettAdmin:
    def __init__(self, jackett=None, session=None, settings=None):
        self.jackett = jackett or Jackett(remote=False)
        self.session = session or requests.Session()
        self.settings = settings or IndexerSettings()
        self.lock = threading.RLock()

    def _request(self, method, path, *, admin=False, **kwargs):
        if not self.jackett.configured:
            raise ValueError('jackett_not_configured')
        try:
            response = self.session.request(method, self.jackett.base+path, timeout=25,
                                            allow_redirects=False, **kwargs)
            if admin and response.status_code in (301,302,401,403):
                self._login()
                response = self.session.request(method, self.jackett.base+path, timeout=25,
                                                allow_redirects=False, **kwargs)
            if response.status_code in (301,302,401,403):
                raise ValueError('jackett_admin_auth_required')
            if not response.ok:
                raise ValueError('jackett_operation_failed')
            if len(response.content)>4*1024*1024:
                raise ValueError('jackett_invalid_response')
            return response
        except requests.Timeout:
            raise ValueError('jackett_timeout') from None
        except requests.RequestException:
            raise ValueError('jackett_connection_failed') from None

    def _login(self):
        password = os.environ.get('JACKETT_ADMIN_PASSWORD')
        path = Path(os.environ.get('JACKETT_ADMIN_PASSWORD_FILE') or self.settings.path.parent/'jackett-admin-password')
        if password is None:
            try:password=path.read_text().rstrip('\r\n')
            except FileNotFoundError:password=''
        self.session.post(self.jackett.base+'/UI/Dashboard', data={'password':password},
                          timeout=15, allow_redirects=False)

    def inventory(self):
        response = self._request('GET','/api/v2.0/indexers/all/results/torznab/api',
            params={'apikey':self.jackett.key,'t':'indexers'})
        try:
            root = ElementTree.fromstring(response.content)
        except (ValueError, ElementTree.ParseError, DefusedXmlException):
            raise ValueError('jackett_invalid_response') from None
        if root.tag!='indexers':raise ValueError('jackett_invalid_response')
        settings = self.settings.get()
        rows=[]
        for item in root.findall('indexer'):
            site=item.get('id','')
            if item.findtext('type')!='public' or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',site):continue
            configured=item.get('configured')=='true'
            rows.append({'id':site,'name':item.findtext('title') or site,'language':item.findtext('language') or '',
                         'configured':configured,'enabled':configured and site not in settings['disabled'],
                         'test':settings['tests'].get(site)})
        return {'indexers':sorted(rows,key=lambda row:(not row['configured'],row['name'].lower())),
                'revision':settings['revision']}

    def _public(self, site):
        row=next((row for row in self.inventory()['indexers'] if row['id']==site),None)
        if row is None:raise ValueError('jackett_public_indexer_required')
        return row

    @staticmethod
    def _revision(config):
        return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _fields(config):
        # Hidden/password/cookie fields never leave the service, including public-site settings.
        return [item for item in config if item.get('type') in ('inputbool','inputselect')
                and not re.search(r'password|cookie|token|apikey|passkey|secret',item.get('id','')+' '+item.get('name',''),re.I)]

    def _configuration(self, site):
        response=self._request('GET',f'/api/v2.0/indexers/{site}/Config',admin=True)
        try:
            raw=response.json()
        except ValueError:
            raise ValueError('jackett_invalid_response') from None
        if not isinstance(raw,list) or not all(isinstance(item,dict) for item in raw):
            raise ValueError('jackett_invalid_response')
        return raw

    def configuration(self, site):
        row=self._public(site)
        raw=self._configuration(site)
        fields=[{key:item[key] for key in ('id','name','type','value','options') if key in item}
                for item in self._fields(raw)]
        return {'id':site,'configured':row['configured'],'revision':self._revision(raw),'fields':fields}

    def invoke(self, action, site=None, *, enabled=None, revision=None, values=None, confirm=False):
        with self.lock:
            if action=='list':return self.inventory()
            if action=='configuration':return self.configuration(site)
            row=self._public(site)
            if action=='enabled':
                if not row['configured']:raise ValueError('jackett_indexer_not_configured')
                def update(settings):
                    disabled=set(settings['disabled'])
                    disabled.discard(site) if enabled else disabled.add(site)
                    settings['disabled']=sorted(disabled)
                self.settings.update(update,revision)
                return self.inventory()
            if action=='save':
                raw=self._configuration(site)
                if self._revision(raw)!=revision:raise ValueError('jackett_settings_changed')
                editable={item['id']:item for item in self._fields(raw)}
                for key,value in (values or {}).items():
                    field=editable.get(key)
                    if not field:raise ValueError('invalid_request')
                    if field['type']=='inputbool' and type(value) is not bool:raise ValueError('invalid_request')
                    if field['type']=='inputselect' and value not in field.get('options',{}):raise ValueError('invalid_request')
                payload=[]
                for item in raw:
                    if 'value' in item or 'values' in item:
                        field={key:copy.deepcopy(item[key]) for key in ('id','value','values') if key in item}
                        if item['id'] in (values or {}):field['value']=values[item['id']]
                        payload.append(field)
                self._request('POST',f'/api/v2.0/indexers/{site}/Config',admin=True,json=payload)
            elif action=='remove':
                if not confirm:raise ValueError('confirmation_required')
                raw=self._configuration(site)
                if self._revision(raw)!=revision:raise ValueError('jackett_settings_changed')
                if not row['configured']:raise ValueError('jackett_indexer_not_configured')
                self._request('DELETE',f'/api/v2.0/indexers/{site}',admin=True)
            elif action=='test':
                if not row['configured']:raise ValueError('jackett_indexer_not_configured')
                try:
                    self._request('POST',f'/api/v2.0/indexers/{site}/Test',admin=True)
                    status='passed'
                except ValueError as exc:
                    if str(exc)=='jackett_admin_auth_required':raise
                    status=str(exc)
                self.settings.update(lambda settings:settings['tests'].update({site:{'status':status,'tested_at':time.time()}}))
            else:raise ValueError('invalid_request')
            return self.inventory()
