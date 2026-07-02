import json
import os
import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """获取项目基础目录（兼容 PyInstaller 打包）"""
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_data_dir() -> Path:
    """获取用户数据目录（可写）"""
    if getattr(sys, 'frozen', False):
        return Path(os.path.dirname(sys.executable))
    return Path(__file__).parent.parent


DEFAULT_CONFIG = {
    # MQTT Broker（统一 key 名称，兼容旧版 mqtt_broker_host / mqtt_broker_port）
    "mqtt_host": "127.0.0.1",
    "mqtt_port": 1883,
    "mqtt_username": "",
    "mqtt_password": "",
    "mqtt_use_tls": False,
    "mqtt_subscribe_topic": "elf2/+/detect/result",
    "mqtt_cmd_topic_template": "elf2/{device_id}/cmd",
    "mqtt_heartbeat_interval": 30,
    # 本地 broker 自动启动
    "broker_auto_start": True,
    "local_broker_path": "",
    # 报警
    "alarm_sound_enabled": True,
    "alarm_popup_enabled": True,
    "alarm_grade_threshold": 1,
    "alarm_defect_types": ["damage", "stain", "wrinkle"],
    "alarm_offset_enabled": True,
    # 数据
    "data_retention_days": 90,
    "ui_refresh_interval": 1000,
    # 导出目录：空字符串表示使用系统默认（Documents）
    "export_dir": "",
}

CONFIG_FILE = _get_data_dir() / "data" / "config.json"

class Settings:
    """系统配置管理器，支持持久化到 JSON 文件"""

    def __init__(self):
        self._config = {}
        self.load()

    def load(self):
        """从文件加载配置，不存在则使用默认；自动迁移旧版 key"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            except Exception:
                self._config = {}
        
        # 兼容旧版 key 迁移：mqtt_broker_host -> mqtt_host, mqtt_broker_port -> mqtt_port
        if "mqtt_broker_host" in self._config and "mqtt_host" not in self._config:
            self._config["mqtt_host"] = self._config.pop("mqtt_broker_host")
        if "mqtt_broker_port" in self._config and "mqtt_port" not in self._config:
            self._config["mqtt_port"] = self._config.pop("mqtt_broker_port")
        
        # 补全缺失的默认键
        for k, v in DEFAULT_CONFIG.items():
            if k not in self._config:
                self._config[k] = v
        self._ensure_export_dir()
        # 迁移后自动保存
        if "mqtt_broker_host" not in self._config:
            self.save()

    def save(self):
        """保存到 JSON 文件"""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self._config.get(key, default)

    def set(self, key, value):
        self._config[key] = value

    def all(self):
        return dict(self._config)

    def _ensure_export_dir(self):
        export_dir = self.get("export_dir", "")
        if export_dir:
            Path(export_dir).mkdir(parents=True, exist_ok=True)
    def _get_export_dir(self) -> Path:
        """获取实际导出目录：优先用户配置，否则使用用户 Documents 目录"""
        export_dir = self.get("export_dir", "")
        if export_dir:
            return Path(export_dir)
        # 默认使用用户 Documents 目录，确保可写
        docs = Path.home() / "Documents"
        if not docs.exists():
            docs = Path.home()
        return docs / "IPC_Monitor_Exports"

settings = Settings()
