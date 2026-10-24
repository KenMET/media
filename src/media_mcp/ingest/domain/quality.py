"""Conservative quality comparison: measured video first, release labels second."""
from __future__ import annotations
import json
import os
import re
import subprocess


def probe_quality(path: str, release_path: str | None = None) -> dict:
    name = os.path.basename(release_path or path).lower()
    source = next((rank for pattern, rank in (
        (r'\bremux\b', 4), (r'blu[ ._-]?ray|bdrip', 3),
        (r'web[ ._-]?dl', 2), (r'webrip|hdtv', 1)) if re.search(pattern,name)), None)
    result = {'height': None, 'width': None, 'duration': None, 'codec': None, 'bitrate': None,
              'source_rank': source, 'revision': 1 if re.search(r'\b(proper|repack)\b',name) else 0}
    try:
        response = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
            '-show_entries','stream=width,height,codec_name,bit_rate:format=duration','-of','json',path],
            capture_output=True,text=True,timeout=30,check=True)
        payload = json.loads(response.stdout)
        stream = payload['streams'][0]
        for field in ('height','width'):
            result[field] = int(stream[field]) if int(stream.get(field) or 0)>0 else None
        result['codec'] = stream.get('codec_name')
        result['bitrate'] = int(stream['bit_rate']) if str(stream.get('bit_rate','')).isdigit() else None
        result['duration'] = float(payload.get('format',{}).get('duration') or 0) or None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        pass
    return result


def compare_quality(candidate: dict, current: dict) -> int | None:
    """1/-1 means demonstrably better/worse; unknown or equal never overwrites."""
    durations = (candidate.get('duration'), current.get('duration'))
    if not all(durations) or abs(durations[0]-durations[1])/max(durations) > .05:
        return None  # Different cuts/incomplete files are not interchangeable.
    candidate = {**candidate,'resolution':max(candidate.get('width') or 0,candidate.get('height') or 0) or None}
    current = {**current,'resolution':max(current.get('width') or 0,current.get('height') or 0) or None}
    for key in ('resolution','source_rank'):
        left,right = candidate.get(key), current.get(key)
        if left is None or right is None:
            return None
        if left != right:
            return 1 if left>right else -1
    if candidate.get('revision') != current.get('revision'):
        return 1 if candidate['revision']>current['revision'] else -1
    # Codec and container names or bytes alone do not establish picture quality.
    return 0
