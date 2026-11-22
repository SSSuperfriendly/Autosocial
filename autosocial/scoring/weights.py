"""Scoring weight tables for professor ranking.

These are the only "magic numbers" that govern sort order across the
dashboard.  Keeping them together makes it easy to tune ranking without
hunting through orchestration code.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Note-priority keyword → weight
# Positive = push this professor higher in the list
# Negative = push this professor lower / exclude
# ---------------------------------------------------------------------------

NOTE_PRIORITY_POSITIVE: dict[str, int] = {
    "优先": 12,
    "重点": 10,
    "很匹配": 10,
    "强匹配": 10,
    "已回复": 16,
    "回复": 10,
    "沟通": 12,
    "面试": 16,
    "有名额": 14,
    "名额": 8,
    "尽快": 12,
    "ddl": 12,
    "deadline": 12,
    "催": 8,
    "跟进": 10,
    "愿意": 12,
    "同意": 12,
}

NOTE_PRIORITY_NEGATIVE: dict[str, int] = {
    "不匹配": -18,
    "低匹配": -12,
    "别联系": -24,
    "不联系": -24,
    "暂不": -14,
    "拒绝": -24,
    "没名额": -22,
    "无名额": -22,
    "不考虑": -20,
    "排除": -24,
    "慎重": -10,
    "慎": -8,
    "方向偏": -12,
}

# ---------------------------------------------------------------------------
# Contact-stage → (base_priority_score, reason_label)
# Used by score_professor_interaction_priority to give every professor a
# baseline rank before per-professor signals are applied.
# ---------------------------------------------------------------------------

STAGE_INTERACTION_META: dict[str, tuple[int, str]] = {
    "replied": (760, "已回复，需要优先处理"),
    "in_conversation": (740, "沟通中，需要持续跟进"),
    "sent_waiting": (640, "已联系，等待回复或准备跟进"),
    "ready_to_send": (580, "草稿已就绪，可优先发送"),
    "draft_ready": (520, "已有草稿，适合继续完善"),
    "shortlisted": (430, "已心仪，等待推进"),
    "reviewing": (360, "待复核，适合补信息"),
    "new": (160, "未联系，排在已联系导师之后"),
    "rejected": (20, "已排除，默认后置"),
}
