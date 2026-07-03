#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简易日志模块
- 写入 data/logs/app.log（可写目录，兼容打包后）
- 同时支持在 UI 中显示最后 N 条
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime
from threading import Lock


def _get_log_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.path.dirname(sys.executable)) / "data" / "logs"
    return Path(__file__).parent.parent / "data" / "logs"


LOG_DIR = _get_log_dir()
LOG_FILE = LOG_DIR / "app.log"

# 内存缓存：最近 200 条日志
_log_cache = []
_log_lock = Lock()


def _ensure_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str, level: str = "INFO"):
    """写日志到文件 + 内存缓存"""
    _ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] [{level}] {msg}"
    
    with _log_lock:
        _log_cache.append(line)
        if len(_log_cache) > 200:
            _log_cache.pop(0)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # 文件写入失败不影响程序运行


def info(msg: str):
    log(msg, "INFO")


def warn(msg: str):
    log(msg, "WARN")


def error(msg: str):
    log(msg, "ERROR")


def debug(msg: str):
    log(msg, "DEBUG")


def get_recent_logs(n: int = 50) -> list:
    """获取最近 N 条日志"""
    with _log_lock:
        return list(_log_cache[-n:])
