#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口 - 侧边栏导航 + 中央堆叠窗口
"""

import os
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QStackedWidget, QStatusBar,
    QFrame, QSizePolicy, QApplication, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon

import os
import sys

def _get_icon_path(filename: str) -> str:
    """获取图标文件路径（兼容 PyInstaller 打包）"""
    if getattr(sys, '_MEIPASS', None):
        return os.path.join(sys._MEIPASS, "resources", "icons", filename)
    return os.path.join(os.path.dirname(__file__), "..", "resources", "icons", filename)

from config.settings import settings
from core.mqtt_client import MQTTClient
from core.alarm_manager import alarm_manager
from database.db_manager import db

from ui.dashboard import DashboardPage
from ui.device_manager import DeviceManagerPage
from ui.history_view import HistoryViewPage
from ui.analytics import AnalyticsPage
from ui.settings_dialog import SettingsDialog


class NavButton(QPushButton):
    """自定义导航按钮"""
    def __init__(self, text: str, icon_text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #cbd5e1;
                border: none;
                padding: 10px 20px;
                text-align: left;
                font-size: 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
            QPushButton:checked {
                background-color: #0ea5e9;
                color: #000000;
                font-weight: bold;
            }
        """)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, broker_manager=None):
        super().__init__()
        self.broker_manager = broker_manager
        self.setWindowTitle("工业标签缺陷检测上位机管理系统")
        self.setMinimumSize(1280, 800)
        self.resize(1400, 900)

        # 设置窗口图标（标题栏 + 任务栏）
        icon_path = _get_icon_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.mqtt = MQTTClient()
        self._init_ui()
        self._init_signals()
        self._init_timers()
        self._start_mqtt()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ===== 侧边栏 =====
        self.sidebar = QFrame()
        self.sidebar.setStyleSheet("background-color: #1e293b;")
        self.sidebar.setMaximumWidth(220)
        self.sidebar.setMinimumWidth(200)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 20, 10, 20)
        side_layout.setSpacing(8)

        # Logo
        logo = QLabel("IPC Monitor")
        logo.setStyleSheet("color: #38bdf8; font-size: 20px; font-weight: bold; padding: 10px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(logo)
        side_layout.addSpacing(10)

        # 导航按钮
        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "监控看板", "dashboard"),
            ("devices", "设备管理", "devices"),
            ("history", "历史查询", "history"),
            ("analytics", "统计分析", "analytics"),
        ]
        for key, text, _ in nav_items:
            btn = NavButton(text)
            self.nav_buttons[key] = btn
            btn.clicked.connect(lambda checked, k=key: self._switch_page(k))
            side_layout.addWidget(btn)

        side_layout.addStretch()

        # MQTT 状态指示灯
        self.status_indicator = QLabel("● MQTT: 未连接")
        self.status_indicator.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 5px;")
        side_layout.addWidget(self.status_indicator)

        # 设置按钮
        self.btn_settings = NavButton("系统设置")
        self.btn_settings.clicked.connect(self._open_settings)
        side_layout.addWidget(self.btn_settings)

        # 报警计数器
        self.alarm_badge = QLabel("未读报警: 0")
        self.alarm_badge.setStyleSheet("color: #f87171; font-size: 12px; padding: 5px;")
        self.alarm_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alarm_badge.mousePressEvent = lambda e: self._show_alarms()
        side_layout.addWidget(self.alarm_badge)

        main_layout.addWidget(self.sidebar)

        # ===== 中央内容区 =====
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #f1f5f9;")

        self.page_dashboard = DashboardPage(self.mqtt)
        self.page_devices = DeviceManagerPage(self.mqtt)
        self.page_history = HistoryViewPage()
        self.page_analytics = AnalyticsPage()

        self.stack.addWidget(self.page_dashboard)
        self.stack.addWidget(self.page_devices)
        self.stack.addWidget(self.page_history)
        self.stack.addWidget(self.page_analytics)

        main_layout.addWidget(self.stack, 1)

        # 状态栏
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("就绪")
        self.setStatusBar(self.status_bar)

        # 默认选中第一个
        self._switch_page("dashboard")

    def _init_signals(self):
        self.mqtt.connected.connect(self._on_mqtt_connected)
        self.mqtt.disconnected.connect(self._on_mqtt_disconnected)
        self.mqtt.connection_error.connect(self._on_mqtt_error)
        self.mqtt.message_received.connect(self._on_message)
        self.mqtt.heartbeat_received.connect(self._on_heartbeat)
        alarm_manager.alarm_triggered.connect(self._on_alarm)

    def _init_timers(self):
        # UI 刷新定时器
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._periodic_refresh)
        interval = int(settings.get("ui_refresh_interval", 1000))
        self.refresh_timer.start(interval)

        # 数据清理定时器 (每小时检查一次)
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._cleanup_old_data)
        self.cleanup_timer.start(3600 * 1000)  # 1小时

    def _start_mqtt(self):
        self.mqtt.connect()

    # ------------------------------------------------------------------
    # 页面切换
    # ------------------------------------------------------------------
    def _switch_page(self, key: str):
        mapping = {
            "dashboard": 0,
            "devices": 1,
            "history": 2,
            "analytics": 3,
        }
        idx = mapping.get(key, 0)
        self.stack.setCurrentIndex(idx)
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        from PyQt6.QtWidgets import QDialog
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # 先停止 MQTT，延迟 500ms 后再重启，避免阻塞 UI
            self.mqtt.disconnect()
            QTimer.singleShot(500, self._start_mqtt)

    def _show_alarms(self):
        self.page_dashboard.show_alarm_panel()
        self._switch_page("dashboard")

    # ------------------------------------------------------------------
    # MQTT 信号处理
    # ------------------------------------------------------------------
    def _on_mqtt_connected(self):
        self.status_indicator.setText("● MQTT: 已连接")
        self.status_indicator.setStyleSheet("color: #4ade80; font-size: 12px; padding: 5px;")
        self.status_bar.showMessage("MQTT 已连接")

    def _on_mqtt_disconnected(self):
        self.status_indicator.setText("● MQTT: 未连接")
        self.status_indicator.setStyleSheet("color: #f87171; font-size: 12px; padding: 5px;")
        self.status_bar.showMessage("MQTT 已断开")

    def _on_mqtt_error(self, msg: str):
        self.status_bar.showMessage(f"MQTT 错误: {msg}")

    def _on_message(self, data: dict):
        from core.data_processor import DataProcessor
        try:
            DataProcessor.process(data)
            self.status_bar.showMessage(f"收到 {data.get('device_id')} 检测数据 #{data.get('seq_id')}")
        except Exception as e:
            self.status_bar.showMessage(f"数据处理错误: {e}")

    def _on_heartbeat(self, device_id: str):
        self.status_bar.showMessage(f"心跳: {device_id} 在线", 2000)

    def _on_alarm(self, device_id: str, alarm_type: str, message: str):
        # 更新报警徽标
        count = db.get_unread_alarm_count()
        self.alarm_badge.setText(f"未读报警: {count}")
        # 通知看板页面
        self.page_dashboard.on_alarm(device_id, alarm_type, message)

    # ------------------------------------------------------------------
    # 定时刷新
    # ------------------------------------------------------------------
    def _periodic_refresh(self):
        # 刷新各页面数据
        self.page_dashboard.refresh_data()
        self.page_devices.refresh_data()
        # 更新报警计数
        count = db.get_unread_alarm_count()
        self.alarm_badge.setText(f"未读报警: {count}")

    def _cleanup_old_data(self):
        days = int(settings.get("data_retention_days", 90))
        if days > 0:
            db.cleanup_old_data(days)
            self.status_bar.showMessage(f"已清理 {days} 天前的历史数据", 3000)

    def closeEvent(self, event):
        # 先停止所有定时器，避免退出卡顿
        self.refresh_timer.stop()
        self.cleanup_timer.stop()
        self.mqtt.disconnect()
        # 注：不关闭本地 mosquitto，保持 broker 持续运行
        # 开发板连接不会断，重新打开上位机即可直接接收数据
        event.accept()
