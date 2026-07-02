#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT 客户端封装
- 基于 paho-mqtt
- 自动重连、断线恢复
- 消息去重（基于 device_id + seq_id）
- 心跳超时检测
"""

import json
import time
import threading
import hashlib
from typing import Callable, Dict, Any, Optional

import paho.mqtt.client as mqtt
from PyQt6.QtCore import QObject, pyqtSignal

from utils.logger import info, warn, error, debug

from config.settings import settings
from database.db_manager import db


class MQTTClient(QObject):
    """MQTT 客户端（Qt 信号驱动）"""

    # 信号定义
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    message_received = pyqtSignal(dict)   # 解析后的 JSON dict
    heartbeat_received = pyqtSignal(str)   # device_id
    connection_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._lock = threading.Lock()
        self._seen_seq: Dict[str, int] = {}  # 去重缓存 device_id -> latest_seq_id
        self._heartbeat_callbacks: Dict[str, float] = {}  # device_id -> last_heartbeat_time
        self._stop_event = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._callback_on_message: Optional[Callable] = None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def connect(self):
        host = settings.get("mqtt_host", "127.0.0.1")
        port = int(settings.get("mqtt_port", 1883))
        username = settings.get("mqtt_username", "")
        password = settings.get("mqtt_password", "")
        use_tls = bool(settings.get("mqtt_use_tls", False))
        sub_topic = settings.get("mqtt_subscribe_topic", "elf2/+/detect/result")
        hb_topic = "elf2/+/heartbeat"

        info(f"[MQTTClient] 尝试连接: {host}:{port}, 订阅: {sub_topic}")

        # 兼容 paho-mqtt 1.x 和 2.x
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"ipc-monitor-{int(time.time()*1000)}",
            )
        except AttributeError:
            # paho-mqtt 1.x
            self.client = mqtt.Client(
                client_id=f"ipc-monitor-{int(time.time()*1000)}"
            )
        if username:
            self.client.username_pw_set(username, password)
        if use_tls:
            self.client.tls_set()

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_connect_fail = self._on_connect_fail

        try:
            self.client.connect(host, port, keepalive=60)
            info("[MQTTClient] connect() 调用成功")
        except Exception as e:
            error(f"[MQTTClient] connect() 异常: {e}")
            self.connection_error.emit(str(e))
            return

        self.client.subscribe(sub_topic, qos=1)
        self.client.subscribe(hb_topic, qos=0)
        info(f"[MQTTClient] 已订阅: {sub_topic}, {hb_topic}")
        self.client.loop_start()

        # 启动心跳监控线程
        self._stop_event.clear()
        self._hb_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True)
        self._hb_thread.start()

    def disconnect(self):
        self._stop_event.set()
        if self._hb_thread:
            self._hb_thread.join(timeout=0.5)
        if self.client:
            try:
                # force=True 立即终止 loop_start 线程，避免阻塞
                self.client.loop_stop(force=True)
            except Exception:
                pass
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    # ------------------------------------------------------------------
    # 回调
    # ------------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        info(f"[MQTTClient] _on_connect: rc={rc}, flags={flags}")
        if rc == 0:
            self._connected = True
            info("[MQTTClient] 连接成功")
            self.connected.emit()
        else:
            err_msg = f"连接失败，返回码: {rc}"
            error(f"[MQTTClient] {err_msg}")
            self.connection_error.emit(err_msg)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        info(f"[MQTTClient] _on_disconnect: rc={rc}")
        self._connected = False
        self.disconnected.emit()

    def _on_connect_fail(self, client, userdata):
        error("[MQTTClient] _on_connect_fail: 连接失败")
        self.connection_error.emit("连接失败")
        self._connected = False

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="ignore")
        info(f"[MQTTClient] 收到消息: topic={topic}, payload={payload[:200]}...")

        # 心跳消息
        if "/heartbeat" in topic:
            device_id = self._extract_device_id(topic)
            if device_id:
                info(f"[MQTTClient] 心跳: {device_id}")
                self._heartbeat_callbacks[device_id] = time.time()
                db.update_device_status(device_id, "online")
                self.heartbeat_received.emit(device_id)
            else:
                warn(f"[MQTTClient] 心跳 topic 解析失败: {topic}")
            return

        # 检测结果消息
        if "/detect/result" in topic:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as e:
                error(f"[MQTTClient] JSON 解析失败: {e}, payload={payload[:200]}")
                return
            if not isinstance(data, dict):
                warn(f"[MQTTClient] 非 dict 格式: {type(data)}")
                return

            # 数据校验
            device_id = data.get("device_id")
            if not device_id:
                warn("[MQTTClient] 缺少 device_id")
                return
            seq_id = data.get("seq_id", 0)

            # 消息去重（基于 payload 内容 MD5 哈希，10秒窗口）
            payload_hash = hashlib.md5(payload.encode()).hexdigest()
            with self._lock:
                if payload_hash in self._seen_seq:
                    if time.time() - self._seen_seq[payload_hash] < 10:
                        info(f"[MQTTClient] 重复消息过滤: {device_id} seq={seq_id}")
                        return
                self._seen_seq[payload_hash] = time.time()
                now = time.time()
                stale = [k for k, v in self._seen_seq.items() if now - v > 60]
                for k in stale:
                    del self._seen_seq[k]

            data["_raw_json"] = payload
            info(f"[MQTTClient] 有效检测消息: {device_id}, seq={seq_id}, grade={data.get('grade')}")
            db.upsert_device(device_id, status="online")
            db.update_device_status(device_id, "online")
            self.message_received.emit(data)
            return
        
        info(f"[MQTTClient] 未匹配的 topic: {topic}")

    def clear_dup_cache(self):
        """手动清除去重缓存"""
        with self._lock:
            self._seen_seq.clear()

    def _extract_device_id(self, topic: str) -> Optional[str]:
        """从 topic elf2/{device_id}/... 中提取 device_id"""
        parts = topic.split("/")
        if len(parts) >= 2:
            return parts[1]
        return None

    # ------------------------------------------------------------------
    # 心跳监控
    # ------------------------------------------------------------------
    def _heartbeat_monitor(self):
        interval = int(settings.get("mqtt_heartbeat_interval", 30))
        while not self._stop_event.is_set():
            now = time.time()
            offline_ids = []
            for device_id, last in self._heartbeat_callbacks.items():
                if now - last > interval * 2:
                    offline_ids.append(device_id)
            for device_id in offline_ids:
                db.update_device_status(device_id, "offline")
                self._heartbeat_callbacks.pop(device_id, None)
            self._stop_event.wait(5)

    # ------------------------------------------------------------------
    # 命令下发
    # ------------------------------------------------------------------
    def publish_command(self, device_id: str, cmd: str, params: Optional[Dict] = None) -> bool:
        if not self.is_connected() or not self.client:
            return False
        template = settings.get("mqtt_cmd_topic_template", "elf2/{device_id}/cmd")
        topic = template.replace("{device_id}", device_id)
        payload = json.dumps({"cmd": cmd, "params": params or {}}, ensure_ascii=False)
        info = self.client.publish(topic, payload, qos=1)
        return info.rc == 0
