"""Direct notification adapter; the local log is always a durable delivery target."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import requests


def send_notification(title: str, content: str, url: str | None = None) -> bool:
    from media_mcp.redaction import redact_sensitive_text
    record = {'at': datetime.now(timezone.utc).isoformat(), 'title': title,
              'content': redact_sensitive_text(content)}
    path = Path(os.environ.get('MEDIA_NOTIFICATION_LOG', '/state/notifications.jsonl'))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    endpoint = os.environ.get('BARK_URL', '').strip()
    if endpoint:
        try:
            response = requests.post(endpoint, json={'title': title, 'body': record['content'],
                **({'url': url} if url else {})}, timeout=15, allow_redirects=False)
            response.raise_for_status()
            return response.json().get('code') == 200
        except (requests.RequestException, ValueError):
            return False
    return True
