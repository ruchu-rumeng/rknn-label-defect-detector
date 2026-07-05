#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统设置对话框
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QDialogButtonBox, QGroupBox, QPlainTextEdit, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt

from config.settings import settings


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        self.setMinimumWidth(500)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # MQTT 设置
        mqtt_group = QGroupBox("MQTT Broker 配置")
        mqtt_layout = QFormLayout(mqtt_group)
        self.edit_host = QLineEdit()
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.edit_user = QLineEdit()
        self.edit_pass = QLineEdit()
        self.edit_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.chk_tls = QCheckBox("启用 TLS/SSL")
        self.edit_sub_topic = QLineEdit()
        self.edit_cmd_template = QLineEdit()
        self.spin_hb_interval = QSpinBox()
        self.spin_hb_interval.setRange(5, 600)
        self.spin_hb_interval.setSuffix(" 秒")

        mqtt_layout.addRow("Broker 地址", self.edit_host)
        mqtt_layout.addRow("Broker 端口", self.spin_port)
        mqtt_layout.addRow("用户名", self.edit_user)
        mqtt_layout.addRow("密码", self.edit_pass)
        mqtt_layout.addRow(self.chk_tls)
        mqtt_layout.addRow("订阅 Topic", self.edit_sub_topic)
        mqtt_layout.addRow("命令 Topic 模板", self.edit_cmd_template)
        mqtt_layout.addRow("心跳超时判定", self.spin_hb_interval)
        layout.addWidget(mqtt_group)

        # 报警设置
        alarm_group = QGroupBox("报警规则")
        alarm_layout = QFormLayout(alarm_group)
        self.chk_alarm_sound = QCheckBox("启用报警声音")
        self.chk_alarm_popup = QCheckBox("启用报警弹窗")
        self.edit_defect_types = QLineEdit()
        self.edit_defect_types.setPlaceholderText("damage,stain,wrinkle")
        self.chk_offset_alarm = QCheckBox("偏移超标触发报警")

        alarm_layout.addRow(self.chk_alarm_sound)
        alarm_layout.addRow(self.chk_alarm_popup)
        alarm_layout.addRow("缺陷类型 (逗号分隔)", self.edit_defect_types)
        alarm_layout.addRow(self.chk_offset_alarm)
        layout.addWidget(alarm_group)

        # 本地 Broker 设置
        local_group = QGroupBox("本地 MQTT Broker（产线自动启动）")
        local_layout = QFormLayout(local_group)
        self.chk_auto_start = QCheckBox("启动程序时自动启动本地 mosquitto")
        self.chk_auto_start.setToolTip("如果端口 1883 空闲，程序会自动启动 mosquitto")
        
        hint = QLabel(
            "提示：先下载安装 mosquitto (<a href='https://mosquitto.org/download/'>官网下载</a>)，\n"
            "然后在下方配置 mosquitto.exe 的完整路径。\n"
            "程序会自动生成配置文件并启动。"
        )
        hint.setOpenExternalLinks(True)
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        hint.setWordWrap(True)
        
        self.edit_local_path = QLineEdit()
        self.edit_local_path.setPlaceholderText("例如: C:\Program Files\mosquitto\mosquitto.exe")
        self.btn_browse_local = QPushButton("浏览...")
        self.btn_browse_local.clicked.connect(self._browse_local_broker)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.edit_local_path)
        path_layout.addWidget(self.btn_browse_local)
        
        local_layout.addRow(self.chk_auto_start)
        local_layout.addRow(hint)
        local_layout.addRow("mosquitto 路径", path_layout)
        layout.addWidget(local_group)

        # 数据保留
        data_group = QGroupBox("数据保留")
        data_layout = QFormLayout(data_group)
        self.spin_retention = QSpinBox()
        self.spin_retention.setRange(0, 365)
        self.spin_retention.setSuffix(" 天")
        self.spin_retention.setSpecialValueText("永久保留")
        data_layout.addRow("自动清理 N 天前数据", self.spin_retention)
        layout.addWidget(data_group)

        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse_local_broker(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 mosquitto 可执行文件",
            "", "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if path:
            self.edit_local_path.setText(path)

    def _load_settings(self):
        self.edit_host.setText(settings.get("mqtt_host", "127.0.0.1"))
        self.spin_port.setValue(int(settings.get("mqtt_port", 1883)))
        self.edit_user.setText(settings.get("mqtt_username", ""))
        self.edit_pass.setText(settings.get("mqtt_password", ""))
        self.chk_tls.setChecked(bool(settings.get("mqtt_use_tls", False)))
        self.edit_sub_topic.setText(settings.get("mqtt_subscribe_topic", "elf2/+/detect/result"))
        self.edit_cmd_template.setText(settings.get("mqtt_cmd_topic_template", "elf2/{device_id}/cmd"))
        self.spin_hb_interval.setValue(int(settings.get("mqtt_heartbeat_interval", 30)))

        self.chk_alarm_sound.setChecked(bool(settings.get("alarm_sound_enabled", True)))
        self.chk_alarm_popup.setChecked(bool(settings.get("alarm_popup_enabled", True)))
        self.edit_defect_types.setText(",".join(settings.get("alarm_defect_types", ["damage", "stain", "wrinkle"])))
        self.chk_offset_alarm.setChecked(bool(settings.get("alarm_offset_enabled", True)))

        self.chk_auto_start.setChecked(bool(settings.get("broker_auto_start", True)))
        self.edit_local_path.setText(settings.get("local_broker_path", ""))

        self.spin_retention.setValue(int(settings.get("data_retention_days", 90)))

    def _on_ok(self):
        settings.set("mqtt_host", self.edit_host.text().strip())
        settings.set("mqtt_port", self.spin_port.value())
        settings.set("mqtt_username", self.edit_user.text().strip())
        settings.set("mqtt_password", self.edit_pass.text().strip())
        settings.set("mqtt_use_tls", self.chk_tls.isChecked())
        settings.set("mqtt_subscribe_topic", self.edit_sub_topic.text().strip())
        settings.set("mqtt_cmd_topic_template", self.edit_cmd_template.text().strip())
        settings.set("mqtt_heartbeat_interval", self.spin_hb_interval.value())

        settings.set("alarm_sound_enabled", self.chk_alarm_sound.isChecked())
        settings.set("alarm_popup_enabled", self.chk_alarm_popup.isChecked())
        settings.set("alarm_defect_types", [t.strip() for t in self.edit_defect_types.text().split(",") if t.strip()])
        settings.set("alarm_offset_enabled", self.chk_offset_alarm.isChecked())

        settings.set("broker_auto_start", self.chk_auto_start.isChecked())
        settings.set("local_broker_path", self.edit_local_path.text().strip())

        settings.set("data_retention_days", self.spin_retention.value())
        settings.save()
        self.accept()
