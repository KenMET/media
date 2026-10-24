"""Compute v1 infohash from the exact bencoded info bytes, with bounded parsing."""
import hashlib
import re
from urllib.parse import parse_qs, urlsplit


def infohash(content=None, magnet=None):
    if magnet:
        from base64 import b32decode
        for xt in parse_qs(urlsplit(magnet).query).get('xt', []):
            value = xt.removeprefix('urn:btih:')
            if xt.startswith('urn:btih:') and re.fullmatch('[a-fA-F0-9]{40}', value):
                return value.lower()
            if xt.startswith('urn:btih:') and re.fullmatch('[A-Za-z2-7]{32}', value):
                return b32decode(value.upper()).hex()
        raise ValueError('v1_infohash_required')
    if not content or len(content) > 8 * 1024 * 1024 or content[:1] != b'd':
        raise ValueError('invalid_torrent')
    index, captured = 0, None
    def parse(depth=0):
        nonlocal index, captured
        if depth > 40 or index >= len(content):
            raise ValueError('invalid_torrent')
        token = content[index:index+1]
        if token in (b'd', b'l'):
            index += 1
            keys = set()
            while index < len(content) and content[index:index+1] != b'e':
                if token == b'd':
                    key = parse(depth+1)
                    if not isinstance(key, bytes) or key in keys:
                        raise ValueError('invalid_torrent_dictionary')
                    keys.add(key)
                    start = index
                    value = parse(depth+1)
                    if depth == 0 and key == b'info':
                        if content[start:start+1] != b'd':
                            raise ValueError('invalid_torrent_info')
                        captured = content[start:index]
                else:
                    parse(depth+1)
            if index >= len(content):
                raise ValueError('invalid_torrent')
            index += 1
            return None
        if token == b'i':
            end = content.index(b'e', index)
            value = int(content[index+1:end]); index = end+1
            return value
        colon = content.index(b':', index)
        size = int(content[index:colon])
        if size < 0 or colon+1+size > len(content):
            raise ValueError('invalid_torrent')
        index = colon+1+size
        return content[colon+1:index]
    try:
        parse()
    except (IndexError, ValueError):
        raise ValueError('invalid_torrent') from None
    if index != len(content) or not captured:
        raise ValueError('invalid_torrent')
    return hashlib.sha1(captured).hexdigest()
