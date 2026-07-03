#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本（修正版）
- 包含所有 hidden imports（paho-mqtt, PyQt6, matplotlib, openpyxl）
- 清理旧构建后重新打包

【产线部署 mosquitto 说明】
1. 从 https://mosquitto.org/download/ 下载 Windows 版 mosquitto
2. 解压到 IPC_Monitor_System/resources/mosquitto/ 目录下
   目录结构应为：
     resources/mosquitto/
       mosquitto.exe
       mosquitto.dll
       ... (其他依赖文件)
3. 运行本打包脚本，mosquitto 会被自动包含进 exe
4. 产线 PC 无需单独安装 mosquitto，双击 exe 即可自动启动 broker
"""

import sys
import os
import subprocess
import shutil


def build():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    # 检查依赖
    required_pkgs = ["paho-mqtt", "PyQt6", "matplotlib", "openpyxl", "pyinstaller"]
    for pkg in required_pkgs:
        try:
            __import__(pkg.replace("-", "_").split("-")[0])
        except ImportError:
            print(f"[依赖缺失] {pkg} 未安装，正在安装...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    # 检查 mosquitto 是否存在（产线部署需要）
    mosquitto_dir = os.path.join(project_dir, "resources", "mosquitto")
    mosquitto_exe = os.path.join(mosquitto_dir, "mosquitto.exe" if os.name == "nt" else "mosquitto")
    if os.path.exists(mosquitto_exe):
        print(f"[✓] 检测到 mosquitto: {mosquitto_exe}")
    else:
        print(f"[!] 警告: 未找到 mosquitto ({mosquitto_exe})")
        print("    产线部署建议将 mosquitto 解压到 resources/mosquitto/ 目录下")
        print("    下载地址: https://mosquitto.org/download/")
        print("    如果不需要嵌入式 broker，可忽略此警告")

    # 彻底清理旧构建
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
    # 同时清理子目录的 __pycache__
    for root, dirs, files in os.walk(project_dir):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root, "__pycache__"), ignore_errors=True)

    # Windows 用分号 ; Linux/macOS 用冒号 :
    sep = ";" if os.name == "nt" else ":"

    # 所有 hidden imports — 解决 PyInstaller 检测不到子包的问题
    hidden_imports = [
        # paho-mqtt
        "--hidden-import", "paho",
        "--hidden-import", "paho.mqtt",
        "--hidden-import", "paho.mqtt.client",
        "--hidden-import", "paho.mqtt.enums",
        "--hidden-import", "paho.mqtt.properties",
        "--hidden-import", "paho.mqtt.packettypes",
        # PyQt6
        "--hidden-import", "PyQt6",
        "--hidden-import", "PyQt6.sip",
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtGui",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "PyQt6.QtMultimedia",
        # matplotlib
        "--hidden-import", "matplotlib",
        "--hidden-import", "matplotlib.backends",
        "--hidden-import", "matplotlib.backends.backend_qtagg",
        "--hidden-import", "matplotlib.pyplot",
        "--hidden-import", "matplotlib.dates",
        # openpyxl
        "--hidden-import", "openpyxl",
        "--hidden-import", "openpyxl.styles",
        "--hidden-import", "openpyxl.utils",
        "--hidden-import", "openpyxl.worksheet",
        "--hidden-import", "openpyxl.workbook",
        # sqlite3
        "--hidden-import", "sqlite3",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "IPC_Monitor_System",
        "--onefile",            # 单文件 exe
        "--windowed",           # 不显示控制台（GUI 程序）
        "--noconfirm",
        "--clean",
        # 图标
        "--icon", "resources/icons/app_icon.ico",
        # 数据文件
        "--add-data", f"database{sep}database",
        "--add-data", f"config{sep}config",
        "--add-data", f"utils{sep}utils",
        "--add-data", f"ui{sep}ui",
        "--add-data", f"core{sep}core",
        "--add-data", f"resources{sep}resources",
    ] + hidden_imports + ["main.py"]

    print(f"\n{'='*60}")
    print(f"  开始打包 IPC_Monitor_System")
    print(f"{'='*60}")
    print(f"项目目录: {project_dir}")
    print(f"\n执行命令:\n")
    print(" \\\n  ".join(cmd))
    print(f"\n{'='*60}\n")

    subprocess.check_call(cmd)

    exe_path = os.path.join(project_dir, "dist", "IPC_Monitor_System.exe")
    print(f"\n{'='*60}")
    print(f"  ✅ 打包成功！")
    print(f"  可执行文件: {exe_path}")
    print(f"  大小: {os.path.getsize(exe_path) / (1024*1024):.1f} MB")
    print(f"\n  运行方式：直接双击 .exe，无需 python 命令")
    print(f"{'='*60}")


if __name__ == "__main__":
    build()
