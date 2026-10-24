"""Validated standalone configuration and filesystem boundary."""
import os
import re
from pathlib import Path


def parse_title_id(value):
    if not re.fullmatch(r'(movie|tv):[1-9][0-9]{0,11}', value):
        raise ValueError('invalid_title_id')
    kind, ident = value.split(':')
    return kind, int(ident)


def download_root():
    return Path(os.environ.get('MEDIA_DOWNLOAD_ROOT', '/data/downloads')).resolve()


def contained(path, root=None, *, exists=True):
    root = (root or download_root()).resolve()
    original = Path(path)
    resolved = original.resolve(strict=exists)
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError('path_outside_media_root')
    # Reject aliases too: a torrent path must be the recorded physical path.
    if original.absolute() != resolved:
        raise ValueError('symlink_or_path_alias')
    return resolved


def check_hardlinks():
    import tempfile
    library = Path(os.environ.get('MEDIA_LIBRARY_ROOT', '/data/media_hub'))
    source = download_root()
    source.mkdir(parents=True, exist_ok=True)
    library.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != library.stat().st_dev:
        raise RuntimeError('hardlink_cross_device')
    with tempfile.NamedTemporaryFile(dir=source, prefix='.media-probe-') as item:
        target = library / Path(item.name).name
        try:
            os.link(item.name, target)
            if not os.path.samefile(item.name, target):
                raise RuntimeError('hardlink_probe_failed')
        finally:
            target.unlink(missing_ok=True)
