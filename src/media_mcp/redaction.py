"""Shared diagnostic and quality-context redaction with explicit URL policies."""
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_KEYS = {'api_key', 'apikey', 'key', 'token', 'access_token'}


def redact_sensitive_text(value: Any, *, url_policy: str = "query_secrets", credentials: bool = False) -> str:
    if url_policy not in {'query_secrets', 'quality_context'}:
        raise ValueError('unknown_redaction_url_policy')
    text = str(value)

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
        except ValueError:
            return '[invalid URL]'
        if url_policy == 'quality_context':
            return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))
        if not parts.query:
            return raw
        query = urlencode(
            [
                (key, '<redacted>' if key.lower() in SENSITIVE_QUERY_KEYS else item)
                for key, item in parse_qsl(parts.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    pattern = r'https?://[^\s<>"\\]+' if url_policy == 'quality_context' else r'https?://[^\s\])>]+'
    text = re.sub(pattern, redact_url, text)
    for key in SENSITIVE_QUERY_KEYS:
        text = re.sub(rf'(?i)([?&]{re.escape(key)}=)[^&\s\])>]+', r'\1<redacted>', text)
    if credentials:
        text = re.sub(r'(?i)(authorization|bearer|password|token|cookie|secret)([\s:=]+)[^\s,;]+',
                      r'\1\2[redacted]', text)
    return text
