"""Opt-in, request-local provider progress on the existing authorized command."""
import asyncio
from contextvars import ContextVar
import json
import threading

from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse


_observer = ContextVar('search_progress', default=None)


def report_progress(**event):
    observer = _observer.get()
    if observer is not None:
        observer(event)


class SearchDisconnected(Exception):
    """Stop further provider work when a progress consumer disconnects."""


def stream_search(call):
    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=64)
        disconnected = threading.Event()

        def deliver(event):
            if not queue.full():
                queue.put_nowait({'progress': event})

        def report(event):
            if disconnected.is_set():
                raise SearchDisconnected()
            loop.call_soon_threadsafe(deliver, event)

        def work():
            token = _observer.set(report)
            try:
                return {'success': True, 'data': call()}
            except ValueError as exc:
                code = str(exc)
                if not code.replace('_', '').isalnum() or len(code) > 120:
                    code = 'invalid_request'
                return {'success': False, 'error_code': code}
            except Exception:
                return {'success': False, 'error_code': 'dependency_unavailable'}
            finally:
                _observer.reset(token)

        async def run():
            result = await run_in_threadpool(work)
            await queue.put(result)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                yield json.dumps(item, ensure_ascii=True) + '\n'
                if 'success' in item:
                    break
        finally:
            disconnected.set()
            task.cancel()

    return StreamingResponse(events(), media_type='application/x-ndjson',
                             headers={'X-Accel-Buffering': 'no'})
