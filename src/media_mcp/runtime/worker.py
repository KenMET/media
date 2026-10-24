"""Independent supervised ingest/subtitle workers; durable jobs survive restart."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from media_mcp.runtime.state import MediaJobs


def heartbeat(name: str):
    path = Path(os.environ.get('MEDIA_HEALTH_DIR', '/tmp/media-health')) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()))


def run_worker(stage: str, test_mode: bool = False):
    from media_mcp.ingest.run import full_scan_triage, set_logger, _requires_human_review
    from media_mcp.ingest.domain.file_utils import is_video_file
    from media_mcp.ingest.services.triage_agent import CodexMediaTriageAgent
    from media_mcp import logging_utils as log
    log.init('/tmp', 'MediaMonitor', log_mode='a', log_level='info', console_enable=True)
    logger = log.get('MediaMonitor')
    set_logger(logger)
    jobs = MediaJobs()
    jobs.reset_after_fork()
    jobs.initialize()
    from media_mcp.storage.media import _client
    _client(jobs.db.db_name)
    triage = CodexMediaTriageAgent() if stage == 'ingest' else None
    while True:
        heartbeat(stage)
        job = jobs.claim(stage)
        if not job:
            time.sleep(2)
            continue
        from media_mcp.application.identity import expected_identity
        from media_mcp.storage.records import Records
        expected = Records(jobs.db).processing_context(job['delivery_key'])
        token = expected_identity.set(expected)
        done = threading.Event()
        def renew():
            while not done.wait(20):
                try:
                    if not jobs.renew(job):
                        os._exit(1)
                    heartbeat(stage)
                except Exception:
                    # Fail the process rather than continue mutations after losing ownership.
                    os._exit(1)
        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        error = None
        result = {}
        review_required = False
        try:
            from media_mcp.config import contained
            path = contained(job['path'])
            if path.is_dir():
                for child in path.rglob('*'):
                    contained(str(child))
            if not os.path.exists(job['path']):
                raise FileNotFoundError('source_path_unavailable')
            if stage == 'ingest':
                manual_retry = bool(json.loads(job.get('result_json') or '{}').get('manual_retry'))
                counts = full_scan_triage(triage, job['path'], test_mode=test_mode, run_subtitles=False, recheck_unlinked=manual_retry,recheck_review=manual_retry)
                result = dict(zip(('created','relinked','existed','failed'), counts))
                attention = jobs.db.execute('''SELECT source_path,status,reason FROM media_link
                    WHERE (source_path=:path OR substr(source_path,1,LENGTH(:prefix))=:prefix)
                    AND status IN ('failed','needs_review')''', {'path':job['path'],'prefix':job['path'].rstrip('/')+'/'}).mappings().all()
                attention = [row for row in attention if is_video_file(row['source_path']) and os.path.isfile(row['source_path'])]
                review_count = sum(_requires_human_review(row) for row in attention)
                transient_count = len(attention)-review_count
                result['review'] = review_count
                if not any(counts) and expected:
                    review_required = True
                    error = 'no_media_processed'
                elif review_count and not transient_count:
                    review_required = True
                    error = 'ingest_requires_review'
                elif counts[3]:
                    error = 'ingest_incomplete'
            else:
                from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
                result = SubtitleAgent(defer_ai_usage=True).run_path_summary(job['path'], test_mode=test_mode)
                if result['failed'] or result['missing']:
                    error = 'subtitle_incomplete'
                elif result['review']:
                    review_required = True
                    error = 'subtitle_requires_review'
        except Exception as exc:
            review_required = isinstance(exc, ValueError)
            error = 'processing_identity_or_path_requires_review' if review_required else type(exc).__name__
            logger.exception('Media %s job %s failed', stage, job['id'])
        finally:
            done.set()
            thread.join(timeout=2)
        expected_identity.reset(token)
        jobs.finish(job, error=error, result=json.dumps(result, ensure_ascii=False), review_required=review_required)
        heartbeat(stage)
