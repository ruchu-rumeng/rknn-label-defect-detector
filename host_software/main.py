#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
入口文件
"""

import sys
import os

# 确保资源路径在打包后正确
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtCore import Qt
from utils.logger import info, warn, error

from ui.main_window import MainWindow
from core.broker_manager import BrokerManager, BrokerStartupDialog
from config.settings import settings


def main():
    # 高DPI支持（兼容不同 PyQt6 版本）
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 设置应用全局图标（标题栏 + 任务栏 + 对话框）
    icon_path = None
    if getattr(sys, '_MEIPASS', None):
        icon_path = os.path.join(sys._MEIPASS, "resources", "icons", "app_icon.ico")
    else:
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "icons", "app_icon.ico")
    if icon_path and os.path.exists(icon_path):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(icon_path))
    # 全局样式
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f1f5f9;
        }
        QGroupBox {
            background-color: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            margin-top: 10px;
            padding: 15px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: #334155;
        }
        QTableWidget {
            background-color: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            gridline-color: #f1f5f9;
        }
        QTableWidget::item:selected {
            background-color: #bae6fd;
            color: #0f172a;
        }
        QHeaderView::section {
            background-color: #f8fafc;
            padding: 8px;
            border: 1px solid #e2e8f0;
            font-weight: bold;
        }
        QPushButton {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #cbd5e1;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #f1f5f9;
            border: 1px solid #94a3b8;
        }
        QPushButton:pressed {
            background-color: #e2e8f0;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
            border: 1px solid #cbd5e1;
            border-radius: 4px;
            padding: 6px;
            background-color: #ffffff;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
            border: 1px solid #0ea5e9;
        }
        QLabel {
            color: #334155;
        }
    """)

    # ================================================================
    # 自动启动 MQTT Broker（产线环境开箱即用）
    # ================================================================
    broker_manager = BrokerManager()
    broker_host = settings.get("mqtt_host", "127.0.0.1")
    broker_port = int(settings.get("mqtt_port", 1883))
    use_local = settings.get("broker_auto_start", True)

    broker_ready = False
    
    # 方式1：端口已有 broker 在运行 → 直接复用
    if BrokerManager.is_port_open(broker_host, broker_port):
        info(f"[main] 检测到端口 {broker_port} 已开放，复用现有 broker")
        broker_ready = True
    elif use_local:
        # 方式2：用户配置了本地 broker 路径 → 尝试启动
        custom_path = settings.get("local_broker_path", "").strip()
        if custom_path and os.path.exists(custom_path):
            info(f"[main] 使用用户配置的 mosquitto: {custom_path}")
            broker_ready = broker_manager.start_local_broker(broker_host, broker_port, custom_exe=custom_path)
        
        # 方式3：尝试查找自带/PATH
        if not broker_ready:
            broker_ready = broker_manager.start_local_broker(broker_host, broker_port)
    
    # 方式4：如果都失败了，弹引导对话框
    if not broker_ready:
        dlg = BrokerStartupDialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        cfg = dlg.get_config()
        broker_host = cfg["host"]
        broker_port = cfg["port"]
        settings.set("mqtt_host", broker_host)
        settings.set("mqtt_port", broker_port)
        settings.set("broker_auto_start", cfg["use_local"])
        
        if cfg["use_local"]:
            # 保存用户配置的 mosquitto 路径
            if cfg.get("local_path"):
                settings.set("local_broker_path", cfg["local_path"])
            broker_ready = broker_manager.start_local_broker(broker_host, broker_port, custom_exe=cfg.get("local_path"))
        else:
            broker_ready = broker_manager.check_external_broker(broker_host, broker_port)
        
        settings.save()
    
    if not broker_ready:
        QMessageBox.critical(
            None, "启动失败",
            "无法连接到 MQTT Broker，请检查配置或手动启动 mosquitto。"
        )
        sys.exit(1)
    
    # 把 broker_manager 传给主窗口，以便退出时关闭
    window = MainWindow(broker_manager=broker_manager)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
