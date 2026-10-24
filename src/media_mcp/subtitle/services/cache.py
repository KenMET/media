#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run-scoped caches for subtitle orchestration."""

from __future__ import annotations

import os

from media_mcp.subtitle.domain.subtitle_file import SubtitleCandidate, parse_subtitle_candidate


class SubtitleRunCache:
    def __init__(self) -> None:
        self._subtitle_candidate_cache: dict[str, tuple[tuple[int, int], SubtitleCandidate]] = {}
        self._directory_listing_cache: dict[str, list[str]] = {}

    def parse_subtitle_candidate(self, path: str) -> SubtitleCandidate:
        try:
            stat = os.stat(path)
            cache_key = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            cache_key = (-1, -1)
        cached = self._subtitle_candidate_cache.get(path)
        if cached and cached[0] == cache_key:
            return cached[1]
        candidate = parse_subtitle_candidate(path)
        self._subtitle_candidate_cache[path] = (cache_key, candidate)
        return candidate

    def listdir(self, directory: str) -> list[str]:
        cached = self._directory_listing_cache.get(directory)
        if cached is not None:
            return list(cached)
        names = os.listdir(directory)
        self._directory_listing_cache[directory] = list(names)
        return names

    def invalidate_path(self, path: str | None) -> None:
        if not path:
            return
        self._subtitle_candidate_cache.pop(path, None)
        directory = os.path.dirname(path)
        if directory:
            self._directory_listing_cache.pop(directory, None)

    def remove_file(self, path: str) -> None:
        from media_mcp.runtime.state import assert_mutation_lock
        assert_mutation_lock()
        os.remove(path)
        self.invalidate_path(path)

    def replace_file(self, source_path: str, target_path: str) -> None:
        from media_mcp.runtime.state import assert_mutation_lock
        assert_mutation_lock()
        os.replace(source_path, target_path)
        self.invalidate_path(source_path)
        self.invalidate_path(target_path)
