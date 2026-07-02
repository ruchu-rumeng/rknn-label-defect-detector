#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工具函数
"""

import re
import os
from datetime import datetime
from typing import Optional


def validate_device_id(device_id: str) -> bool:
    """设备 ID 校验：字母数字和下划线，长度 3-32"""
    if not device_id:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]{3,32}$', device_id))


def validate_timestamp(ts: str) -> bool:
    """时间戳格式校验：YYYY-MM-DD HH:MM:SS"""
    try:
        datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        return False


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """格式化当前时间为字符串"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(name: str) -> str:
    """将字符串转为安全文件名"""
    return re.sub(r'[^\w\-_.]', '_', name)


def ensure_dir(path: str) -> str:
    """确保目录存在，返回绝对路径"""
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)
