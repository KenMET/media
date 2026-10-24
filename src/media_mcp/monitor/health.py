"""Health requires live supervised workers and recent progress/lease heartbeats."""
import os
from pathlib import Path
import time


def healthy(root=None, now=None):
    root = Path(root or os.environ.get('MEDIA_HEALTH_DIR', '/tmp/media-health'))
    now = time.time() if now is None else now
    try:
        return all(0 <= now-float((root/name).read_text()) < 150 for name in ('monitor','ingest','subtitle'))
    except (OSError, ValueError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if healthy() else 1)
