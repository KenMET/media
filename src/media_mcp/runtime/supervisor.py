"""Supervise independent processing workers and the acquisition controller."""
import os
import signal
import time
from multiprocessing import Process
from pathlib import Path
from media_mcp.adapters.codex import CodexClient
from media_mcp.adapters.notify import send_notification
from media_mcp.config import check_hardlinks
from media_mcp.runtime.worker import heartbeat, run_worker
from media_mcp.storage.records import Records
from media_mcp.storage.media import _client
from media_mcp.runtime.state import MediaJobs
from media_mcp.application.controller import Controller


def main():
    stop = False
    def stopping(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    for name in ('monitor', 'ingest', 'subtitle', 'library'):
        (Path(os.environ.get('MEDIA_HEALTH_DIR', '/tmp/media-health')) / name).unlink(missing_ok=True)
    records = Records()
    records.initialize()
    _client(None)
    jobs = MediaJobs()
    jobs.initialize()
    processes = []
    failed_notified = False
    maintenance_error_at = 0
    try:
        while not stop:
            try:
                check_hardlinks()
                CodexClient(timeout=45, max_retries=0).check_connection()
                if not send_notification('Media MCP 启动通过', 'Codex 认证与硬链接探针通过，后台任务即将启动。'):
                    raise RuntimeError('startup_notification_failed')
                break
            except Exception as exc:
                if not failed_notified:
                    failed_notified = send_notification('Media MCP 启动失败', f'{type(exc).__name__}；下载提交与处理暂停，60秒后重试。')
                for _ in range(60):
                    if stop:
                        return
                    time.sleep(1)
        if stop:
            return
        for stage in ('ingest', 'subtitle'):
            process = Process(target=run_worker, args=(stage,), name='media-'+stage)
            process.start()
            processes.append(process)
        from media_mcp.runtime.library_worker import run_library_worker
        process=Process(target=run_library_worker,name='media-library')
        process.start()
        processes.append(process)
        controller = Controller(records, jobs=jobs)
        while not stop:
            if any(not process.is_alive() for process in processes):
                raise RuntimeError('processing_worker_exited')
            heartbeat('monitor')
            try:
                from media_mcp.runtime.task_notifications import deliver
                deliver(records)
                from media_mcp.runtime.thread_cleanup import drain
                drain(records)
            except Exception as exc:
                # Optional delivery/archival must not terminate active model or
                # subtitle calls. Durable intents remain available for retry.
                if time.monotonic()-maintenance_error_at>=60:
                    print('Media background maintenance deferred: '+type(exc).__name__,flush=True)
                    maintenance_error_at=time.monotonic()
            for row in records.active():
                if stop:
                    break
                controller.tick(row['id'])
                heartbeat('monitor')
            for _ in range(5):
                if stop:
                    break
                time.sleep(1)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)


if __name__ == '__main__':
    main()
