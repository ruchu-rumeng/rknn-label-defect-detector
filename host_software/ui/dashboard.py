#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控看板
- 在线设备列表
- 最新检测结果表格
- 报警弹窗/声音
- 统计摘要卡片
"""

import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QSplitter, QFrame, QSizePolicy,
    QMessageBox, QDialog, QPushButton, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QPixmap
from PyQt6.QtMultimedia import QSoundEffect

from config.settings import settings
from core.mqtt_client import MQTTClient
from database.db_manager import db
from utils.image_utils import base64_to_pixmap


class StatCard(QFrame):
    """统计卡片组件"""
    def __init__(self, title: str, value: str, color: str = "#0ea5e9", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #ffffff;
                border-radius: 10px;
                border: 1px solid #e2e8f0;
            }}
        """)
        self.setMinimumHeight(100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        self.title = QLabel(title)
        self.title.setStyleSheet("color: #64748b; font-size: 13px;")
        self.value = QLabel(value)
        self.value.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: bold;")
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str):
        self.value.setText(value)


class DashboardPage(QWidget):
    """监控看板页面"""

    def __init__(self, mqtt: MQTTClient):
        super().__init__()
        self.mqtt = mqtt
        self._sound: QSoundEffect = None
        self._init_sound()
        self._init_ui()

    def _init_sound(self):
        self._sound = QSoundEffect(self)
        self._sound.setSource(QUrl.fromLocalFile(""))
        self._sound_enabled = bool(settings.get("alarm_sound_enabled", True))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ===== 顶部报警警示条（默认隐藏）=====
        self.alarm_banner = QLabel("暂无报警")
        self.alarm_banner.setStyleSheet("""
            background-color: #22c55e;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 15px;
            border-radius: 6px;
        """)
        self.alarm_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.alarm_banner.setMaximumHeight(40)
        layout.addWidget(self.alarm_banner)

        # ===== 顶部统计卡片 =====
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)
        self.card_total = StatCard("总检测数", "0", "#0ea5e9")
        self.card_ok = StatCard("良品数", "0", "#22c55e")
        self.card_ng = StatCard("不良品数", "0", "#ef4444")
        self.card_yield = StatCard("良率", "0.0%", "#a855f7")
        self.card_online = StatCard("在线设备", "0", "#f59e0b")
        for c in [self.card_total, self.card_ok, self.card_ng, self.card_yield, self.card_online]:
            cards_layout.addWidget(c)
        layout.addLayout(cards_layout)

        # ===== 中间：设备列表 + 检测记录 =====
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：设备列表
        self.device_group = QGroupBox("在线设备")
        self.device_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        dv_layout = QVBoxLayout(self.device_group)
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels(["设备ID", "状态", "总检测", "NG数", "良率"])
        self.device_table.horizontalHeader().setStretchLastSection(True)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        dv_layout.addWidget(self.device_table)
        splitter.addWidget(self.device_group)

        # 右侧：最新检测记录 + 工具栏
        self.result_group = QGroupBox("最新检测记录 (最近 50 条)")
        self.result_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        rv_layout = QVBoxLayout(self.result_group)
        
        # 工具栏：清空按钮（继承全局白底黑字样式）
        result_toolbar = QHBoxLayout()
        self.btn_clear = QPushButton("🗑 清空记录")
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #cbd5e1;
                padding: 6px 14px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border: 1px solid #94a3b8;
            }
        """)
        self.btn_clear.clicked.connect(self._clear_records)
        result_toolbar.addStretch()
        result_toolbar.addWidget(self.btn_clear)
        rv_layout.addLayout(result_toolbar)
        
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels([
            "ID", "设备", "时间", "等级", "缺陷", "NG"
        ])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setColumnWidth(0, 60)
        self.result_table.setColumnWidth(1, 100)
        self.result_table.setColumnWidth(2, 150)
        self.result_table.setColumnWidth(3, 60)
        self.result_table.setColumnWidth(4, 80)
        self.result_table.setColumnWidth(5, 60)
        self.result_table.doubleClicked.connect(self._on_result_double_click)
        rv_layout.addWidget(self.result_table)
        splitter.addWidget(self.result_group)
        splitter.setSizes([400, 800])
        layout.addWidget(splitter, 1)

        # ===== 底部：报警日志 =====
        self.alarm_group = QGroupBox("报警日志")
        self.alarm_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        al_layout = QVBoxLayout(self.alarm_group)
        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(5)
        self.alarm_table.setHorizontalHeaderLabels(["时间", "设备", "类型", "级别", "消息"])
        self.alarm_table.horizontalHeader().setStretchLastSection(True)
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alarm_table.setMaximumHeight(200)
        al_layout.addWidget(self.alarm_table)
        layout.addWidget(self.alarm_group)

        # ===== 调试信息面板（折叠式，显示 MQTT 连接状态和最后收到的消息） =====
        self.debug_group = QGroupBox("调试信息（MQTT 连接状态）")
        self.debug_group.setCheckable(True)
        self.debug_group.setChecked(False)  # 默认折叠
        self.debug_group.setStyleSheet("QGroupBox { font-size: 12px; color: #64748b; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        debug_layout = QVBoxLayout(self.debug_group)
        self.debug_label = QLabel("等待数据...")
        self.debug_label.setStyleSheet("color: #334155; font-family: Consolas, monospace; font-size: 11px; background-color: #f8fafc; padding: 8px; border-radius: 4px;")
        self.debug_label.setWordWrap(True)
        debug_layout.addWidget(self.debug_label)
        layout.addWidget(self.debug_group)

        # 连接信号，记录最后收到的消息
        self._last_msg_time = None
        self._last_msg_info = "暂无"
        self.mqtt.message_received.connect(self._on_debug_message)
        self.mqtt.connected.connect(self._on_debug_connected)
        self.mqtt.disconnected.connect(self._on_debug_disconnected)
        self.mqtt.connection_error.connect(self._on_debug_error)

    def _on_debug_message(self, data: dict):
        from datetime import datetime
        self._last_msg_time = datetime.now().strftime("%H:%M:%S")
        dev = data.get("device_id", "?")
        seq = data.get("seq_id", "?")
        grade = data.get("grade", "?")
        self._last_msg_info = f"[{dev}] seq={seq} grade={grade}"
        self._update_debug_display()

    def _on_debug_connected(self):
        self._update_debug_display()

    def _on_debug_disconnected(self):
        self._update_debug_display()

    def _on_debug_error(self, msg: str):
        self._last_msg_info = f"错误: {msg}"
        self._update_debug_display()

    def _update_debug_display(self):
        conn = "已连接" if self.mqtt.is_connected() else "未连接"
        topic = settings.get("mqtt_subscribe_topic", "elf2/+/detect/result")
        host = settings.get("mqtt_host", "127.0.0.1")
        port = settings.get("mqtt_port", 1883)
        lines = [
            f"MQTT 状态: {conn}",
            f"Broker: {host}:{port}",
            f"订阅: {topic}",
            f"最后消息: {self._last_msg_time or '无'} {self._last_msg_info}",
        ]
        self.debug_label.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh_data(self):
        self._refresh_stats()
        self._refresh_devices()
        self._refresh_results()
        self._refresh_alarms()

    def _refresh_stats(self):
        total = db.count_detections()
        ng = db.count_detections(is_ng=1)
        ok = total - ng
        yield_rate = round(100.0 * ok / total, 2) if total > 0 else 0.0
        online = len([d for d in db.get_all_devices() if d.get("status") == "online"])

        self.card_total.set_value(str(total))
        self.card_ok.set_value(str(ok))
        self.card_ng.set_value(str(ng))
        self.card_yield.set_value(f"{yield_rate}%")
        self.card_online.set_value(str(online))

    def _refresh_devices(self):
        devices = db.get_all_devices()
        self.device_table.setRowCount(len(devices))
        for i, d in enumerate(devices):
            total = d.get("total_count", 0)
            ng = d.get("ng_count", 0)
            yield_rate = f"{round(100.0 * (total - ng) / total, 1)}%" if total > 0 else "-"
            status = d.get("status", "unknown")
            status_color = "#22c55e" if status == "online" else "#ef4444"

            self.device_table.setItem(i, 0, QTableWidgetItem(d.get("device_id", "")))
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(status_color))
            self.device_table.setItem(i, 1, status_item)
            self.device_table.setItem(i, 2, QTableWidgetItem(str(total)))
            self.device_table.setItem(i, 3, QTableWidgetItem(str(ng)))
            self.device_table.setItem(i, 4, QTableWidgetItem(yield_rate))

    def _refresh_results(self):
        results = db.get_detections(limit=50)
        self.result_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.result_table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.result_table.setItem(i, 1, QTableWidgetItem(r.get("device_id", "")))
            self.result_table.setItem(i, 2, QTableWidgetItem(r.get("timestamp", "")))
            self.result_table.setItem(i, 3, QTableWidgetItem(str(r.get("grade", 0))))
            self.result_table.setItem(i, 4, QTableWidgetItem(r.get("defect", "")))
            ng_text = "NG" if r.get("is_ng") else "OK"
            ng_item = QTableWidgetItem(ng_text)
            if r.get("is_ng"):
                ng_item.setForeground(QColor("#ef4444"))
                ng_item.setFont(QFont("", -1, QFont.Weight.Bold))
            self.result_table.setItem(i, 5, ng_item)

    def _refresh_alarms(self):
        alarms = db.get_alarms(limit=20)
        self.alarm_table.setRowCount(len(alarms))
        for i, a in enumerate(alarms):
            self.alarm_table.setItem(i, 0, QTableWidgetItem(a.get("created_at", "")))
            self.alarm_table.setItem(i, 1, QTableWidgetItem(a.get("device_id", "")))
            self.alarm_table.setItem(i, 2, QTableWidgetItem(a.get("alarm_type", "")))
            level = a.get("alarm_level", "")
            level_item = QTableWidgetItem(level)
            if level == "critical":
                level_item.setForeground(QColor("#ef4444"))
            elif level == "warning":
                level_item.setForeground(QColor("#f59e0b"))
            self.alarm_table.setItem(i, 3, level_item)
            self.alarm_table.setItem(i, 4, QTableWidgetItem(a.get("message", "")))

    # ------------------------------------------------------------------
    # 报警处理
    # ------------------------------------------------------------------
    def on_alarm(self, device_id: str, alarm_type: str, message: str):
        # 界面警示条（红色背景 + 报警文字）
        self.alarm_banner.setText(f"⚠️ 报警: [{device_id}] {message}")
        self.alarm_banner.setStyleSheet("""
            background-color: #ef4444;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 15px;
            border-radius: 6px;
        """)
        # 5秒后自动恢复绿色
        QTimer.singleShot(5000, self._reset_alarm_banner)
        # 声音
        if self._sound_enabled and self._sound:
            try:
                self._sound.play()
            except Exception:
                pass

    def _reset_alarm_banner(self):
        """恢复报警条为正常状态"""
        self.alarm_banner.setText("暂无报警")
        self.alarm_banner.setStyleSheet("""
            background-color: #22c55e;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 15px;
            border-radius: 6px;
        """)

    def show_alarm_panel(self):
        pass  # 已在当前页面，无需额外操作

    def _clear_records(self):
        """手动清空检测记录（保留设备信息）"""
        msgBox = QMessageBox(self)
        msgBox.setWindowTitle("确认")
        msgBox.setText("确定清空所有检测记录吗？")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        yesBtn = msgBox.button(QMessageBox.StandardButton.Yes)
        noBtn = msgBox.button(QMessageBox.StandardButton.No)
        yesBtn.setText("是")
        noBtn.setText("否")
        # 弹窗样式：覆盖全局按钮样式，确保按钮文字可见
        msgBox.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
            }
            QPushButton {
                background-color: #f59e0b;
                color: #000000;
                border: 1px solid #d97706;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #d97706;
            }
            QLabel {
                color: #1e293b;
                font-size: 14px;
            }
        """)
        ret = msgBox.exec()
        if ret == QMessageBox.StandardButton.Yes:
            try:
                db.clear_all_records()
                # 清除去重缓存
                if self.mqtt:
                    self.mqtt.clear_dup_cache()
                self.refresh_data()
                # 成功提示
                okBox = QMessageBox(self)
                okBox.setWindowTitle("完成")
                okBox.setText("记录已清空")
                okBox.setStandardButtons(QMessageBox.StandardButton.Ok)
                okBtn = okBox.button(QMessageBox.StandardButton.Ok)
                okBtn.setText("确定")
                okBox.setStyleSheet("""
                    QPushButton {
                        background-color: #22c55e;
                        color: #000000;
                        border: 1px solid #16a34a;
                        padding: 8px 20px;
                        border-radius: 4px;
                        font-size: 13px;
                        font-weight: bold;
                        min-width: 60px;
                    }
                    QPushButton:hover {
                        background-color: #16a34a;
                    }
                    QLabel {
                        color: #1e293b;
                        font-size: 14px;
                    }
                """)
                okBox.exec()
            except Exception as e:
                errBox = QMessageBox(self)
                errBox.setWindowTitle("错误")
                errBox.setText(f"清空失败: {e}")
                errBox.setStandardButtons(QMessageBox.StandardButton.Ok)
                errBox.button(QMessageBox.StandardButton.Ok).setText("确定")
                errBox.setStyleSheet("""
                    QPushButton {
                        background-color: #ef4444;
                        color: #000000;
                        border: 1px solid #dc2626;
                        padding: 8px 20px;
                        border-radius: 4px;
                        font-size: 13px;
                        font-weight: bold;
                        min-width: 60px;
                    }
                    QPushButton:hover {
                        background-color: #dc2626;
                    }
                    QLabel {
                        color: #1e293b;
                        font-size: 14px;
                    }
                """)
                errBox.exec()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_result_double_click(self, index):
        row = index.row()
        result_id = self.result_table.item(row, 0).text()
        if not result_id:
            return
        result = db.get_detection_by_id(int(result_id))
        if not result:
            return
        # 显示详情弹窗
        dlg = QDialog(self)
        dlg.setWindowTitle(f"检测详情 #{result_id}")
        dlg.setMinimumSize(500, 400)
        dlg_layout = QVBoxLayout(dlg)
        grid = QGridLayout()
        fields = [
            ("设备ID", result.get("device_id")),
            ("时间", result.get("timestamp")),
            ("序号", result.get("seq_id")),
            ("等级", result.get("grade")),
            ("缺陷", result.get("defect")),
            ("偏移状态", "OK" if result.get("position_ok") else "NG"),
            ("是否NG", "是" if result.get("is_ng") else "否"),
        ]
        for i, (k, v) in enumerate(fields):
            grid.addWidget(QLabel(f"<b>{k}:</b>"), i, 0)
            grid.addWidget(QLabel(str(v)), i, 1)
        dlg_layout.addLayout(grid)
        dlg.exec()
