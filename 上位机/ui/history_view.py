#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史查询页面
- 按时间范围、设备ID、缺陷类型查询
- 导出 CSV/Excel
- 查看详情
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QComboBox, QDateTimeEdit, QGroupBox,
    QMessageBox, QDialog, QGridLayout, QFileDialog
)
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QColor, QFont

from database.db_manager import db
from utils.export_utils import ExportManager


class HistoryViewPage(QWidget):
    """历史查询页面"""

    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # ===== 查询条件 =====
        filter_group = QGroupBox("查询条件")
        filter_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        fl = QHBoxLayout(filter_group)

        self.combo_device = QComboBox()
        self.combo_device.addItem("全部设备")
        self.combo_device.setMinimumWidth(150)

        self.combo_defect = QComboBox()
        self.combo_defect.addItems(["全部类型", "normal", "damage", "stain", "wrinkle"])

        self.combo_ng = QComboBox()
        self.combo_ng.addItems(["全部", "OK", "NG"])

        self.dt_start = QDateTimeEdit()
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_start.setDateTime(QDateTime.currentDateTime().addDays(-7))
        self.dt_start.setCalendarPopup(True)

        self.dt_end = QDateTimeEdit()
        self.dt_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_end.setDateTime(QDateTime.currentDateTime())
        self.dt_end.setCalendarPopup(True)

        self.btn_query = QPushButton("查询")
        self.btn_query.clicked.connect(self._do_query)
        self.btn_export_csv = QPushButton("导出 CSV")
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_excel = QPushButton("导出 Excel")
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_refresh = QPushButton("刷新设备列表")
        self.btn_refresh.clicked.connect(self._refresh_devices)

        fl.addWidget(QLabel("设备:"))
        fl.addWidget(self.combo_device)
        fl.addWidget(QLabel("缺陷:"))
        fl.addWidget(self.combo_defect)
        fl.addWidget(QLabel("结果:"))
        fl.addWidget(self.combo_ng)
        fl.addWidget(QLabel("开始:"))
        fl.addWidget(self.dt_start)
        fl.addWidget(QLabel("结束:"))
        fl.addWidget(self.dt_end)
        fl.addWidget(self.btn_query)
        fl.addWidget(self.btn_export_csv)
        fl.addWidget(self.btn_export_excel)
        fl.addWidget(self.btn_refresh)
        fl.addStretch()
        layout.addWidget(filter_group)

        # ===== 结果表格 =====
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "设备", "时间", "等级", "缺陷", "NG"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._show_detail)
        layout.addWidget(self.table)

        # 分页/统计
        self.label_count = QLabel("共 0 条记录")
        layout.addWidget(self.label_count)

        self._refresh_devices()
        self._do_query()

    def _refresh_devices(self):
        self.combo_device.clear()
        self.combo_device.addItem("全部设备")
        for d in db.get_all_devices():
            self.combo_device.addItem(d.get("device_id", ""))

    def _do_query(self):
        device = self.combo_device.currentText()
        if device == "全部设备":
            device = None
        defect = self.combo_defect.currentText()
        if defect == "全部类型":
            defect = None
        ng_text = self.combo_ng.currentText()
        is_ng = None
        if ng_text == "OK":
            is_ng = 0
        elif ng_text == "NG":
            is_ng = 1
        start = self.dt_start.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end = self.dt_end.dateTime().toString("yyyy-MM-dd HH:mm:ss")

        results = db.get_detections(
            device_id=device, start_time=start, end_time=end,
            defect=defect, is_ng=is_ng, limit=500
        )
        self._populate_table(results)
        self.label_count.setText(f"共 {len(results)} 条记录")

    def _populate_table(self, results):
        self.table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(r.get("device_id", "")))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("timestamp", "")))
            self.table.setItem(i, 3, QTableWidgetItem(str(r.get("grade", 0))))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("defect", "")))
            ng_text = "NG" if r.get("is_ng") else "OK"
            ng_item = QTableWidgetItem(ng_text)
            if r.get("is_ng"):
                ng_item.setForeground(QColor("#ef4444"))
                ng_item.setFont(QFont("", -1, QFont.Weight.Bold))
            self.table.setItem(i, 5, ng_item)

    def _export_csv(self):
        try:
            results = self._get_current_results()
            if not results:
                msgBox = QMessageBox(self)
                msgBox.setWindowTitle("提示")
                msgBox.setText("无数据可导出")
                msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
                msgBox.exec()
                return
            # 弹窗让用户选择保存位置
            default_name = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            path, _ = QFileDialog.getSaveFileName(
                self, "导出 CSV", default_name, "CSV 文件 (*.csv);;所有文件 (*.*)"
            )
            if not path:
                return  # 用户取消
            ok, msg = ExportManager.export_csv(results, filepath=path)
            msgBox = QMessageBox(self)
            if ok:
                msgBox.setWindowTitle("完成")
                msgBox.setText(f"CSV 已导出到:\n{msg}")
            else:
                msgBox.setWindowTitle("导出失败")
                msgBox.setText(msg)
                msgBox.setIcon(QMessageBox.Icon.Warning)
            msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
            msgBox.exec()
        except Exception as e:
            msgBox = QMessageBox(self)
            msgBox.setWindowTitle("错误")
            msgBox.setText(f"导出时发生错误：{e}")
            msgBox.setIcon(QMessageBox.Icon.Critical)
            msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
            msgBox.exec()

    def _export_excel(self):
        try:
            results = self._get_current_results()
            if not results:
                msgBox = QMessageBox(self)
                msgBox.setWindowTitle("提示")
                msgBox.setText("无数据可导出")
                msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
                msgBox.exec()
                return
            # 弹窗让用户选择保存位置
            default_name = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self, "导出 Excel", default_name, "Excel 文件 (*.xlsx);;所有文件 (*.*)"
            )
            if not path:
                return  # 用户取消
            ok, msg = ExportManager.export_excel(results, filepath=path)
            msgBox = QMessageBox(self)
            if ok:
                msgBox.setWindowTitle("完成")
                msgBox.setText(f"Excel 已导出到:\n{msg}")
            else:
                msgBox.setWindowTitle("导出失败")
                msgBox.setText(msg)
                msgBox.setIcon(QMessageBox.Icon.Warning)
            msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
            msgBox.exec()
        except Exception as e:
            msgBox = QMessageBox(self)
            msgBox.setWindowTitle("错误")
            msgBox.setText(f"导出时发生错误：{e}")
            msgBox.setIcon(QMessageBox.Icon.Critical)
            msgBox.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
            msgBox.exec()

    def _get_current_results(self) -> list:
        device = self.combo_device.currentText()
        if device == "全部设备":
            device = None
        defect = self.combo_defect.currentText()
        if defect == "全部类型":
            defect = None
        ng_text = self.combo_ng.currentText()
        is_ng = None
        if ng_text == "OK":
            is_ng = 0
        elif ng_text == "NG":
            is_ng = 1
        start = self.dt_start.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        end = self.dt_end.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        return db.get_detections(
            device_id=device, start_time=start, end_time=end,
            defect=defect, is_ng=is_ng, limit=500
        )

    def _show_detail(self, index):
        row = index.row()
        result_id = self.table.item(row, 0).text()
        if not result_id:
            return
        result = db.get_detection_by_id(int(result_id))
        if not result:
            return
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
