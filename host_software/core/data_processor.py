#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理器 - 对接 MQTT 消息与数据库
负责数据校验、转换、业务逻辑计算
"""

import json
import base64
from typing import Dict, Any, Optional, Tuple

from config.settings import settings
from database.db_manager import db
from core.alarm_manager import alarm_manager


class DataProcessor:
    """检测结果数据处理器"""

    REQUIRED_FIELDS = {"device_id", "timestamp", "seq_id", "grade", "defect", "position_ok"}

    @classmethod
    def validate(cls, data: Dict[str, Any]) -> Tuple[bool, str]:
        """校验数据完整性"""
        if not isinstance(data, dict):
            return False, "数据不是 JSON 对象"
        missing = cls.REQUIRED_FIELDS - data.keys()
        if missing:
            return False, f"缺少必填字段: {missing}"
        if not isinstance(data.get("seq_id"), int):
            return False, "seq_id 必须是整数"
        if data.get("grade", 0) not in range(0, 6):
            return False, "grade 必须在 0-5 之间"
        if data.get("defect") not in {"normal", "damage", "stain", "wrinkle"}:
            return False, "defect 值不合法"
        if not isinstance(data.get("position_ok"), bool):
            return False, "position_ok 必须是布尔值"
        return True, ""

    @classmethod
    def process(cls, data: Dict[str, Any]) -> int:
        """
        处理一条检测结果：
        1. 校验
        2. 入库
        3. 触发报警（如需要）
        4. 返回 result_id
        """
        ok, msg = cls.validate(data)
        if not ok:
            raise ValueError(f"数据校验失败: {msg}")

        result_id = db.insert_detection(data)
        alarm_manager.check_and_trigger(data, result_id)
        return result_id
