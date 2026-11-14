"""Persistent memory for AI-review rejections of online subtitle candidates.

Today the review gate rejects a machine-translated candidate, but nothing
remembers the verdict: the next scan (or the next search-title variant of the
same scan) re-downloads the same file and pays for another model review. For a
media item whose only online candidates are machine translations this repeats
until the job's retry budget is exhausted, burning dozens of review calls per
cycle for identical content.

Rejections are persisted as JSON keyed by (media, provider, file_id) with a
TTL, so a rejected candidate is skipped cheaply until the TTL expires (a site
may replace the file with a better upload later; permanent blacklisting would
be wrong).

The cache is best-effort: any read/write error degrades to "no memory" and the
normal review path runs, never blocking acquisition.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

from media_mcp.subtitle.services import dependencies

_REVIEW_CACHE_TTL_SECONDS = int(
    os.environ.get("SUBTITLE_REVIEW_CACHE_TTL_SECONDS", str(7 * 24 * 3600))
)
_REVIEW_CACHE_MAX_ENTRIES = int(
    os.environ.get("SUBTITLE_REVIEW_CACHE_MAX_ENTRIES", "4096")
)
_REVIEW_CACHE_LOCK = threading.Lock()
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_.:-]+")


def _cache_path() -> str:
    return os.environ.get(
        "SUBTITLE_REVIEW_CACHE_FILE",
        "/state/subtitle-review-rejections.json",
    )


def rejection_cache_key(
    media_path: str | None, provider: str, file_id: dependencies.Any
) -> str:
    media_part = _UNSAFE_KEY_CHARS.sub("_", str(media_path or "-"))[-120:]
    file_part = _UNSAFE_KEY_CHARS.sub("_", str(file_id))[-120:]
    return f"{media_part}|{provider}|{file_part}"


def _load_cache() -> dict[str, dict[str, dependencies.Any]]:
    path = _cache_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items()
            if isinstance(value, dict)}


def _save_cache(cache: dict[str, dict[str, dependencies.Any]]) -> None:
    path = _cache_path()
    directory = os.path.dirname(path)
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary_path = f"{path}.part"
        with open(temporary_path, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False)
        os.replace(temporary_path, path)
    except OSError:
        pass


def _prune(cache: dict[str, dict[str, dependencies.Any]], now: float) -> None:
    expired = [
        key
        for key, value in cache.items()
        if now - float(value.get("at") or 0) > _REVIEW_CACHE_TTL_SECONDS
    ]
    for key in expired:
        cache.pop(key, None)
    if len(cache) > _REVIEW_CACHE_MAX_ENTRIES:
        ordered = sorted(
            cache.items(), key=lambda item: float(item[1].get("at") or 0)
        )
        for key, _ in ordered[: len(cache) - _REVIEW_CACHE_MAX_ENTRIES]:
            cache.pop(key, None)


def rejection_memory(
    media_path: str | None, provider: str, file_id: dependencies.Any
) -> dict[str, dependencies.Any] | None:
    """Return the cached rejection for this candidate, or None if unrecorded/expired."""
    key = rejection_cache_key(media_path, provider, file_id)
    now = time.time()
    with _REVIEW_CACHE_LOCK:
        cache = _load_cache()
        entry = cache.get(key)
        if not entry:
            return None
        if now - float(entry.get("at") or 0) > _REVIEW_CACHE_TTL_SECONDS:
            return None
        return entry


def record_rejection(
    media_path: str | None,
    provider: str,
    file_id: dependencies.Any,
    reason: str,
    score: float | None = None,
) -> bool:
    """Persist a rejection verdict. Returns False when persistence failed."""
    key = rejection_cache_key(media_path, provider, file_id)
    now = time.time()
    entry: dict[str, dependencies.Any] = {"reason": str(reason)[:400], "at": now}
    if score is not None:
        entry["score"] = score
    with _REVIEW_CACHE_LOCK:
        cache = _load_cache()
        cache[key] = entry
        _prune(cache, now)
        _save_cache(cache)
    return True


def filter_rejected_candidates(
    media_path: str | None,
    ranked: list[tuple[float, dependencies.Any, str]],
) -> tuple[list[tuple[float, dependencies.Any, str]], int]:
    """Drop candidates already carrying a cached rejection.

    Returns (kept, skipped_count). Never raises: on cache read failure the
    full candidate list passes through.
    """
    kept: list[tuple[float, dependencies.Any, str]] = []
    skipped = 0
    for score, candidate, reason in ranked:
        memory = rejection_memory(
            media_path, str(getattr(candidate, "provider", "")),
            getattr(candidate, "file_id", None),
        )
        if memory is None:
            kept.append((score, candidate, reason))
        else:
            skipped += 1
            dependencies.logger.info(
                "Online candidate skipped (cached rejection): %s:%s (%s)",
                getattr(candidate, "provider", "?"),
                dependencies.redact_sensitive_text(str(getattr(candidate, "file_id", "?"))),
                str(memory.get("reason", ""))[:120],
            )
    return kept, skipped
