"""Bounded Torznab search. Download URLs never leave the service boundary."""
import os
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urljoin
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
import requests


class Jackett:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.base = os.environ.get('JACKETT_URL', 'http://127.0.0.1:18212').rstrip('/')
        self.key = os.environ.get('JACKETT_API_KEY', '')

    @property
    def configured(self):
        if not self.key:
            try:
                config=json.loads(Path(os.environ.get('JACKETT_CONFIG_FILE','/services/jackett/Jackett/ServerConfig.json')).read_text())
                self.key=config.get('APIKey') or ''
            except (OSError,ValueError):pass
        return bool(self.base and self.key)

    def search(self, query, kind=None):
        """Query each configured site separately; one failed site must not hide others."""
        if not self.configured:
            raise RuntimeError('jackett_not_configured')
        config = Path(os.environ.get('JACKETT_CONFIG_FILE', '/services/jackett/Jackett/ServerConfig.json'))
        sites = sorted(p.stem for p in (config.parent / 'Indexers').glob('*.json')
                       if re.fullmatch(r'[a-zA-Z0-9_-]+', p.stem))
        if not sites:
            return {'releases': [], 'diagnostics': [{'site': None, 'status': 'no_configured_sites', 'raw_count': 0}]}
        rows, diagnostics = [], []
        deadline = time.monotonic() + 20
        for site in sites:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                diagnostics.append({'site': site, 'status': 'budget_exhausted', 'raw_count': 0})
                continue
            try:
                found = self._search_site(query, site, kind, min(5, remaining))
            except RuntimeError as exc:
                diagnostics.append({'site': site, 'status': str(exc), 'raw_count': 0})
                continue
            rows.extend(found)
            diagnostics.append({'site': site, 'status': 'ok', 'raw_count': len(found)})
        return {'releases': rows, 'diagnostics': diagnostics}

    def _search_site(self, query, site, kind, timeout):
        if not self.configured:
            raise RuntimeError('jackett_not_configured')
        try:
            params = {'apikey': self.key, 't': 'search', 'q': query, 'limit': 50}
            if kind in ('movie', 'tv'):
                params['cat'] = 2000 if kind == 'movie' else 5000
            response = self.session.get(self.base + f'/api/v2.0/indexers/{site}/results/torznab/api',
                params=params, timeout=timeout, allow_redirects=False, stream=True)
            try:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise ValueError('indexer_response_too_large')
                    chunks.append(chunk)
                tree = ElementTree.fromstring(b''.join(chunks))
            finally:
                response.close()
        except requests.Timeout:
            raise RuntimeError('jackett_timeout') from None
        except (requests.RequestException, ValueError, ElementTree.ParseError, DefusedXmlException):
            raise RuntimeError('jackett_search_failed') from None
        if tree.tag=='error':
            raise RuntimeError('jackett_auth_or_query_failed')
        if tree.tag != 'rss':
            raise RuntimeError('jackett_invalid_response')
        rows = []
        for item in tree.findall('.//item')[:50]:
            attrs = {node.attrib.get('name'): node.attrib.get('value') for node in item
                     if node.tag.endswith('attr')}
            enclosure = item.find('enclosure')
            url = item.findtext('link') or (enclosure.get('url') if enclosure is not None else '')
            if not url:
                continue
            title = (item.findtext('title') or '')[:1000]
            size = item.findtext('size') or (enclosure.get('length') if enclosure is not None else None)
            rows.append({'name': title, 'size': int(size) if size and size.isdigit() else None,
                         'seeders': int(attrs['seeders']) if (attrs.get('seeders') or '').isdigit() else None,
                         'resolution': next((n for n in (2160, 1080, 720, 480) if re.search(rf'(?<!\d){n}[pi](?!\w)', title, re.I)), None),
                         'indexer': item.findtext('jackettindexer') or site,
                         'indexer_id': site,
                         'categories': [int(n.attrib['value']) for n in item
                                        if n.tag.endswith('attr') and n.attrib.get('name') == 'category'
                                        and n.attrib.get('value', '').isdigit()],
                         'download_url': url, 'claimed_infohash': attrs.get('infohash')})
        return rows

    def torrent(self, url):
        """Return torrent bytes, a validated redirected magnet, or None for a direct magnet."""
        if url.startswith('magnet:?'):
            return None
        # Follow only same-origin proxy hops. A magnet is data, never an HTTP request.
        trusted = urlsplit(self.base)
        visited = set()
        try:
            for hop in range(4):
                target = urlsplit(url)
                if ((target.scheme, target.netloc) != (trusted.scheme, trusted.netloc)
                        or target.username or target.password):
                    raise ValueError('untrusted_indexer_download_url')
                if url in visited:
                    raise ValueError('indexer_redirect_loop')
                visited.add(url)
                with self.session.get(url, timeout=30, stream=True, allow_redirects=False) as response:
                    response.raise_for_status()
                    if 300 <= response.status_code < 400:
                        location = response.headers.get('Location', '').strip()
                        if not location or len(location) > 16384 or any(ord(c) < 32 for c in location):
                            raise ValueError('indexer_invalid_redirect')
                        if location.startswith('magnet:?'):
                            from media_mcp.adapters.torrent import infohash
                            infohash(magnet=location)
                            return location
                        redirected = urlsplit(urljoin(url, location))
                        if ((redirected.scheme, redirected.netloc) != (trusted.scheme, trusted.netloc)
                                or redirected.username or redirected.password):
                            raise ValueError('indexer_redirect_not_allowed')
                        if hop == 3:
                            raise ValueError('indexer_redirect_limit')
                        url = urljoin(url, location)
                        continue
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            raise ValueError('torrent_too_large')
                        chunks.append(chunk)
                    return b''.join(chunks)
        except requests.RequestException:
            raise RuntimeError('torrent_fetch_failed') from None
