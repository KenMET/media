"""Read-only task views. Progress never scans media or needs the mutation lock."""
import json
import re
from pathlib import Path
from media_mcp.application.collections import digest,task_public
from media_mcp.redaction import redact_sensitive_text


def diagnostic(value):
    value=re.sub(r'(?i)authorization\s*[:=]\s*bearer\s+\S+','Authorization: [redacted]',str(value or '')[:10000])
    return redact_sensitive_text(value,url_policy='quality_context',credentials=True)[:2000]


# Do not transfer frozen file snapshots and every result on each progress poll.
STATUS_SELECT="""SELECT r.id,r.kind,r.state,r.revision,r.created_at,r.updated_at,
    json_set(json_remove(r.data,'$.files','$.results'),'$.files',json('[]'),'$.results',json('[]'),
        '$.total',COALESCE(json_extract(r.data,'$.total'),json_array_length(r.data,'$.files'))) AS data,
    COALESCE(json_array_length(r.data,'$.results'),0) AS completed_count,
    (SELECT COUNT(*) FROM json_each(r.data,'$.results') item
        WHERE json_extract(item.value,'$.state')!='completed') AS review_count
    FROM media_mcp_record r """


class LibraryTasks:
    def __init__(self,service):
        self.service=service;self.records=service.records;self.db=service.records.db;self.actor=service.actor

    def manage(self):
        if not self.actor.can_manage_media:raise ValueError('media_management_permission_required')

    def owned(self,job_id,full=False):
        self.manage()
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('invalid_record_id')
        row=self.records.get(job_id,'library_task') if full else self.records.decode(self.db.execute(STATUS_SELECT+"WHERE r.id=:id AND r.kind='library_task'",{'id':job_id}).mappings().first())
        if row['data']['owner']!=self.actor.id:raise ValueError('permission_denied')
        return row

    def public(self,row):
        data=row['data'];result=task_public(row)
        for name in ('completed_count','review_count'):
            if name in row:result['completed' if name=='completed_count' else name]=row[name]
        result.update(created_at=str(row['created_at']),updated_at=str(row['updated_at']))
        processing=self.db.execute("""SELECT state,lease_until,updated_at,
            CASE WHEN state='running' AND lease_until>CURRENT_TIMESTAMP THEN 1 ELSE 0 END lease_active
            FROM media_processing_job WHERE delivery_key=:key AND stage='library'""",{'key':data.get('processing_key','')}).mappings().first() if self.db.table_exists('media_processing_job') else None
        result['worker']={**dict(processing),'lease_active':bool(processing['lease_active'])} if processing else None
        progress=dict(data.get('analysis_progress') or {})
        index=data.get('next_work',0);work=data.get('work',[])
        if result['automatic'] and row['state'] in ('queued','running') and index<len(work):
            item=work[index];progress.update(label=item['label'],group=index+1,groups=len(work))
            child=self.records.by_key(digest(['library-auto-item',row['id'],index]))
            if child:
                detail=child['data'];progress['detail']=detail.get('analysis_progress') if progress.get('phase')=='identifying' else None
                progress['detail_updated_at']=str(child['updated_at'])
                if progress.get('phase')=='identifying' and detail.get('analysis_progress'):
                    progress['phase']=detail['analysis_progress']['phase']
                key=detail.get('subtitle_inflight')
                if key:
                    file=next((f for f in detail.get('files',[]) if f['key']==key),None)
                    if file:progress['file_name']=Path(file.get('source_path') or file.get('target_path')).name
        result['analysis_progress']=progress
        # Routine polling returns summaries, not paths or hundreds of per-file results.
        result['results']=[]
        return result

    def task(self,job_id):return self.public(self.owned(job_id))

    def list(self,after='',limit=10):
        self.manage()
        if after:self.owned(after)
        rows=self.db.execute(STATUS_SELECT+""" WHERE r.kind='library_task'
            AND json_extract(data,'$.owner')=:owner AND
            (:after='' OR rowid<(SELECT rowid FROM media_mcp_record WHERE id=:after))
            ORDER BY rowid DESC LIMIT :limit""",{'owner':self.actor.id,'after':after,'limit':limit+1}).mappings().all()
        page=rows[:limit]
        # Active tasks remain visible even when later completed tasks fill the history page.
        active=self.db.execute(STATUS_SELECT+""" WHERE r.kind='library_task'
            AND json_extract(data,'$.owner')=:owner AND state IN ('queued','running') ORDER BY rowid LIMIT 10""",{'owner':self.actor.id}).mappings().all() if not after else []
        active_ids={row['id'] for row in active}
        tasks=[self.public(self.records.decode(row)) for row in [*active,*[item for item in page if item['id'] not in active_ids]]]
        return {'tasks':tasks,'next_cursor':page[-1]['id'] if len(rows)>limit else None}

    def lookup_auto(self,idempotency_key):
        self.manage();request=self.records.by_key(digest(['library-auto',self.actor.id,idempotency_key]))
        return {'found':bool(request),'task':self.task(request['data']['job_id']) if request else None}

    def details(self,job_id,after=0,limit=25,issues_only=False):
        row=self.owned(job_id,full=True);data=row['data'];items=data.get('results',[])
        if issues_only:items=[item for item in items if item['state']!='completed']
        page=[dict(item) for item in items[after:after+limit]]
        files={file['key']:file for file in data.get('files',[])}
        keys={item['key'] for item in page}
        decisions={}
        # Recover reasons for jobs created by older workers without rewriting those jobs.
        for index,work in enumerate(data.get('work',[])):
            if not keys.intersection(work['keys']):continue
            child=self.records.by_key(digest(['library-auto-item',row['id'],index]))
            if child and child['data'].get('analysis_plan_id'):
                plan=self.records.get(child['data']['analysis_plan_id'],'library_analysis')
                decisions.update({d['key']:d for d in plan['data']['decisions'] if d['key'] in keys})
        for item in page:
            file=files.get(item['key'],{});decision=decisions.get(item['key'],{})
            item.update(name=item.get('name') or Path(file.get('source_path') or file.get('target_path') or item['key']).name,
                source_path=file.get('source_path'),target_path=file.get('target_path'))
            for name in ('reason','confidence','category'):
                if name not in item and name in decision:item[name]=decision[name]
            if decision.get('identity'):item['matched_title']=decision['identity']['title']
            if item.get('reason'):item['reason']=diagnostic(item['reason'])
            current=self.db.execute('SELECT target_path,status FROM media_link WHERE source_path=:source',{'source':file.get('source_path')}).mappings().first()
            item['current_mapping']=dict(current) if current else None
            subtitles=self.db.execute('''SELECT language,status,reason FROM media_subtitle
                WHERE matched_video_source_path=:source OR matched_video_target_path=:target ORDER BY id DESC LIMIT 10''',
                {'source':file.get('source_path'),'target':current['target_path'] if current else file.get('target_path')}).mappings().all()
            item['subtitle_records']=[{**dict(sub),'reason':diagnostic(sub['reason'])} for sub in subtitles]
        return {'task':self.public(row),'results':page,'total_results':len(items),
                'next_cursor':after+len(page) if after+len(page)<len(items) else None}
