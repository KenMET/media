"""One durable media/subtitle summary per work/season and processing round."""
import json
import os
import time
import uuid

from media_mcp.storage.records import Records
from media_mcp.application.collections import READY_SUBTITLE_STATUSES, digest

TERMINAL={'completed','completed_with_warnings','needs_review','failed','cancelled'}
READY=READY_SUBTITLE_STATUSES|{'embedded_default_set','copied','audio_transcribed','audio_translated'}


def group_files(files):
    groups={}
    for file in files:
        kind=file.get('media_type');tmdb=file.get('media_tmdb_id')
        if kind not in ('movie','tv') or not tmdb:continue
        season=file.get('season') if kind=='tv' else None
        episode=file.get('episode') if kind=='tv' else None
        if kind=='tv' and (season is None or episode is None):continue
        group=groups.setdefault((kind,tmdb,season),{'kind':kind,'tmdb':tmdb,'season':season,
            'label':file.get('media_name') or file.get('base_title') or f'{kind}:{tmdb}','episodes':set()})
        group['episodes'].add(episode)
    return list(groups.values())


def snapshot(records,group):
    expected=set(group['episodes']);linked=set();subtitled=set()
    for row in records.db.execute("""SELECT * FROM media_link WHERE media_type=:kind AND media_tmdb_id=:tmdb
        AND (:kind='movie' OR season=:season) AND status='linked'""",group).mappings():
        episode=row['episode'] if group['kind']=='tv' else None
        if episode not in expected:continue
        source,target=row['source_path'],row['target_path']
        try:
            if os.path.islink(source) or os.path.islink(target) or not os.path.samefile(source,target):continue
        except OSError:continue
        linked.add(episode)
        for subtitle in records.db.execute("""SELECT target_subtitle_path,status,source_type,stream_index FROM media_subtitle
            WHERE matched_video_target_path=:target AND matched_video_source_path=:source""",{'target':target,'source':source}).mappings():
            subtitle_path=subtitle['target_subtitle_path'] or ''
            embedded=subtitle['source_type']=='embedded' and subtitle_path==target+f"#stream:{subtitle['stream_index']}"
            if subtitle['status'] in READY and (embedded or os.path.isfile(subtitle_path) and not os.path.islink(subtitle_path)):
                subtitled.add(episode);break
    total=len(expected)
    label={'tv':'Series ','movie':'Movie '}.get(group['kind'],'Unidentified media ')+str(group['label'])
    if group['kind']=='tv':label+=f" S{group['season']:02d}"
    content=f'{label}\nLibrary videos: {len(linked)}/{total}. Subtitles ready: {len(subtitled)}/{total}.'
    unresolved=expected-subtitled
    if unresolved:content+=f'\nNeeds attention: {len(unresolved)}. See the task page for missing media or subtitles.'
    return {'content':content,'total':total,'ingested':len(linked),'subtitles':len(subtitled),'unresolved':len(unresolved)}


def _send(records,row,sender):
    # A timeout may mean Bark accepted the push. Never blindly replay an unknown send.
    row=records.update(row,'sending',{**row['data'],'attempted_at':time.time()})
    try:sent=bool(sender('Media processing summary',row['data']['content']))
    except Exception:sent=False
    records.update(row,'delivered' if sent else 'delivery_unknown',row['data'])


def enqueue(records,round_id,groups,*,send=False,sender=None):
    if sender is None:
        from media_mcp.adapters.notify import send_notification
        sender=send_notification
    with records.db.lock('media-notifications',timeout=5):
        for group in groups:
            key=digest(['media-summary',round_id,group['kind'],group['tmdb'],group['season']])
            row=records.by_key(key)
            if row:continue
            row=records.put('media_notice',{'round_id':round_id,**snapshot(records,group)},'pending',key)
            if send:_send(records,row,sender)


def notify_path(path,*,media_links=None,unresolved=0,sender=None):
    """Standalone entrypoints finish both phases before publishing grouped summaries."""
    from media_mcp.storage.media import _client
    records=Records(_client(None));records.initialize()
    if media_links is None:
        media_links=records.db.execute("""SELECT * FROM media_link WHERE source_path=:path
            OR substr(source_path,1,LENGTH(:prefix))=:prefix""",{'path':path,'prefix':path.rstrip('/')+'/'}).mappings().all()
    groups=group_files(media_links)
    if not groups and unresolved:
        groups=[{'kind':'unknown','tmdb':None,'season':None,'label':os.path.basename(path.rstrip('/')),
            'episodes':set(range(unresolved))}]
    enqueue(records,'direct:'+uuid.uuid4().hex,groups,send=True,sender=sender)


def processing_round(root):
    data=root['data']
    generation=data.get('notification_round',0)
    if generation:return f"acquisition:{root['id']}:retry:{generation}"
    parent=data.get('season_request_id')
    return 'season:'+parent+':'+str(data.get('season_run_key') or 'legacy') if parent else 'acquisition:'+root['id']


def reconcile(records):
    policy_key=digest(['media-notification-policy',1])
    policy=records.by_key(policy_key)
    if not policy:
        policy=records.put('media_notice_policy',{'enabled_at':records.db.execute('SELECT CURRENT_TIMESTAMP').scalar()},'enabled',policy_key)
    roots=[records.decode(row) for row in records.db.execute("""SELECT * FROM media_mcp_record
        WHERE kind IN ('acquisition','library_task') AND state!='deleted'""").mappings()]
    fresh={root['id'] for root in roots if str(root['updated_at'])>policy['data']['enabled_at']}
    rounds={processing_round(root) for root in roots if root['id'] in fresh and root['kind']=='acquisition'}
    batches={}
    for root in roots:
        data=root['data']
        if root['kind']=='acquisition':
            identity=data.get('identity') or {};scope=data.get('scope') or {}
            if not identity.get('tmdb_id'):continue
            parent=data.get('season_request_id');run=data.get('season_run_key')
            round_id=processing_round(root)
            if round_id not in rounds:continue
            batch=batches.setdefault(round_id,{'roots':[],'groups':{}});batch['roots'].append(root)
            if parent and not data.get('notification_round'):
                consent=records.get(parent)
                if consent['state']=='active' and consent['data'].get('run_key')==run and consent['data'].get('result_run_key')!=run:
                    batch['planning']=True
            key=(identity['kind'],identity['tmdb_id'],scope.get('season'))
            group=batch['groups'].setdefault(key,{'kind':identity['kind'],'tmdb':identity['tmdb_id'],
                'season':scope.get('season'),'label':identity.get('title') or identity['title_id'],'episodes':set()})
            group['episodes'].update(scope.get('episodes',[]) if identity['kind']=='tv' else [None])
        elif root['id'] in fresh and root['state'] in TERMINAL and not data.get('terminal_notice_event'):
            # Existing urgent quota/authentication notices remain on their original path.
            files=[]
            for file in data.get('files',[]):
                if file.get('title_id'):
                    from media_mcp.config import parse_title_id
                    try:kind,tmdb=parse_title_id(file['title_id'])
                    except ValueError:continue
                    files.append({**file,'media_type':kind,'media_tmdb_id':int(tmdb),
                        'media_name':file.get('media_name') or data.get('label')})
            enqueue(records,'library:'+root['id'],group_files(files))
    for round_id,batch in batches.items():
        if batch.get('planning') or any(root['state'] not in TERMINAL for root in batch['roots']):continue
        # Do not announce a parent task while an owned child stage is still running/retrying.
        keys=[root['data'].get('delivery_hash') for root in batch['roots'] if root['data'].get('delivery_hash')]
        if any(records.db.execute("""SELECT 1 FROM media_processing_job WHERE delivery_key=:key
            AND state IN ('queued','retry','running') LIMIT 1""",{'key':key}).scalar() for key in keys):continue
        enqueue(records,round_id,list(batch['groups'].values()))


def deliver(records=None,sender=None):
    if sender is None:
        from media_mcp.adapters.notify import send_notification
        sender=send_notification
    records=records or Records()
    reconcile(records)
    with records.db.lock('media-notifications',timeout=1):
        rows=records.db.execute("SELECT * FROM media_mcp_record WHERE kind='media_notice' AND state IN ('pending','sending') ORDER BY created_at,id LIMIT 3").mappings().all()
        for raw in rows:
            row=records.decode(raw)
            if row['state']=='sending':records.update(row,'delivery_unknown',row['data'])
            else:_send(records,row,sender)
