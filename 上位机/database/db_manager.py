#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理器 - 封装 SQLite 所有操作
支持连接池、事务、ORM 风格接口
"""

import sqlite3
import threading
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any


def _get_base_dir() -> Path:
    """获取项目基础目录（兼容 PyInstaller 打包）"""
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_data_dir() -> Path:
    """获取用户数据目录（可写）"""
    if getattr(sys, 'frozen', False):
        # 打包后：exe 所在目录
        return Path(os.path.dirname(sys.executable))
    # 开发模式：项目根目录
    return Path(__file__).parent.parent


DB_PATH = _get_data_dir() / "data" / "ipc_monitor.db"
SCHEMA_PATH = _get_base_dir() / "database" / "schema.sql"


class DatabaseManager:
    """线程安全的 SQLite 数据库管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[Path] = None):
        if self._initialized:
            return
        self._initialized = True
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn.execute("PRAGMA journal_mode = WAL")
        return self._local.conn

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def _init_db(self):
        """首次运行：执行 schema.sql 建表"""
        if not SCHEMA_PATH.exists():
            return
        conn = self._get_conn()
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()

    # ------------------------------------------------------------------
    # 设备操作
    # ------------------------------------------------------------------
    def upsert_device(self, device_id: str, **kwargs) -> int:
        """插入或更新设备信息（避免 REPLACE 级联删除检测记录）"""
        conn = self._get_conn()
        # 先检查设备是否存在
        row = conn.execute("SELECT id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if row:
            # 存在则 UPDATE，只更新传入的字段，不重置计数器
            if kwargs:
                set_clauses = [f"{k} = ?" for k in kwargs.keys()]
                values = list(kwargs.values())
                values.append(device_id)
                sql = f"UPDATE devices SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?"
                conn.execute(sql, values)
                conn.commit()
            return 0
        else:
            # 不存在则 INSERT
            fields = ["device_id"] + list(kwargs.keys())
            values = [device_id] + list(kwargs.values())
            placeholders = ["?"] * len(fields)
            sql = f"INSERT INTO devices ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
            cur = conn.execute(sql, values)
            conn.commit()
            return cur.lastrowid

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_devices(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM devices ORDER BY group_name, device_id").fetchall()
        return [dict(r) for r in rows]

    def get_devices_by_group(self, group_name: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM devices WHERE group_name = ? ORDER BY device_id", (group_name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_device_status(self, device_id: str, status: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE devices SET status = ?, last_heartbeat = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
            (status, device_id),
        )
        conn.commit()

    def update_device_counters(self, device_id: str, is_ng: bool):
        conn = self._get_conn()
        if is_ng:
            conn.execute(
                "UPDATE devices SET total_count = total_count + 1, ng_count = ng_count + 1, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
                (device_id,),
            )
        else:
            conn.execute(
                "UPDATE devices SET total_count = total_count + 1, ok_count = ok_count + 1, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
                (device_id,),
            )
        conn.commit()

    def clear_all_records(self):
        """清空所有检测记录和报警（保留设备信息）"""
        conn = self._get_conn()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM detection_results")
            conn.execute("DELETE FROM alarms")
            conn.execute("UPDATE devices SET total_count = 0, ok_count = 0, ng_count = 0")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.commit()
        except Exception:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.rollback()
            raise

    def delete_device(self, device_id: str):
        conn = self._get_conn()
        conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
        conn.commit()

    # ------------------------------------------------------------------
    # 检测结果操作
    # ------------------------------------------------------------------
    def insert_detection(self, data: Dict[str, Any]) -> int:
        """插入检测结果，自动计算 is_ng"""
        is_ng = 0
        if data.get("grade", 0) > 1:
            is_ng = 1
        if data.get("defect", "normal") != "normal":
            is_ng = 1
        if data.get("position_ok", True) is False:
            is_ng = 1

        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO detection_results
            (device_id, timestamp, seq_id, grade, defect, position_ok, is_ng, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("device_id"),
                data.get("timestamp"),
                data.get("seq_id", 0),
                data.get("grade", 0),
                data.get("defect", "normal"),
                1 if data.get("position_ok", True) else 0,
                is_ng,
                data.get("_raw_json"),
            ),
        )
        conn.commit()
        result_id = cur.lastrowid

        # 同步更新设备计数
        self.update_device_counters(data.get("device_id"), is_ng == 1)
        return result_id

    def get_detections(
        self,
        device_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        defect: Optional[str] = None,
        is_ng: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        if defect:
            conditions.append("defect = ?")
            params.append(defect)
        if is_ng is not None:
            conditions.append("is_ng = ?")
            params.append(is_ng)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM detection_results {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_detection_by_id(self, result_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM detection_results WHERE id = ?", (result_id,)
        ).fetchone()
        return dict(row) if row else None

    def count_detections(self, **filters) -> int:
        conn = self._get_conn()
        conditions = []
        params = []
        for k, v in filters.items():
            if v is not None:
                conditions.append(f"{k} = ?")
                params.append(v)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        row = conn.execute(f"SELECT COUNT(*) FROM detection_results {where}", params).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # 报警操作
    # ------------------------------------------------------------------
    def insert_alarm(self, device_id: str, result_id: Optional[int], alarm_type: str,
                     alarm_level: str, message: str) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            """
            INSERT INTO alarms (device_id, result_id, alarm_type, alarm_level, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (device_id, result_id, alarm_type, alarm_level, message),
        )
        conn.commit()
        return cur.lastrowid

    def get_alarms(self, is_read: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        where = "WHERE is_read = ?" if is_read is not None else ""
        params = (is_read,) if is_read is not None else ()
        sql = f"SELECT * FROM alarms {where} ORDER BY created_at DESC LIMIT ?"
        params = (*params, limit) if isinstance(params, tuple) else (limit,)
        if is_read is None:
            params = (limit,)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def mark_alarm_read(self, alarm_id: int):
        conn = self._get_conn()
        conn.execute("UPDATE alarms SET is_read = 1 WHERE id = ?", (alarm_id,))
        conn.commit()

    def mark_all_alarms_read(self):
        conn = self._get_conn()
        conn.execute("UPDATE alarms SET is_read = 1")
        conn.commit()

    def get_unread_alarm_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM alarms WHERE is_read = 0").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # 统计查询
    # ------------------------------------------------------------------
    def get_hourly_stats(self, device_id: Optional[str] = None, date: Optional[str] = None) -> List[Dict]:
        """每小时检测数量趋势"""
        conn = self._get_conn()
        date = date or datetime.now().strftime("%Y-%m-%d")
        params = [f"{date}%"]
        where = "WHERE timestamp LIKE ?"
        if device_id:
            where += " AND device_id = ?"
            params.append(device_id)
        sql = f"""
            SELECT SUBSTR(timestamp, 12, 2) as hour,
                   COUNT(*) as total,
                   SUM(is_ng) as ng_count
            FROM detection_results
            {where}
            GROUP BY hour
            ORDER BY hour
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_daily_stats(self, device_id: Optional[str] = None, days: int = 7) -> List[Dict]:
        """近 N 天每日检测数量"""
        conn = self._get_conn()
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        params = [start]
        where = "WHERE DATE(timestamp) >= ?"
        if device_id:
            where += " AND device_id = ?"
            params.append(device_id)
        sql = f"""
            SELECT DATE(timestamp) as day,
                   COUNT(*) as total,
                   SUM(is_ng) as ng_count
            FROM detection_results
            {where}
            GROUP BY day
            ORDER BY day
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_defect_distribution(self, device_id: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict]:
        """缺陷类型分布"""
        conn = self._get_conn()
        conditions = []
        params = []
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"""
            SELECT defect, COUNT(*) as count
            FROM detection_results
            {where}
            GROUP BY defect
            ORDER BY count DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_device_yield(self, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict]:
        """各设备良率对比"""
        conn = self._get_conn()
        conditions = []
        params = []
        if start:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end:
            conditions.append("timestamp <= ?")
            params.append(end)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"""
            SELECT device_id,
                   COUNT(*) as total,
                   SUM(is_ng) as ng_count,
                   ROUND(100.0 * (1 - SUM(is_ng) * 1.0 / COUNT(*)), 2) as yield_rate
            FROM detection_results
            {where}
            GROUP BY device_id
            ORDER BY yield_rate
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 数据清理
    # ------------------------------------------------------------------
    def cleanup_old_data(self, retention_days: int):
        """清理超过 retention_days 的检测数据和报警"""
        if retention_days <= 0:
            return
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM detection_results WHERE created_at < ?", (cutoff,))
        conn.execute("DELETE FROM alarms WHERE created_at < ?", (cutoff,))
        conn.execute("DELETE FROM device_heartbeats WHERE heartbeat_at < ?", (cutoff,))
        conn.commit()


# 全局单例
db = DatabaseManager()
