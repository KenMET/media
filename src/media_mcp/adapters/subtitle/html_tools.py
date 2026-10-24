#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small HTML helpers for subtitle provider pages."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


@dataclass(frozen=True)
class HtmlLink:
    href: str
    text: str
    attrs: dict[str, str]


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[HtmlLink] = []
        self._current_href: str | None = None
        self._current_attrs: dict[str, str] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != 'a':
            return
        attributes = {key.lower(): value or '' for key, value in attrs}
        href = attributes.get('href')
        if not href:
            return
        self._current_href = unescape(href)
        self._current_attrs = attributes
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != 'a' or self._current_href is None:
            return
        text = ' '.join(' '.join(self._text_parts).split())
        self.links.append(
            HtmlLink(
                href=self._current_href,
                text=unescape(text),
                attrs=self._current_attrs,
            )
        )
        self._current_href = None
        self._current_attrs = {}
        self._text_parts = []


def extract_links(html: str) -> list[HtmlLink]:
    parser = LinkExtractor()
    parser.feed(html)
    return parser.links
