from difflib import SequenceMatcher
from typing import List


def name_similarity(a: str, b: str) -> float:
    """计算两个名称的相似度 (0.0 - 1.0)。"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def tags_overlap(tags_a: List[str], tags_b: List[str]) -> float:
    """计算两组标签的重叠率 (0.0 - 1.0)。"""
    if not tags_a or not tags_b:
        return 0.0
    set_a = set(t.lower() for t in tags_a)
    set_b = set(t.lower() for t in tags_b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def is_fuzzy_duplicate(
    name_a: str,
    tags_a: List[str],
    name_b: str,
    tags_b: List[str],
    name_threshold: float = 0.8,
    tags_threshold: float = 0.5,
) -> tuple:
    """
    判断是否为疑似重复。
    返回 (is_duplicate, score, reason)
    """
    n_score = name_similarity(name_a, name_b)
    t_score = tags_overlap(tags_a, tags_b)

    if n_score >= name_threshold:
        reasons = []
        reasons.append(f"名称相似度 {n_score:.0%}")
        if t_score >= tags_threshold:
            reasons.append(f"标签重叠 {t_score:.0%}")

        combined_score = n_score * 0.7 + t_score * 0.3
        return True, combined_score, "，".join(reasons)

    if t_score >= 0.8 and n_score >= 0.6:
        reason = f"标签高度重叠 {t_score:.0%}，名称相似 {n_score:.0%}"
        combined_score = n_score * 0.5 + t_score * 0.5
        return True, combined_score, reason

    return False, 0.0, ""
