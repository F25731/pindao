from __future__ import annotations

import re
from typing import Iterable, Optional


_SPACE_RE = re.compile(r"\s+")


def normalize_search_keyword(value: str) -> str:
    if not value:
        return ""
    text = value.strip().lower().replace("\u3000", " ")
    text = _SPACE_RE.sub(" ", text)
    return text


def build_resource_search_text(
    name: str = "",
    tags: str = "",
    original_link: str = "",
    share_id: str = "",
    extract_code: str = "",
    new_share_link: str = "",
    new_share_id: str = "",
    new_extract_code: str = "",
    extra_parts: Optional[Iterable[str]] = None,
) -> str:
    parts = [
        name,
        tags,
        original_link,
        share_id,
        extract_code,
        new_share_link,
        new_share_id,
        new_extract_code,
    ]
    if extra_parts:
        parts.extend(extra_parts)
    text = " ".join(str(part).strip() for part in parts if part and str(part).strip())
    text = text.replace("\u3000", " ")
    text = _SPACE_RE.sub(" ", text)
    return text.strip().lower()
