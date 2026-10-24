#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py
媒体处理工具函数
"""

import os
import errno
import json
from typing import List, Dict, Set

MAX_FILENAME_BYTES = 240

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}


def same_recorded_source(record: dict, path: str) -> bool:
    try:
        stat = os.stat(path,follow_symlinks=False)
        payload = record.get('agent_result_json') or {}
        if isinstance(payload,str):
            payload = json.loads(payload)
        fingerprint = payload.get('_source_fingerprint') if isinstance(payload,dict) else None
        if isinstance(fingerprint,list) and len(fingerprint)==4:
            return fingerprint == [stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns]
        return stat.st_ino==record.get('source_inode') and stat.st_size==record.get('source_size')
    except (OSError,ValueError,TypeError):
        return False


def is_video_file(filename: str) -> bool:
    """
    判断文件是否为视频文件

    Args:
        filename: 文件名

    Returns:
        是否为视频文件
    """
    ext = os.path.splitext(filename)[1].lower()
    return ext in VIDEO_EXTENSIONS


def _raise_scan_error(error):
    raise error


def get_main_media(directory: str, size_ratio: int = 10) -> List[Dict[str, any]]:
    """
    搜索目录中的主要媒体文件

    Args:
        directory: 目录路径或文件路径
        size_ratio: 兼容旧调用参数，不再按相对文件大小丢弃媒体

    Returns:
        媒体文件列表，每项包含path和size_mb
    """
    main_media = []

    # 如果是文件，直接处理
    if os.path.isfile(directory):
        if is_video_file(directory):
            size = os.path.getsize(directory)
            return [{
                "path": directory,
                "size_mb": round(size / 1024 / 1024, 2)
            }]
        else:
            return []

    # 如果是目录，递归搜索
    for root, dirs, files in os.walk(directory,onerror=_raise_scan_error):
        for file in files:
            if not is_video_file(file):
                continue

            full_path = os.path.join(root, file)
            size = os.path.getsize(full_path)

            main_media.append({
                "path": full_path,
                "size_mb": round(size / 1024 / 1024, 2)
            })

    if len(main_media) == 0:
        return []

    # 按大小排序，最大的优先
    main_media.sort(key=lambda x: x["size_mb"], reverse=True)

    # File size does not establish whether a video is an episode or an extra.
    # Classification/quality selection handles short videos explicitly; never
    # silently drop a real short episode because a larger movie shares a folder.
    return main_media


def list_directory_recursive(path: str) -> Dict:
    """
    递归列出目录内容

    Args:
        path: 目录路径

    Returns:
        嵌套的目录结构字典
    """
    result = {
        "name": os.path.basename(path),
        "type": "directory",
        "children": []
    }

    try:
        entries = os.listdir(path)
    except PermissionError:
        result["children"].append({
            "name": "Permission Denied",
            "type": "error"
        })
        return result

    for entry in entries:
        full_path = os.path.join(path, entry)

        if os.path.isdir(full_path):
            # 递归子目录
            result["children"].append(list_directory_recursive(full_path))
        else:
            # 文件信息
            result["children"].append({
                "name": entry,
                "type": "file",
                "size_bytes": os.path.getsize(full_path)
            })

    return result

REPLACEMENTS = {
    '\\': '＼',
    '/': '／',
    ':': '：',
    '?': '？',
    '*': '_',
    '|': '_',
    '"': "'",
    '<': '《',
    '>': '》',
    ', ': ',',
    '. ': '.',
}


def sanitize_segment(segment: str) -> str:
    for old, new in REPLACEMENTS.items():
        segment = segment.replace(old, new)
    return segment


def sanitize_path(path: str) -> str:
    drive, tail = os.path.splitdrive(path)
    is_absolute = tail.startswith(os.sep)
    parts = [part for part in tail.split(os.sep) if part]
    sanitized_parts = [sanitize_segment(part) for part in parts]

    rebuilt = os.sep.join(sanitized_parts)
    if is_absolute:
        rebuilt = os.sep + rebuilt if rebuilt else os.sep
    if drive:
        rebuilt = drive + rebuilt
    return rebuilt

def _truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode('utf-8').rstrip(' .-_')
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ''


def _shorten_filename_for_limit(filename: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    stem, ext = os.path.splitext(filename)
    if len(filename.encode('utf-8')) <= max_bytes:
        return filename

    parts = stem.split(' - ')
    if len(parts) >= 4 and parts[-2].isdigit():
        title = parts[0]
        marker = parts[1]
        year = parts[-2]
        compact = f'{title} - {marker} - {year}{ext}'
        if len(compact.encode('utf-8')) <= max_bytes:
            return compact
        reserved = len(f' - {marker} - {year}{ext}'.encode('utf-8'))
        title_budget = max(32, max_bytes - reserved)
        short_title = _truncate_utf8_bytes(title, title_budget)
        return f'{short_title} - {marker} - {year}{ext}'

    if len(parts) >= 2 and parts[-1].isdigit():
        title = ' - '.join(parts[:-1])
        year = parts[-1]
        compact = f'{title} - {year}{ext}'
        if len(compact.encode('utf-8')) <= max_bytes:
            return compact
        reserved = len(f' - {year}{ext}'.encode('utf-8'))
        title_budget = max(32, max_bytes - reserved)
        short_title = _truncate_utf8_bytes(title, title_budget)
        return f'{short_title} - {year}{ext}'

    budget = max(16, max_bytes - len(ext.encode('utf-8')))
    short_stem = _truncate_utf8_bytes(stem, budget)
    return f'{short_stem}{ext}'


def _shorten_target_path_for_limit(hardlink_path: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    directory = os.path.dirname(hardlink_path)
    filename = os.path.basename(hardlink_path)
    shortened = _shorten_filename_for_limit(filename, max_bytes=max_bytes)
    return os.path.join(directory, shortened)


def create_hardlink_with_target(source_path: str, hardlink_path: str) -> tuple[bool, str | None, str | None]:
    if not source_path or not hardlink_path:
        return False, "source_path 或 hardlink_path 缺失", None
    if not os.path.isfile(source_path):
        return False, f"源文件不存在: {source_path}", None
    if os.path.islink(source_path):
        return False, 'Source symlink is not a regular media file', None
    parent = os.path.abspath(os.path.dirname(source_path))
    while parent != os.path.dirname(parent):
        if os.path.islink(parent):
            return False, 'Source parent symlink is not allowed', None
        parent = os.path.dirname(parent)
    parent = os.path.abspath(os.path.dirname(hardlink_path))
    while parent != os.path.dirname(parent):
        if os.path.islink(parent):
            return False, 'Target parent symlink is not allowed', None
        parent = os.path.dirname(parent)
    target_dir = os.path.dirname(hardlink_path)

    def _link_once(target_path: str) -> tuple[bool, str | None]:
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.link(source_path, target_path)
            return True, None
        except FileExistsError:
            try:
                if not os.path.islink(target_path) and os.path.samefile(source_path, target_path):
                    return True, 'Skip hardlink'
                return False, 'Target conflict: existing file is not the source inode'
            except OSError as e:
                return False, f"处理已存在文件时失败: {e.strerror}"
        except OSError as e:
            if e.errno == errno.EXDEV:
                return False, "无法创建硬链接：源路径与目标路径不在同一文件系统（跨设备）"
            if e.errno == errno.ENAMETOOLONG:
                return False, '__ENAMETOOLONG__'
            return False, f"创建硬链接失败: {e.strerror}"

    os.makedirs(target_dir, exist_ok=True)
    flag, msg = _link_once(hardlink_path)
    if flag:
        return flag, msg, hardlink_path
    if msg != '__ENAMETOOLONG__':
        return False, msg, None

    shortened_path = _shorten_target_path_for_limit(hardlink_path)
    if shortened_path == hardlink_path:
        return False, '创建硬链接失败: File name too long', None

    flag, msg = _link_once(shortened_path)
    if flag:
        if msg in {'Overwrite hardlink', 'Skip hardlink'}:
            return True, f'{msg} (shortened filename)', shortened_path
        return True, f'Shortened filename: {os.path.basename(shortened_path)}', shortened_path

    if msg == '__ENAMETOOLONG__':
        return False, '创建硬链接失败: File name too long', None
    return False, msg, None


def create_hardlink(source_path: str, hardlink_path: str) -> tuple[bool, str | None]:
    flag, msg, _ = create_hardlink_with_target(source_path, hardlink_path)
    return flag, msg
