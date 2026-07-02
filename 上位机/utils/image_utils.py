#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片处理工具
"""

import base64
import io
from typing import Optional

from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QByteArray


def base64_to_pixmap(b64_str: str) -> Optional[QPixmap]:
    """base64 字符串 → QPixmap"""
    if not b64_str:
        return None
    try:
        data = QByteArray.fromBase64(b64_str.encode("ascii"))
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            return pixmap
    except Exception:
        pass
    return None


def base64_to_bytes(b64_str: str) -> Optional[bytes]:
    """base64 字符串 → bytes"""
    if not b64_str:
        return None
    try:
        return base64.b64decode(b64_str)
    except Exception:
        return None


def bytes_to_pixmap(image_bytes: bytes) -> Optional[QPixmap]:
    """bytes → QPixmap"""
    if not image_bytes:
        return None
    try:
        pixmap = QPixmap()
        if pixmap.loadFromData(image_bytes):
            return pixmap
    except Exception:
        pass
    return None
