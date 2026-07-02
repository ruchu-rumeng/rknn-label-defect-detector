#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出工具：CSV / Excel 导出
"""

import base64
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import openpyxl
from openpyxl.styles import Font, Alignment

from config.settings import settings


def _get_export_dir() -> Path:
    """获取导出目录，确保可写"""
    export_dir = settings.get("export_dir", "")
    if export_dir:
        p = Path(export_dir)
    else:
        # 默认使用用户 Documents 目录，确保打包后也有写入权限
        docs = Path.home() / "Documents"
        if not docs.exists():
            docs = Path.home()
        p = docs / "IPC_Monitor_Exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


class ExportManager:
    """数据导出管理器"""

    DEFAULT_HEADERS = [
        ("id", "记录ID"),
        ("device_id", "设备ID"),
        ("timestamp", "检测时间"),
        ("seq_id", "序号"),
        ("grade", "能效等级"),
        ("defect", "缺陷类型"),
        ("position_ok", "偏移状态"),
        ("is_ng", "是否NG"),
    ]

    @classmethod
    def export_csv(cls, data: List[Dict[str, Any]], filepath: Optional[Path] = None) -> Tuple[bool, str]:
        """导出 CSV，返回 (成功, 文件路径或错误信息)

        :param filepath: 用户指定的完整保存路径，None 则自动生成
        """
        try:
            if filepath is None:
                export_dir = _get_export_dir()
                filename = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                filepath = export_dir / filename
            else:
                filepath = Path(filepath)
                filepath.parent.mkdir(parents=True, exist_ok=True)

            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([h[1] for h in cls.DEFAULT_HEADERS])
                for row in data:
                    writer.writerow([str(row.get(h[0], "")) for h in cls.DEFAULT_HEADERS])
            return True, str(filepath)
        except PermissionError as e:
            return False, f"权限不足，无法写入导出目录。请检查文件夹权限，或在设置中修改导出目录。\n({e})"
        except OSError as e:
            return False, f"文件系统错误：{e}"
        except Exception as e:
            return False, f"导出 CSV 失败：{e}"

    @classmethod
    def export_excel(cls, data: List[Dict[str, Any]], filepath: Optional[Path] = None) -> Tuple[bool, str]:
        """导出 Excel，返回 (成功, 文件路径或错误信息)

        :param filepath: 用户指定的完整保存路径，None 则自动生成
        """
        try:
            if filepath is None:
                export_dir = _get_export_dir()
                filename = f"detection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                filepath = export_dir / filename
            else:
                filepath = Path(filepath)
                filepath.parent.mkdir(parents=True, exist_ok=True)

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "检测结果"

            # 表头
            headers = [h[1] for h in cls.DEFAULT_HEADERS]
            ws.append(headers)
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

            # 数据行
            for row in data:
                ws.append([str(row.get(h[0], "")) for h in cls.DEFAULT_HEADERS])

            # 自动列宽
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        max_length = max(max_length, len(str(cell.value)))
                    except Exception:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width

            wb.save(filepath)
            return True, str(filepath)
        except PermissionError as e:
            return False, f"权限不足，无法写入导出目录。请检查文件夹权限，或在设置中修改导出目录。\n({e})"
        except OSError as e:
            return False, f"文件系统错误：{e}"
        except Exception as e:
            return False, f"导出 Excel 失败：{e}"

    @classmethod
    def export_image(cls, b64_str: str, filename: Optional[str] = None) -> str:
        """导出 base64 图片为本地文件"""
        if not b64_str:
            return ""
        try:
            export_dir = _get_export_dir()
            if not filename:
                filename = f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = export_dir / filename
            img_bytes = base64.b64decode(b64_str)
            with open(filepath, "wb") as f:
                f.write(img_bytes)
            return str(filepath)
        except Exception:
            return ""
