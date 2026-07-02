#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT Broker 管理器
- 检测端口是否被占用
- 查找并启动 mosquitto（自带或系统）
- 退出时自动关闭
"""

import os
import sys
import time
import socket
import shutil
import subprocess
import threading
from pathlib import Path
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QProgressDialog, QGroupBox
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

from typing import Optional

from utils.logger import info, warn, error

from config.settings import settings


class BrokerManager(QObject):
    """管理嵌入式 mosquitto 生命周期"""
    broker_started = pyqtSignal(str)   # 启动成功，参数：broker 地址
    broker_failed = pyqtSignal(str)    # 启动失败，参数：错误信息
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None          # 自己启动的 mosquitto 进程
        self._host = None
        self._port = None
        self._is_self_started = False

    # ------------------------------------------------------------------
    # 端口检测
    # ------------------------------------------------------------------
    @staticmethod
    def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
        """尝试连接端口，判断 broker 是否已运行"""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, OSError, ConnectionRefusedError):
            return False

    # ------------------------------------------------------------------
    # 查找 mosquitto 可执行文件
    # ------------------------------------------------------------------
    def find_mosquitto(self) -> Optional[str]:
        """
        按优先级查找 mosquitto 可执行文件：
        1. 用户设置的路径（settings.local_broker_path）
        2. 程序自带目录 resources/mosquitto/
        3. 系统 PATH
        """
        candidates = []
        
        # 1. 用户自定义路径
        custom_path = settings.get("local_broker_path", "").strip()
        if custom_path and os.path.exists(custom_path):
            candidates.append(custom_path)
        
        # 2. 程序自带目录（支持打包后路径）
        if getattr(sys, '_MEIPASS', None):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(__file__))
        
        exe_name = "mosquitto.exe" if sys.platform == "win32" else "mosquitto"
        bundled = os.path.join(base, "resources", "mosquitto", exe_name)
        if os.path.exists(bundled):
            candidates.append(bundled)
        
        # 3. 系统 PATH
        system_path = shutil.which("mosquitto")
        if system_path:
            candidates.append(system_path)
        
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    # 生成最小化配置文件（写到程序自己的可写目录，避免 Program Files 权限问题）
    # ------------------------------------------------------------------
    def _ensure_config(self, config_dir: str) -> str:
        """在程序可写目录下生成最小配置，确保监听所有接口"""
        config_path = os.path.join(config_dir, "mosquitto_min.conf")
        
        config = """# 最小化 mosquitto 配置（上位机自动生成，明确监听所有接口）
listener 1883 0.0.0.0
allow_anonymous true
# 不持久化消息，纯内存模式
persistence false
connection_messages false
max_connections 50
"""
        # 如果旧配置存在，重写（确保 0.0.0.0 生效）
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config)
        return config_path

    def _get_writable_dir(self) -> str:
        """获取程序可写目录（exe 同目录 / 项目根目录）"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(__file__))

    # ------------------------------------------------------------------
    # 启动 broker
    # ------------------------------------------------------------------
    def start_local_broker(self, host: str = "127.0.0.1", port: int = 1883, custom_exe: Optional[str] = None) -> bool:
        """
        尝试启动本地 mosquitto。
        如果端口已占用（有外部 broker），直接复用。
        如果传入了 custom_exe，优先使用用户指定的路径。
        返回是否成功让 broker 可用。
        """
        self._host = host
        self._port = port
        
        # 先检查端口是否已运行
        if self.is_port_open(host, port):
            info(f"[BrokerManager] 检测到端口 {port} 已开放，复用现有 broker")
            self._is_self_started = False
            self.broker_started.emit(f"{host}:{port}")
            return True
        
        # 查找可执行文件
        if custom_exe and os.path.exists(custom_exe):
            exe = custom_exe
        else:
            exe = self.find_mosquitto()
        
        if not exe:
            self.broker_failed.emit(
                "未找到 mosquitto 可执行文件。\n"
                "请从 https://mosquitto.org/download/ 下载并安装，\n"
                "然后在系统设置中配置 mosquitto 安装路径。"
            )
            return False
        
        mosquitto_dir = os.path.dirname(exe)
        config_dir = self._get_writable_dir()
        config_file = self._ensure_config(config_dir)
        
        # 启动进程
        try:
            if sys.platform == "win32":
                # Windows: 用 CREATE_NO_WINDOW 避免弹黑窗
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                self._proc = subprocess.Popen(
                    [exe, "-c", config_file],
                    cwd=config_dir,
                    startupinfo=si,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self._proc = subprocess.Popen(
                    [exe, "-c", config_file],
                    cwd=config_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            
            # 等待 2 秒，检查进程是否存活且端口打开
            for _ in range(20):  # 2 秒，每 100ms 检查一次
                time.sleep(0.1)
                if self._proc.poll() is not None:
                    # 进程已退出
                    err = self._proc.stderr.read().decode("utf-8", errors="ignore") if self._proc.stderr else ""
                    self.broker_failed.emit(f"mosquitto 启动失败（退出码 {self._proc.returncode}）\n{err}")
                    self._proc = None
                    return False
                if self.is_port_open(host, port):
                    break
            else:
                self.broker_failed.emit("mosquitto 启动超时，端口仍未开放")
                self._kill_proc()
                return False
            
            self._is_self_started = True
            info(f"[BrokerManager] 本地 mosquitto 已启动: {exe} -> {host}:{port}")
            self.broker_started.emit(f"{host}:{port}")
            return True
            
        except Exception as e:
            self.broker_failed.emit(f"启动 mosquitto 异常: {e}")
            return False

    # ------------------------------------------------------------------
    # 停止 broker
    # ------------------------------------------------------------------
    def stop_local_broker(self):
        """如果是程序自己启动的 broker，关闭它"""
        if self._is_self_started and self._proc:
            self._kill_proc()
            self._is_self_started = False
            self._proc = None
            info("[BrokerManager] 本地 mosquitto 已关闭")

    def _kill_proc(self):
        if self._proc is None:
            return
        try:
            if sys.platform == "win32":
                # 先发送 Ctrl+C（优雅退出），再强制 kill
                self._proc.send_signal(subprocess.signal.CTRL_C_EVENT)
                self._proc.wait(timeout=2)
            else:
                self._proc.terminate()
                self._proc.wait(timeout=2)
        except Exception:
            pass
        finally:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
                self._proc.wait()

    # ------------------------------------------------------------------
    # 外部 broker 检测与配置
    # ------------------------------------------------------------------
    def check_external_broker(self, host: str, port: int) -> bool:
        """检查用户指定的外部 broker 是否可用"""
        return self.is_port_open(host, port)


# ----------------------------------------------------------------------
# 启动对话框：如果本地没有 broker，弹出让用户选择
# ----------------------------------------------------------------------
class BrokerStartupDialog(QDialog):
    """首次启动时检测不到 broker，提供选项"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MQTT Broker 配置")
        self.setMinimumWidth(520)
        self.setStyleSheet("""
            QDialog { background-color: #f8fafc; }
            QLabel { color: #334155; font-size: 13px; }
            QLineEdit { border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px; background-color: #ffffff; }
            QPushButton { background-color: #0ea5e9; color: #ffffff; border: none; padding: 8px 16px; border-radius: 6px; font-size: 13px; }
            QPushButton:hover { background-color: #0284c7; }
            QPushButton:disabled { background-color: #94a3b8; color: #ffffff; }
            QCheckBox { color: #334155; font-size: 13px; }
            QGroupBox { border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #64748b; font-size: 11px; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        layout.addWidget(QLabel("<b>未检测到 MQTT Broker，请选择运行方式：</b>"))
        
        # 方式1：使用已有外部 broker（默认选中）
        layout.addWidget(QLabel("<b>方式一：使用已有/外部 Broker（推荐已有环境）</b>"))
        hl = QHBoxLayout()
        hl.addWidget(QLabel("地址:"))
        self.edt_host = QLineEdit("127.0.0.1")
        self.edt_host.setFixedWidth(120)
        hl.addWidget(self.edt_host)
        hl.addWidget(QLabel("端口:"))
        self.edt_port = QLineEdit("1883")
        self.edt_port.setFixedWidth(60)
        hl.addWidget(self.edt_port)
        self.btn_test = QPushButton("🔄 测试连接")
        self.btn_test.clicked.connect(self._test_connection)
        hl.addWidget(self.btn_test)
        hl.addStretch()
        layout.addLayout(hl)
        
        # 方式2：启动本地 mosquitto
        layout.addWidget(QLabel("<b>方式二：自动启动本地 mosquitto（产线推荐）</b>"))
        self.chk_local = QCheckBox("启动程序时自动启动本地 mosquitto")
        self.chk_local.setChecked(False)
        self.chk_local.toggled.connect(self._on_local_toggled)
        layout.addWidget(self.chk_local)
        
        # 本地路径配置区域
        self.local_group = QGroupBox()
        local_layout = QVBoxLayout(self.local_group)
        
        # 提示文字
        hint = QLabel(
            "请从 <a href='https://mosquitto.org/download/'>https://mosquitto.org/download/</a> 下载安装，\n"
            "然后在下方配置 mosquitto.exe 的完整路径。\n"
            "配置完成后，程序会自动生成配置文件并启动 mosquitto。"
        )
        hint.setOpenExternalLinks(True)
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        hint.setWordWrap(True)
        local_layout.addWidget(hint)
        
        # 路径输入
        path_hl = QHBoxLayout()
        path_hl.addWidget(QLabel("路径:"))
        self.edt_path = QLineEdit()
        self.edt_path.setPlaceholderText("例如: C:\\Program Files\\mosquitto\\mosquitto.exe")
        self.edt_path.textChanged.connect(self._on_path_changed)
        path_hl.addWidget(self.edt_path)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self._browse_exe)
        path_hl.addWidget(self.btn_browse)
        local_layout.addLayout(path_hl)
        
        # 状态提示
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 11px;")
        local_layout.addWidget(self.lbl_status)
        
        layout.addWidget(self.local_group)
        self.local_group.setVisible(False)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_ok = QPushButton("✅ 确定")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_ok)
        
        self.btn_cancel = QPushButton("❌ 退出")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
        self.result = None
        self._on_local_toggled(False)
    
    def _on_local_toggled(self, checked):
        self.local_group.setVisible(checked)
        if not checked:
            self.edt_path.setText("")
            self.lbl_status.setText("")
    
    def _on_path_changed(self, text):
        if text.strip() and os.path.exists(text.strip()):
            self.lbl_status.setText("✅ 文件存在")
            self.lbl_status.setStyleSheet("color: #22c55e; font-size: 11px;")
        else:
            self.lbl_status.setText("⚠️ 文件不存在，请检查路径")
            self.lbl_status.setStyleSheet("color: #ef4444; font-size: 11px;")
    
    def _browse_exe(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 mosquitto 可执行文件",
            "", "可执行文件 (*.exe);;所有文件 (*.*)"
        )
        if path:
            self.edt_path.setText(path)
    
    def _test_connection(self):
        host = self.edt_host.text().strip()
        try:
            port = int(self.edt_port.text().strip())
        except ValueError:
            QMessageBox.warning(self, "测试失败", "端口格式错误")
            return
        if BrokerManager.is_port_open(host, port):
            QMessageBox.information(self, "测试成功", f"Broker {host}:{port} 连接正常！")
        else:
            QMessageBox.warning(self, "测试失败", f"无法连接到 {host}:{port}，请检查 broker 是否运行。")
    
    def get_config(self) -> dict:
        return {
            "host": self.edt_host.text().strip(),
            "port": int(self.edt_port.text().strip()) if self.edt_port.text().strip() else 1883,
            "use_local": self.chk_local.isChecked(),
            "local_path": self.edt_path.text().strip() if self.chk_local.isChecked() else "",
        }
