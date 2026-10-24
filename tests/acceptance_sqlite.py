"""Run only against a disposable SQLite state and disposable /data mount.

MEDIA_ACCEPTANCE=isolated-container and a marked disposable state directory are mandatory.
No real torrents or external model requests are made by this script.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock


def main():
    if os.environ.get('MEDIA_ACCEPTANCE')!='isolated-container' or os.environ.get('MEDIA_DB_PATH')!='/state/media.sqlite3':
        raise SystemExit('Refusing non-acceptance state')
    if not Path('/state/.acceptance').is_file():
        raise SystemExit('Refusing unmarked media mount')
    from media_mcp.storage.records import Records
    from media_mcp.storage.media import _client
    from media_mcp.runtime.state import MediaJobs
    from media_mcp.application.acquire import MediaService
    from media_mcp.application.controller import Controller
    from media_mcp.application.identity import expected_identity
    from media_mcp.config import download_root,check_hardlinks
    from media_mcp.ingest.services.triage_agent import CodexMediaTriageAgent
    from media_mcp.ingest.run import full_scan_triage,set_logger
    from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
    from media_mcp.logging_utils import init,get
    check_hardlinks()
    records=Records();records.initialize();_client(None)
    assert records.db.execute('SELECT COUNT(*) FROM media_mcp_record').scalar()==0,'Requires a fresh acceptance database'
    jobs=MediaJobs();jobs.initialize()
    init('/tmp','acceptance',console_enable=False);set_logger(get('acceptance'))
    root=download_root();root.mkdir(parents=True,exist_ok=True)
    video=root/'Fixture.2020.1080p.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=1',
        '-t','2','-c:v','libx264','-threads','1','-y',str(video)],check=True)
    subtitle=video.with_suffix('.zh-CN.srt')
    subtitle.write_text('1\n00:00:00,100 --> 00:00:01,900\n你好，这是隔离字幕验收。\n',encoding='utf-8')
    tmdb=Mock();tmdb.detail.return_value={'title_id':'movie:991234','kind':'movie','tmdb_id':991234,
        'title':'验收电影','original_title':'Fixture','date':'2020-01-01','original_language':'en'}
    indexer=Mock();indexer.search.return_value={'releases':[{'name':'Fixture.2020.1080p','resolution':1080,
        'size':video.stat().st_size,'seeders':1,'indexer':'isolated-fixture',
        'download_url':'magnet:?xt=urn:btih:'+'a'*40}], 'diagnostics':[{'site':'isolated-fixture','status':'ok','raw_count':1}]};indexer.torrent.return_value=None
    service=MediaService(records,tmdb,indexer)
    found=service.search_releases('movie:991234',resolution=1080)
    plan=service.plan(found['releases'][0]['release_id'])
    task=service.start(plan['plan_id'],plan['revision'],'isolated-request-123')
    assert service.start(plan['plan_id'],plan['revision'],'isolated-request-123')['job_id']==task['job_id']
    real_qbit=os.environ.get('MEDIA_ACCEPTANCE_QBIT')=='real'
    if real_qbit:
        from media_mcp.adapters.download import Downloader
        def bencode(value):
            if isinstance(value,int):return b'i'+str(value).encode()+b'e'
            if isinstance(value,bytes):return str(len(value)).encode()+b':'+value
            return b'd'+b''.join(bencode(k)+bencode(v) for k,v in sorted(value.items()))+b'e'
        content=video.read_bytes()
        info={b'name':video.name.encode(),b'length':len(content),b'piece length':262144,
              b'pieces':b''.join(hashlib.sha1(content[i:i+262144]).digest() for i in range(0,len(content),262144)),b'private':1}
        torrent=bencode({b'info':info})
        indexer.torrent.return_value=torrent
        downloader=Downloader()
    else:
        downloader=Mock();downloader.find.return_value=None
    controller=Controller(records,downloader,indexer,jobs)
    controller.tick(task['job_id'])
    assert records.get(task['job_id'])['state']=='downloading'
    if real_qbit:
        import time
        for _ in range(60):
            controller.tick(task['job_id'])
            if service.job(task['job_id'])['stage']=='processing':break
            time.sleep(.5)
    else:
        downloader.find.return_value={'hash':'a'*40,'progress':1,'state':'uploading','content_path':str(video),
            'save_path':str(root),'category':'media-mcp','tags':'media-mcp-'+task['job_id']}
        downloader.files.return_value=[{'name':video.name,'progress':1,'priority':1,'size':video.stat().st_size}]
        controller.tick(task['job_id'])
    assert service.job(task['job_id'])['stage']=='processing'
    claimed=jobs.claim('ingest');assert claimed and jobs.claim('ingest') is None
    assert jobs.renew(claimed)
    assert not jobs.renew({**claimed,'owner':'0'*32})
    context=records.processing_context(claimed['delivery_key'])
    assert context['identity']['title_id']=='movie:991234'
    token=expected_identity.set(context)
    try:
        model=Mock()
        model.classify.return_value={'success':True,'kind':'movie','source_path':str(video),'tmdb_id':991234,
            'title':{'zh':'验收电影','original':'Fixture','base':'验收电影(Fixture)'},
            'year':2020,'original_language':'en','confidence':0.99}
        counts=full_scan_triage(CodexMediaTriageAgent(model),str(video),test_mode=True,run_subtitles=False)
        assert sum(counts[:3])>0 and counts[3]==0,counts
        jobs.finish(claimed,result=json.dumps(dict(zip(('created','relinked','existed','failed'),counts))))
        linked=records.db.execute("SELECT * FROM media_link WHERE status='linked'").mappings().one()
        assert os.path.samefile(video,linked['target_path'])
        assert video.stat().st_nlink>=2
        subtitle_job=jobs.claim('subtitle');assert subtitle_job
        summary=SubtitleAgent(disable_opensubtitle=True).run_path_summary(str(video),send_notify=False)
        assert not summary['failed'] and not summary['missing'],summary
        jobs.finish(subtitle_job,result=json.dumps(summary))
    finally:
        expected_identity.reset(token)
    controller.tick(task['job_id'])
    assert service.job(task['job_id'])['stage']=='completed',service.job(task['job_id'])
    subtitles=records.db.execute('SELECT target_subtitle_path,status FROM media_subtitle').mappings().all()
    assert subtitles and all(Path(row['target_subtitle_path']).is_file() for row in subtitles)
    # A fresh repository sees the same persisted result (not an in-memory ledger).
    assert MediaService(Records(),tmdb,indexer).job(task['job_id'])['stage']=='completed'
    if not real_qbit:assert downloader.add.call_count==1
    print(json.dumps({'acceptance':'passed','database':'SQLite','qBittorrent':'real payload hash verification' if real_qbit else 'fixture','external_search_and_model':'fixtures',
        'real_components':['SQLite','MCP image','leases','ffmpeg','canonical naming','hardlink inode','subtitle sidecar','durable completion'],
        'task_state':'completed','video_links':video.stat().st_nlink,'subtitles':len(subtitles)},ensure_ascii=False))


if __name__=='__main__':main()
