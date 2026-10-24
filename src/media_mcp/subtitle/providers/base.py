#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Common contracts for online subtitle providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderTemporarilyUnavailable(RuntimeError):
    def __init__(self, provider: str, reason: str, retry_at: float | None = None):
        super().__init__(reason)
        self.provider = provider
        self.reason = reason
        self.retry_at = retry_at


@dataclass(frozen=True)
class SubtitleSearchRequest:
    media_type: str
    tmdb_id: int | None
    title: str | None
    year: int | None
    season: int | None
    episode: int | None
    languages: tuple[str, ...]


@dataclass(frozen=True)
class OnlineSubtitleCandidate:
    provider: str
    candidate_id: str
    file_id: int | str
    file_name: str
    language: str
    subtitle_type: str
    format: str
    media_type: str | None = None
    tmdb_id: int | None = None
    parent_tmdb_id: int | None = None
    season: int | None = None
    episode: int | None = None
    title: str | None = None
    release: str | None = None
    fps: float | None = None
    download_count: int = 0
    rating: float = 0.0
    trusted: bool = False
    machine_translated: bool = False
    hearing_impaired: bool = False
    foreign_parts_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadedSubtitle:
    content: bytes
    file_name: str
    content_type: str | None = None


class SubtitleProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool:
        ...

    def search(self, request: SubtitleSearchRequest) -> list[OnlineSubtitleCandidate]:
        ...

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        ...
