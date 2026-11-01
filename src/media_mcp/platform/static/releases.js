// Search each season through the existing scoped API; download evidence stays server-owned.
export function seriesSeasons(title) {
  const available=(title.seasons||[]).filter(row=>Number.isInteger(row.season)&&row.season>=0&&row.season<=99&&row.episodes!==0);
  const regular=available.filter(row=>row.season>0);
  return [...new Set((regular.length?regular:available).map(row=>row.season))].sort((a,b)=>b-a);
}

export function orderedReleases(reports) {
  const unique=new Map();
  for(const report of reports)for(const [position,item] of (report.releases||[]).entries()) {
    const key=JSON.stringify([item.name,item.indexer,item.size,item.coverage_kind==='unknown'?null:report.season]);
    if(!unique.has(key))unique.set(key,{...item,season:report.season,position});
  }
  const group=row=>['season_pack','partial_pack'].includes(row.coverage_kind)?0:row.coverage_kind==='episode'?1:2;
  return [...unique.values()].sort((a,b)=>a.season==null&&b.season==null?(b.seeders??-1)-(a.seeders??-1)||a.position-b.position:group(a)-group(b)||(b.season??0)-(a.season??0)||Number(a.seeders===0)-Number(b.seeders===0)||a.position-b.position);
}

function pause(signal) {
  return new Promise((resolve,reject)=>{
    const stop=()=>{clearTimeout(timer);reject(new DOMException('Search cancelled','AbortError'));};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve();},60000);
    if(signal?.aborted)stop();else signal?.addEventListener('abort',stop,{once:true});
  });
}

export async function discoverReleases(title,search,update,signal) {
  const scopes=title.kind==='tv'?seriesSeasons(title):[null];
  const reports=[];let next=0;
  const publish=()=>update({releases:orderedReleases(reports),reports:[...reports],total:scopes.length,finished:reports.length,loading:reports.length<scopes.length});
  publish();
  async function worker() {
    while(next<scopes.length&&!signal.aborted) {
      const season=scopes[next++];let report;
      try {
        try{report=await search(season,signal);}
        catch(error){
          if(!['account_rate_limited','account_concurrency_limited'].includes(error.code))throw error;
          await pause(signal);report=await search(season,signal);
        }
      } catch(error) {
        if(signal.aborted||error.name==='AbortError'||error.name==='ViewChanged')return;
        report={releases:[],search_status:'failed',error_code:error.code||'search_unavailable'};
      }
      if(signal.aborted)return;
      reports.push({...report,season});publish();
    }
  }
  await Promise.all([worker(),worker()]);
}
