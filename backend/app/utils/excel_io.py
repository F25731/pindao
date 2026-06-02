from pathlib import Path
from typing import List, Tuple, Generator, Sequence
from openpyxl import Workbook, load_workbook
import csv


def read_excel_stream(file_path: str, batch_size: int = 2000) -> Generator[List[Tuple[str, str, str]], None, None]:
    """
    流式读取 Excel 文件，每次 yield 一批行。
    适合大文件，不会一次性加载全部到内存。
    """
    wb = load_workbook(file_path, read_only=True)
    ws = wb.active
    batch = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if not row or len(row) < 3:
            continue
        name = str(row[0] or "").strip()
        tags = str(row[1] or "").strip()
        link = str(row[2] or "").strip()
        if name and link:
            batch.append((name, tags, link))
            if len(batch) >= batch_size:
                yield batch
                batch = []

    if batch:
        yield batch
    wb.close()


def read_csv_stream(file_path: str, batch_size: int = 2000) -> Generator[List[Tuple[str, str, str]], None, None]:
    """
    流式读取 CSV 文件，每次 yield 一批行。
    CSV 比 xlsx 快 10 倍以上，推荐百万级数据使用。
    """
    batch = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row or len(row) < 3:
                continue
            name = row[0].strip()
            tags = row[1].strip()
            link = row[2].strip()
            if name and link:
                batch.append((name, tags, link))
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
    if batch:
        yield batch


def read_file_stream(file_path: str, batch_size: int = 2000) -> Generator[List[Tuple[str, str, str]], None, None]:
    """根据文件扩展名自动选择读取方式。"""
    ext = Path(file_path).suffix.lower()
    if ext == ".csv":
        yield from read_csv_stream(file_path, batch_size)
    else:
        yield from read_excel_stream(file_path, batch_size)


def write_excel(
    file_path: str,
    rows: List[Sequence[str]],
    headers: Sequence[str] = ("名称", "标签", "链接"),
):
    """写入 Excel 文件。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "资源列表"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    widths = [40, 20, 65, 65, 24, 24]
    for index, width in enumerate(widths[:len(headers)], start=1):
        ws.column_dimensions[chr(64 + index)].width = width
    wb.save(file_path)
