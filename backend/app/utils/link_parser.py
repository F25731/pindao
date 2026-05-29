import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs


def parse_share_link(link: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析光鸭分享链接，提取 share_id 和 extract_code。

    支持格式:
    - https://www.guangyapan.com/s/1906965843769446425_aeWXvywV3ZOZlzA7?code=x5ek
    - https://www.guangyapan.com/s/1906965843769446425_aeWXvywV3ZOZlzA7?code=x5ek#/share
    - 纯 share_id: 1906965843769446425_aeWXvywV3ZOZlzA7
    """
    if not link:
        return None, None

    link = link.strip()

    # 尝试从完整 URL 解析
    if "guangyapan.com" in link:
        try:
            # 去掉 hash 部分
            url_clean = link.split("#")[0]
            parsed = urlparse(url_clean)
            path = parsed.path

            # 提取 /s/{share_id}
            match = re.search(r"/s/([^/?#]+)", path)
            if match:
                share_id = match.group(1)
            else:
                return None, None

            # 提取 code 参数
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0] or ""

            return share_id, code
        except Exception:
            return None, None

    # 尝试匹配纯 share_id 格式: 数字_字母数字
    match = re.match(r"^(\d+_[A-Za-z0-9]+)$", link)
    if match:
        return match.group(1), ""

    return None, None


def build_share_link(share_id: str, code: str = "") -> str:
    """根据 share_id 和 code 生成官方格式分享链接。"""
    url = f"https://www.guangyapan.com/s/{share_id}"
    if code:
        url += f"?code={code}"
    return url


def normalize_name(name: str) -> str:
    """标准化资源名称，用于去重比较。"""
    if not name:
        return ""
    # 转小写，去除首尾空格，压缩连续空格
    result = name.strip().lower()
    result = re.sub(r"\s+", " ", result)
    # 去除常见无意义后缀
    result = re.sub(r"\.(zip|rar|7z|tar\.gz|mp4|mkv|avi)$", "", result)
    return result


def parse_tags(tags_str: str) -> list:
    """将标签字符串解析为列表。"""
    if not tags_str:
        return []
    separators = re.compile(r"[,，;；/|、\s]+")
    parts = separators.split(tags_str.strip())
    return [p.strip() for p in parts if p.strip()]
