#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Online subtitle provider registry and failure isolation."""

from __future__ import annotations

from dataclasses import dataclass

from media_mcp.subtitle.providers.base import (
    DownloadedSubtitle,
    OnlineSubtitleCandidate,
    SubtitleProvider,
    SubtitleSearchRequest,
)
from media_mcp.adapters.subtitle.opensubtitles import OpenSubtitlesProvider
from media_mcp.adapters.subtitle.subdl import SubDLProvider
from media_mcp.adapters.subtitle.assrt import AssrtProvider
from media_mcp.adapters.subtitle.subtitlecat import SubtitleCatProvider


def provider_factory(name):
    return {'opensubtitles': OpenSubtitlesProvider, 'subdl': SubDLProvider,
            'assrt': AssrtProvider, 'subtitlecat': SubtitleCatProvider}[name]()


DEFAULT_PROVIDER_ORDER = ('opensubtitles', 'subdl', 'assrt', 'subtitlecat')


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    success: bool
    candidates: int
    error: str | None = None


class SubtitleProviderRegistry:
    def __init__(self, providers: list[SubtitleProvider] | None = None):
        self.provider_statuses: list[dict[str, object]] = []
        self.providers = providers if providers is not None else self._configured_providers()
        if providers is not None:
            self.provider_statuses = [
                {'provider': provider.name, 'configured': True}
                for provider in providers
            ]

    def _configured_providers(self) -> list[SubtitleProvider]:
        available: dict[str, SubtitleProvider] = {
            name: provider_factory(name)
            for name in DEFAULT_PROVIDER_ORDER
        }
        providers = []
        self.provider_statuses = []
        for name in DEFAULT_PROVIDER_ORDER:
            provider = available.get(name)
            if provider is None:
                continue
            configured = bool(provider.configured)
            self.provider_statuses.append({'provider': name, 'configured': configured})
            if configured:
                providers.append(provider)
        return providers

    def search(
        self,
        request: SubtitleSearchRequest,
    ) -> tuple[list[OnlineSubtitleCandidate], list[ProviderAttempt]]:
        candidates: list[OnlineSubtitleCandidate] = []
        attempts: list[ProviderAttempt] = []
        for provider in self.providers:
            try:
                found = provider.search(request)
            except Exception as exc:
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        success=False,
                        candidates=0,
                        error=f'{type(exc).__name__}: {exc}',
                    )
                )
                continue
            candidates.extend(found)
            attempts.append(
                ProviderAttempt(
                    provider=provider.name,
                    success=True,
                    candidates=len(found),
                )
            )
        return candidates, attempts

    def download(self, candidate: OnlineSubtitleCandidate) -> DownloadedSubtitle:
        for provider in self.providers:
            if provider.name == candidate.provider:
                return provider.download(candidate)
        raise RuntimeError(f'provider unavailable: {candidate.provider}')
