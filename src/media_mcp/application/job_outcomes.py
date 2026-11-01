"""Read-only delivery outcomes; retained library links never bypass review fences."""
import json
import os
from pathlib import Path

from media_mcp.config import contained, parse_title_id


RETAINED_REASONS = {'lower_or_equal_quality', 'quality_not_comparable'}


def refresh_job_outcome(db, row, public):
    data = row['data']
    key = data.get('delivery_hash')
    if key and db.table_exists('media_processing_job'):
        current = [dict(item) for item in db.execute(
            'SELECT stage,state,error,result_json FROM media_processing_job WHERE delivery_key=:key ORDER BY id',
            {'key':key}).mappings().all()]
        if current:public['processing']=current
    ingest = next((item for item in public.get('processing') or [] if item['stage']=='ingest'), None)
    if not ingest or ingest['state'] not in ('needs_review','succeeded'):
        return
    source = data.get('source_path')
    identity = data.get('identity') or {}
    if not isinstance(source,str) or not source or data.get('workflow') == 'subtitle' or not db.table_exists('media_link'):
        return
    try:
        kind, ident = parse_title_id(identity.get('title_id', ''))
    except (TypeError, ValueError):
        return
    matches = db.execute('''SELECT c.id,c.season,c.episode,c.reason,
        l.source_path,l.target_path,l.reason AS library_reason FROM media_link c JOIN media_link l
        ON l.media_type=c.media_type AND l.media_tmdb_id=c.media_tmdb_id
        AND (l.season=c.season OR l.season IS NULL AND c.season IS NULL)
        AND (l.episode=c.episode OR l.episode IS NULL AND c.episode IS NULL)
        WHERE c.media_type=:kind AND c.media_tmdb_id=:ident AND c.status='unlinked'
        AND (c.source_path=:source OR substr(c.source_path,1,LENGTH(:prefix))=:prefix)
        AND l.status='linked' AND l.target_path!='' ORDER BY c.id,l.id LIMIT 300''',
        {'kind':kind,'ident':ident,'source':source,'prefix':source.rstrip('/')+'/'}).mappings().all()
    items, seen = [], set()
    scope = data.get('scope') or {}
    library_root = Path(os.environ.get('MEDIA_LIBRARY_ROOT', '/data/media_hub'))
    for match in matches:
        reason = (match['reason'] or '').split(';',1)[0]
        if reason not in RETAINED_REASONS or match['id'] in seen:
            continue
        if kind == 'tv' and (match['season'] != scope.get('season') or match['episode'] not in (scope.get('episodes') or [])):
            continue
        try:
            old_source = contained(match['source_path'])
            target = contained(match['target_path'], library_root)
            if not target.is_file() or not os.path.samefile(old_source, target):
                continue
        except (OSError, ValueError):
            continue
        seen.add(match['id'])
        items.append({'name':target.name, 'season':match['season'], 'episode':match['episode'],
                      'reason':reason, 'identity_unverified':'identity_unverified' in (match['library_reason'] or '')})
    if not items:
        return
    subtitle = next((item for item in public.get('processing', []) if item['stage']=='subtitle'), None)
    subtitle_result = {}
    if subtitle:
        try:
            subtitle_result = json.loads(subtitle.get('result_json') or '{}')
        except (ValueError, TypeError):
            pass
    if not isinstance(subtitle_result,dict):subtitle_result={}
    try:
        ingest_result=json.loads(ingest.get('result_json') or '{}')
    except (ValueError,TypeError):
        ingest_result={}
    explains_review=(ingest.get('error')=='no_media_processed' and isinstance(ingest_result,dict)
                     and ingest_result.get('failed')==0 and ingest_result.get('review')==0
                     and not any(item.get('error') or item['state']=='needs_review'
                                 for item in public.get('processing',[]) if item['stage']!='ingest'))
    public['library_outcome'] = {'explains_review':explains_review, 'retained_count':len(items), 'quality_review':any(
        item['reason']=='quality_not_comparable' for item in items), 'items':items,
        'subtitle_no_media':bool(subtitle and subtitle['state']=='succeeded' and subtitle_result.get('media_count')==0)}
