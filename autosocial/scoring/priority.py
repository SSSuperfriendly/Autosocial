"""Professor interaction-priority and note-priority scoring.

These scores determine the default sort order in the mentor pool:
interaction_priority is the primary sort key; note_priority feeds into it.
"""

from __future__ import annotations

from typing import Any

from .weights import (
    NOTE_PRIORITY_NEGATIVE,
    NOTE_PRIORITY_POSITIVE,
    STAGE_INTERACTION_META,
)


def score_note_priority_heuristic(notes: str | None) -> dict[str, Any]:
    """Derive a priority adjustment (-30..+30) from user notes via keyword
    matching.

    Returns:
        {note_priority_score, note_priority_reason, note_priority_source}
    """
    text = str(notes or "").strip().lower()
    if not text:
        return {
            "note_priority_score": 0,
            "note_priority_reason": "",
            "note_priority_source": "none",
        }

    score = 0
    hits: list[str] = []
    for keyword, weight in NOTE_PRIORITY_POSITIVE.items():
        if keyword.lower() in text:
            score += weight
            hits.append(keyword)
    for keyword, weight in NOTE_PRIORITY_NEGATIVE.items():
        if keyword.lower() in text:
            score += weight
            hits.append(keyword)

    clipped = max(-30, min(30, score))
    reason = (
        f"备注命中：{'、'.join(hits[:3])}" if hits else "备注暂无明确优先级信号"
    )
    return {
        "note_priority_score": clipped,
        "note_priority_reason": reason,
        "note_priority_source": "heuristic",
    }


def score_professor_interaction_priority(
    professor: dict[str, Any],
) -> dict[str, Any]:
    """Compute the primary sort key for the mentor pool.

    Combines contact stage, note priority, reply/contact history, shortlist
    status, and fit score into a single 0-900 score.

    Returns:
        {interaction_priority_score, interaction_priority_reason}
    """
    stage = str(professor.get("contact_stage") or "new")
    base, stage_reason = STAGE_INTERACTION_META.get(
        stage, (160, "状态未识别，按普通导师处理")
    )

    score = float(base)
    reasons = [stage_reason]

    # --- note priority ------------------------------------------------
    note_score = float(professor.get("note_priority_score") or 0)
    if note_score:
        score += note_score
        note_reason = str(professor.get("note_priority_reason") or "").strip()
        reasons.append(note_reason or f"备注调整 {note_score:+.0f}")

    # --- communication history ----------------------------------------
    if professor.get("last_replied_at"):
        score += 20
        reasons.append("有回信记录")
    if professor.get("last_contacted_at") and stage not in {
        "sent_waiting",
        "replied",
        "in_conversation",
    }:
        score += 10
        reasons.append("有联系记录")
    if professor.get("shortlisted") and stage in {
        "new",
        "reviewing",
        "shortlisted",
    }:
        score += 18
        reasons.append("已标记心仪")

    # --- fit score contribution ---------------------------------------
    fit_score = float(professor.get("fit_score") or 0)
    score += min(35.0, fit_score * 0.25)
    if fit_score >= 75:
        reasons.append("高匹配")
    elif fit_score < 35:
        reasons.append("匹配分较低")

    # --- rejected override --------------------------------------------
    if stage == "rejected" or str(professor.get("verification_status") or "") == "rejected":
        score = min(score, 80)
        reasons = ["已排除，默认后置"]

    return {
        "interaction_priority_score": round(max(0.0, min(900.0, score)), 1),
        "interaction_priority_reason": "；".join(
            reason for reason in reasons if reason
        )[:180],
    }
