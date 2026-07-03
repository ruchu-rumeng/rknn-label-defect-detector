#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统计分析页面（基于 matplotlib）
- 每小时/每日趋势
- 缺陷类型饼图
- 良率对比柱状图
- 偏移统计表格
"""

from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDateTimeEdit,
    QPushButton, QGroupBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PyQt6.QtCore import Qt, QDateTime

import matplotlib
matplotlib.use("qtagg")

# 配置 matplotlib 中文字体（Windows 常见中文字体）
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from database.db_manager import db


class MplCanvas(FigureCanvas):
    """matplotlib 画布组件"""
    def __init__(self, parent=None, width=5, height=3, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

    def clear(self):
        self.axes.clear()


class AnalyticsPage(QWidget):
    """统计分析页面"""

    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # 顶部过滤器
        filter_layout = QHBoxLayout()
        self.combo_device = QComboBox()
        self.combo_device.addItem("全部设备")
        self.combo_device.setMinimumWidth(150)

        self.dt_start = QDateTimeEdit()
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_start.setDateTime(QDateTime.currentDateTime().addDays(-7))
        self.dt_start.setCalendarPopup(True)

        self.dt_end = QDateTimeEdit()
        self.dt_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_end.setDateTime(QDateTime.currentDateTime())
        self.dt_end.setCalendarPopup(True)

        self.btn_refresh = QPushButton("刷新图表")
        self.btn_refresh.clicked.connect(self._refresh_all)
        self.btn_refresh_devices = QPushButton("刷新设备")
        self.btn_refresh_devices.clicked.connect(self._refresh_devices)

        filter_layout.addWidget(QLabel("设备:"))
        filter_layout.addWidget(self.combo_device)
        filter_layout.addWidget(QLabel("开始:"))
        filter_layout.addWidget(self.dt_start)
        filter_layout.addWidget(QLabel("结束:"))
        filter_layout.addWidget(self.dt_end)
        filter_layout.addWidget(self.btn_refresh)
        filter_layout.addWidget(self.btn_refresh_devices)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Tab 页
        self.tabs = QTabWidget()

        # Tab 1: 每小时趋势
        self.canvas_hourly = MplCanvas(self, width=8, height=4)
        self.tabs.addTab(self.canvas_hourly, "每小时趋势")

        # Tab 2: 每日趋势
        self.canvas_daily = MplCanvas(self, width=8, height=4)
        self.tabs.addTab(self.canvas_daily, "每日趋势")

        # Tab 3: 缺陷分布
        self.canvas_defect = MplCanvas(self, width=8, height=4)
        self.tabs.addTab(self.canvas_defect, "缺陷分布")

        # Tab 4: 良率对比
        self.canvas_yield = MplCanvas(self, width=8, height=4)
        self.tabs.addTab(self.canvas_yield, "良率对比")

        layout.addWidget(self.tabs, 1)
        self._refresh_devices()
        self._refresh_all()

    def _refresh_devices(self):
        self.combo_device.clear()
        self.combo_device.addItem("全部设备")
        for d in db.get_all_devices():
            self.combo_device.addItem(d.get("device_id", ""))

    def _device_filter(self):
        text = self.combo_device.currentText()
        return None if text == "全部设备" else text

    def _start_end(self):
        return (
            self.dt_start.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            self.dt_end.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
        )

    def _refresh_all(self):
        self._draw_hourly()
        self._draw_daily()
        self._draw_defect()
        self._draw_yield()

    def _draw_hourly(self):
        device = self._device_filter()
        today = datetime.now().strftime("%Y-%m-%d")
        stats = db.get_hourly_stats(device_id=device, date=today)
        hours = [f"{h:02d}" for h in range(24)]
        totals = [0] * 24
        ngs = [0] * 24
        for s in stats:
            h = int(s.get("hour", 0))
            totals[h] = s.get("total", 0)
            ngs[h] = s.get("ng_count", 0)
        x = range(24)
        c = self.canvas_hourly
        c.clear()
        ax = c.axes
        ax.bar([i - 0.2 for i in x], totals, 0.4, label="总检测", color="#0ea5e9")
        ax.bar([i + 0.2 for i in x], ngs, 0.4, label="NG数", color="#ef4444")
        ax.set_xticks(x)
        ax.set_xticklabels(hours, rotation=45)
        ax.set_title(f"{today} 每小时检测数量")
        ax.legend()
        ax.set_xlabel("小时")
        ax.set_ylabel("数量")
        c.fig.tight_layout()
        c.draw()

    def _draw_daily(self):
        device = self._device_filter()
        stats = db.get_daily_stats(device_id=device, days=7)
        days = [s.get("day", "") for s in stats]
        totals = [s.get("total", 0) for s in stats]
        ngs = [s.get("ng_count", 0) for s in stats]
        c = self.canvas_daily
        c.clear()
        ax = c.axes
        ax.plot(days, totals, marker="o", label="总检测", color="#0ea5e9")
        ax.plot(days, ngs, marker="o", label="NG数", color="#ef4444")
        ax.set_title("近7日检测数量趋势")
        ax.legend()
        ax.set_xlabel("日期")
        ax.set_ylabel("数量")
        ax.tick_params(axis="x", rotation=45)
        c.fig.tight_layout()
        c.draw()

    def _draw_defect(self):
        device = self._device_filter()
        start, end = self._start_end()
        stats = db.get_defect_distribution(device_id=device, start=start, end=end)
        labels = [s.get("defect", "") for s in stats]
        sizes = [s.get("count", 0) for s in stats]
        c = self.canvas_defect
        c.clear()
        ax = c.axes
        if sizes:
            ax.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.set_title("缺陷类型分布")
        c.fig.tight_layout()
        c.draw()

    def _draw_yield(self):
        start, end = self._start_end()
        stats = db.get_device_yield(start=start, end=end)
        devices = [s.get("device_id", "") for s in stats]
        yields = [s.get("yield_rate", 0.0) for s in stats]
        c = self.canvas_yield
        c.clear()
        ax = c.axes
        if devices:
            bars = ax.barh(devices, yields, color="#22c55e")
            ax.set_xlim(0, 100)
            ax.set_xlabel("良率 (%)")
            ax.set_title("各设备良率对比")
            for bar, val in zip(bars, yields):
                ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2, f"{val:.1f}%", va="center")
        c.fig.tight_layout()
        c.draw()
