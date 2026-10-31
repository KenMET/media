"""Cloud discovery checks reuse normal frozen evidence and NAS acquisition fencing."""
import asyncio
import base64
from contextlib import asynccontextmanager
import logging
import re

from media_mcp.application.acquire import MediaService
from media_mcp.application.releases import select_releases
from media_mcp.platform.cloud import CloudRecords


def check_season(claim, call, db, tmdb, indexer):
    from media_mcp.platform.limits import Budget
    if claim.get('one_time') and claim.get('last_result') is not None:
        return claim['last_result']
    with Budget(db).operation(claim['owner'],'search'):
        return _check_season(claim,call,db,tmdb,indexer)


def _check_season(claim, call, db, tmdb, indexer):
    records=CloudRecords(db,claim['owner']);records.initialize()
    service=MediaService(records,tmdb,indexer)
    report=service.search_releases(claim['title_id'],claim['season'],episodes=claim.get('requested_episodes'),resolution=claim['resolution'])
    unknown=set(report['scope'].get('air_dates_unknown',[]))
    if claim.get('requested_episodes') and unknown.intersection(claim['requested_episodes']):
        raise ValueError('episode_air_dates_require_review')
    report['scope']['episodes']=[episode for episode in report['scope']['episodes'] if episode not in unknown]
    if not report['scope']['episodes']:
        raise ValueError('episode_air_dates_require_review')
    call({'request_id':claim['request_id'],'run_key':claim['run_key'],'episodes':report['scope']['episodes']})
    selected,missing=select_releases(report['releases'],report['scope']['episodes'])
    jobs=[]
    for release,episodes in selected:
        row=service.records.get(release['release_id'],'release')
        content=indexer.torrent(row['data']['release']['download_url'])
        payload={'kind':'bytes','data':base64.b64encode(content).decode()} if isinstance(content,bytes) else {
            'kind':'magnet','data':content or row['data']['release']['download_url']}
        snapshot={k:row['data'][k] for k in ('identity','scope','release','expires_at')}
        snapshot['scope']={**snapshot['scope'],'episodes':episodes}
        # Freeze disjoint requested episodes; extra pack files stay at the source only.
        job=call({'request_id':claim['request_id'],'run_key':claim['run_key'],'request':{
            'action':'plan','operation':'plan','release_id':row['id'],'snapshot':snapshot,'payload':payload}})
        jobs.append(job['job_id'])
    result={'job_ids':jobs,'missing_episodes':missing,'expected_episodes':report['scope']['episodes'],
            'known_episodes':report['scope'].get('known_episodes',[]),'air_dates_unknown':sorted(unknown),'search_status':report['search_status']}
    call({'request_id':claim['request_id'],'run_key':claim['run_key'],'result':result})
    return result


def season_lifespan(due, call, db, tmdb, indexer):
    @asynccontextmanager
    async def lifespan(app):
        async def poll():
            while True:
                await asyncio.sleep(60)
                try:
                    from starlette.concurrency import run_in_threadpool
                    claims=await run_in_threadpool(due)
                    for claim in claims:
                        try:
                            await run_in_threadpool(check_season,claim,call,db,tmdb,indexer)
                        except Exception as error:
                            code=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[a-z_]{1,100}',str(error)) else 'season_check_unavailable'
                            try:
                                await run_in_threadpool(call,{'request_id':claim['request_id'],'run_key':claim['run_key'],'result':{'error_code':code}})
                            except Exception:
                                pass
                            logging.getLogger(__name__).warning('Season check deferred: %s',type(error).__name__)
                except Exception as error:
                    logging.getLogger(__name__).warning('Season scheduling deferred: %s',type(error).__name__)
        task=asyncio.create_task(poll())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    return lifespan
