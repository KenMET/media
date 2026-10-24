#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
naming.py
统一媒体展示名与路径基名，避免中英文混用、重复括号名。
"""

from __future__ import annotations

import re
from typing import Optional

SEASON_SUFFIX_PATTERNS = [
    re.compile(r'\s*第\s*[一二三四五六七八九十0-9]+\s*季\s*$', re.IGNORECASE),
    re.compile(r'\s*Season\s*\d+\s*$', re.IGNORECASE),
    re.compile(r'\s*S\d+\s*$', re.IGNORECASE),
]


def has_cjk(value: Optional[str]) -> bool:
    if not value:
        return False
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', value))


def _norm(value: Optional[str]) -> str:
    if not value:
        return ''
    value = value.strip().lower()
    value = re.sub(r'[\s\-_:：·,./\\()\[\]{}]+', '', value)
    return value


def same_name(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return _norm(a) == _norm(b)


def choose_display_and_alt(zh_name: Optional[str], en_name: Optional[str], original_name: Optional[str]) -> tuple[str, Optional[str]]:
    zh = (zh_name or '').strip()
    en = (en_name or '').strip()
    original = (original_name or '').strip()

    if zh:
        display = zh
        alt = original or None
        if not alt and en and not same_name(zh, en):
            alt = en
    else:
        display = en or original or ''
        alt = original or None

    if not display:
        display = original or en or zh or 'Unknown'

    if alt and same_name(display, alt):
        alt = None

    return display, alt


def strip_season_suffix(value: Optional[str]) -> str:
    text = (value or '').strip()
    if not text:
        return ''
    for pattern in SEASON_SUFFIX_PATTERNS:
        text = pattern.sub('', text).strip()
    return text


def build_base_title(zh_name: Optional[str], en_name: Optional[str], original_name: Optional[str]) -> tuple[str, str, Optional[str]]:
    display, alt = choose_display_and_alt(zh_name, en_name, original_name)
    if alt:
        return f'{display}({alt})', display, alt
    return display, display, None


def should_upgrade_canonical_title(existing_media_name: Optional[str], new_media_name: Optional[str]) -> bool:
    old_name = (existing_media_name or '').strip()
    new_name = (new_media_name or '').strip()
    if not new_name:
        return False
    if not old_name:
        return True
    if same_name(old_name, new_name):
        return False
    if not has_cjk(old_name) and has_cjk(new_name):
        return True
    return False
