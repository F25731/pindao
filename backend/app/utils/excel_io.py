from pathlib import Path
from typing import List, Tuple, Optional
from openpyxl import Workbook, load_workbook


def read_excel(file_path: str) -> List[Tuple[str, str, str]]:
    """
    读取 Excel 文件，返回 [(名称, 标签, 链接), ...]。
    支持 .xlsx 格式，读取第一个 sheet，跳过表头。
    """
    wb = load_workbook(file_path, read_only=True)
    ws = wb.active
    rows = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if not row or len(row) < 3:
            continue
        name = str(row[0] or "").strip()
        tags = str(row[1] or "").strip()
        link = str(row[2] or "").strip()
        if name and link:
            rows.append((name, tags, link))

    wb.close()
    return rows


def write_excel(
    file_path: str,
    rows: List[Tuple[str, str, str]],
    headers: Tuple[str, str, str] = ("名称", "标签", "链接"),
):
    """
    写入 Excel 文件，格式为三列：名称、标签、链接。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "资源列表"

    ws.append(headers)
    for row in rows:
        ws.append(row)

    # 设置列宽
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 60

    wb.save(file_path)
