#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备管理页面
- 设备列表（在线/离线状态）
- 分组管理
- 远程命令下发
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLineEdit, QComboBox, QGroupBox, QMessageBox,
    QDialog, QFormLayout, QDialogButtonBox, QPlainTextEdit
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.mqtt_client import MQTTClient
from database.db_manager import db
from utils.validators import validate_device_id


class AddDeviceDialog(QDialog):
    """添加/编辑设备对话框"""
    def __init__(self, parent=None, device=None):
        super().__init__(parent)
        self.device = device
        self.setWindowTitle("编辑设备" if device else "添加设备")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.edit_id = QLineEdit(device.get("device_id", "") if device else "")
        self.edit_name = QLineEdit(device.get("name", "") if device else "")
        self.edit_group = QLineEdit(device.get("group_name", "默认产线") if device else "默认产线")
        self.edit_location = QLineEdit(device.get("location", "") if device else "")
        layout.addRow("设备ID *", self.edit_id)
        layout.addRow("显示名称", self.edit_name)
        layout.addRow("所属产线", self.edit_group)
        layout.addRow("位置描述", self.edit_location)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)
        if device:
            self.edit_id.setEnabled(False)

    def _on_ok(self):
        if not validate_device_id(self.edit_id.text()):
            QMessageBox.warning(self, "错误", "设备ID 格式不合法（3-32位字母数字）")
            return
        self.accept()

    def get_data(self):
        return {
            "device_id": self.edit_id.text().strip(),
            "name": self.edit_name.text().strip(),
            "group_name": self.edit_group.text().strip() or "默认产线",
            "location": self.edit_location.text().strip(),
        }


class CmdDialog(QDialog):
    """命令下发对话框"""
    def __init__(self, device_id: str, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.setWindowTitle(f"下发命令 - {device_id}")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.cmd_type = QComboBox()
        self.cmd_type.addItems([
            "trigger_detect", "set_threshold", "restart_inference",
            "update_param", "get_status"
        ])
        self.cmd_params = QPlainTextEdit()
        self.cmd_params.setPlaceholderText('{"grade": 2, "offset_max": 0.08}')
        self.cmd_params.setMaximumHeight(80)
        layout.addRow("命令类型", self.cmd_type)
        layout.addRow("参数 (JSON)", self.cmd_params)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_cmd(self):
        import json
        params = self.cmd_params.toPlainText().strip()
        if params:
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                params = {}
        else:
            params = {}
        return self.cmd_type.currentText(), params


class DeviceManagerPage(QWidget):
    """设备管理页面"""

    def __init__(self, mqtt: MQTTClient):
        super().__init__()
        self.mqtt = mqtt
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # 工具栏
        toolbar = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索设备ID...")
        self.edit_search.setMaximumWidth(250)
        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self._do_search)
        self.edit_search.returnPressed.connect(self._do_search)
        self.btn_add = QPushButton("+ 添加设备")
        self.btn_add.clicked.connect(self._add_device)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_data)
        toolbar.addWidget(self.edit_search)
        toolbar.addWidget(self.btn_search)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_refresh)
        layout.addLayout(toolbar)

        # 设备列表
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "设备ID", "名称", "产线", "状态", "总检测", "NG", "良率", "最后心跳"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

        # 分组统计
        self.group_box = QGroupBox("产线分组统计")
        gb_layout = QHBoxLayout(self.group_box)
        self.group_label = QLabel("加载中...")
        gb_layout.addWidget(self.group_label)
        layout.addWidget(self.group_box)

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def refresh_data(self):
        devices = db.get_all_devices()
        self.table.setRowCount(len(devices))
        groups = {}
        for i, d in enumerate(devices):
            total = d.get("total_count", 0)
            ng = d.get("ng_count", 0)
            yield_rate = f"{round(100.0 * (total - ng) / total, 1)}%" if total > 0 else "-"
            status = d.get("status", "unknown")
            status_color = "#22c55e" if status == "online" else "#ef4444"

            self.table.setItem(i, 0, QTableWidgetItem(d.get("device_id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(d.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(d.get("group_name", "")))
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(status_color))
            self.table.setItem(i, 3, status_item)
            self.table.setItem(i, 4, QTableWidgetItem(str(total)))
            self.table.setItem(i, 5, QTableWidgetItem(str(ng)))
            self.table.setItem(i, 6, QTableWidgetItem(yield_rate))
            self.table.setItem(i, 7, QTableWidgetItem(str(d.get("last_heartbeat", ""))))

            g = d.get("group_name", "默认")
            groups[g] = groups.get(g, 0) + 1

        group_text = "  |  ".join([f"{k}: {v}台" for k, v in groups.items()])
        self.group_label.setText(group_text or "暂无分组")

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _do_search(self):
        keyword = self.edit_search.text().strip().lower()
        if not keyword:
            self.refresh_data()
            return
        devices = db.get_all_devices()
        filtered = [d for d in devices if keyword in d.get("device_id", "").lower()]
        self.table.setRowCount(len(filtered))
        for i, d in enumerate(filtered):
            total = d.get("total_count", 0)
            ng = d.get("ng_count", 0)
            yield_rate = f"{round(100.0 * (total - ng) / total, 1)}%" if total > 0 else "-"
            status = d.get("status", "unknown")
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor("#22c55e" if status == "online" else "#ef4444"))
            self.table.setItem(i, 0, QTableWidgetItem(d.get("device_id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(d.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(d.get("group_name", "")))
            self.table.setItem(i, 3, status_item)
            self.table.setItem(i, 4, QTableWidgetItem(str(total)))
            self.table.setItem(i, 5, QTableWidgetItem(str(ng)))
            self.table.setItem(i, 6, QTableWidgetItem(yield_rate))
            self.table.setItem(i, 7, QTableWidgetItem(str(d.get("last_heartbeat", ""))))

    def _add_device(self):
        dlg = AddDeviceDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            db.upsert_device(**data)
            self.refresh_data()

    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        device_id = self.table.item(row, 0).text()
        menu = QMenu(self)
        act_edit = menu.addAction("编辑设备")
        act_cmd = menu.addAction("下发命令")
        act_del = menu.addAction("删除设备")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_edit:
            self._edit_device(device_id)
        elif action == act_cmd:
            self._send_cmd(device_id)
        elif action == act_del:
            self._delete_device(device_id)

    def _edit_device(self, device_id: str):
        d = db.get_device(device_id)
        if not d:
            return
        dlg = AddDeviceDialog(self, d)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            db.upsert_device(**data)
            self.refresh_data()

    def _send_cmd(self, device_id: str):
        dlg = CmdDialog(device_id, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cmd, params = dlg.get_cmd()
            if self.mqtt.is_connected():
                ok = self.mqtt.publish_command(device_id, cmd, params)
                if ok:
                    msgBox = QMessageBox(self)
                    msgBox.setWindowTitle("成功")
                    msgBox.setText(f"命令已下发至 {device_id}")
                    msgBox.addButton("确定", QMessageBox.AcceptRole)
                    msgBox.exec()
                else:
                    msgBox = QMessageBox(self)
                    msgBox.setWindowTitle("失败")
                    msgBox.setText("命令下发失败")
                    msgBox.addButton("确定", QMessageBox.AcceptRole)
                    msgBox.exec()
            else:
                msgBox = QMessageBox(self)
                msgBox.setWindowTitle("错误")
                msgBox.setText("MQTT 未连接，无法下发命令")
                msgBox.addButton("确定", QMessageBox.AcceptRole)
                msgBox.exec()

    def _delete_device(self, device_id: str):
        msgBox = QMessageBox(self)
        msgBox.setWindowTitle("确认")
        msgBox.setText(f"确定删除设备 {device_id} 吗？")
        yesBtn = msgBox.addButton("是", QMessageBox.YesRole)
        noBtn = msgBox.addButton("否", QMessageBox.NoRole)
        msgBox.exec()
        if msgBox.clickedButton() == yesBtn:
            db.delete_device(device_id)
            self.refresh_data()
