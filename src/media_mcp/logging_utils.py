"""Lowest-level logging primitive for apps.api.

A tiny named-logger registry over the stdlib ``logging`` module: ``init`` builds
a rotating-file (+ optional console) logger and stores it by name, ``get``
retrieves it later. No network, no DB — this is a core utility, so higher
layers (engine) can compose on top of it.

Usage (unchanged from the old helper.log):
    from media_mcp import logging_utils as log
    log.init('/var/log/app', 'crawler_daily', log_mode='a', console_enable=False)
    log.get('crawler_daily').info('hello')
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Dict, Optional

_LEVELS: Dict[str, int] = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'warn': logging.WARNING,
    'error': logging.ERROR,
}

_LOG_SIZE_MAX_MB = 10
_FORMAT = "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s"

_loggers: Dict[str, logging.Logger] = {}
_lock = threading.Lock()


def get(name: Optional[str] = None) -> logging.Logger:
    """Return a previously ``init``-ed logger by name.

    Falls back to a console 'default' logger (auto-created) when the requested
    name was never initialised, so a stray ``log.get(...)`` never raises.
    """
    with _lock:
        if name is not None and name in _loggers:
            return _loggers[name]
        if 'default' not in _loggers:
            _init_locked(os.getcwd(), 'default')
        return _loggers['default']


def init(
    log_dir: str,
    log_name: str,
    log_mode: str = 'w',
    log_level: str = 'info',
    console_enable: bool = True,
) -> logging.Logger:
    """Create (or replace) a named rotating-file logger and register it.

    Re-initialising an existing name clears its handlers first, so repeated
    calls don't stack duplicate handlers.
    """
    with _lock:
        return _init_locked(log_dir, log_name, log_mode, log_level, console_enable)


def _init_locked(
    log_dir: str,
    log_name: str,
    log_mode: str = 'w',
    log_level: str = 'info',
    console_enable: bool = True,
) -> logging.Logger:
    level = _LEVELS.get(str(log_level).lower(), logging.INFO)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(log_name)
    logger.propagate = False
    logger.setLevel(level)

    # Replace any existing handlers so re-init does not duplicate output.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_name + '.log'),
        mode=log_mode,
        maxBytes=_LOG_SIZE_MAX_MB * 1024 * 1024,
        backupCount=1,
        encoding='utf-8',
        delay=True,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    if console_enable:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    _loggers[log_name] = logger
    return logger
