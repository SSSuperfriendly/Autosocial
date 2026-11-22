"""Professor research-fit scoring.

Produces a 0-100 fit_score with label and human-readable reason by comparing a
professor's profile text against the user's research preferences (preferred /
acceptable / excluded topics).
"""

from __future__ import annotations

from typing import Any

from ..preferences import excluded_keywords


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    """Return every *keyword* whose lowercased form appears in *text*."""
    lowered = text.lower()
    hits: list[str] = []
    for keyword in keywords:
        value = keyword.strip()
        if not value:
            continue
        if value.lower() in lowered:
            hits.append(value)
    return hits


def score_professor_fit(
    professor: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Score how well *professor* matches the user's research preferences.

    Returns a dict with keys:
        fit_score  – 0.0–100.0
        fit_label  – one of {"高匹配", "中匹配", "待复核", "低匹配"}
        fit_reason – semicolon-separated Chinese explanation
        publication_signal – preserved or placeholder
        scholar_url – Google Scholar link or preserved
    """
    research = preferences.get("research", {})
    preferred = [str(item) for item in research.get("preferred_topics") or []]
    acceptable = [str(item) for item in research.get("acceptable_topics") or []]
    excluded = excluded_keywords(preferences)
    primary = str(research.get("primary_focus") or "").strip()

    text_parts = [
        str(professor.get("school") or ""),
        str(professor.get("institute") or ""),
        str(professor.get("name") or ""),
        str(professor.get("title") or ""),
        str(professor.get("research_summary") or ""),
        " ".join(professor.get("matched_topics") or []),
        str(professor.get("profile_url") or ""),
    ]
    haystack = " ".join(text_parts)

    matched_preferred = _contains_any(haystack, preferred)
    matched_acceptable = _contains_any(haystack, acceptable)
    matched_primary = _contains_any(haystack, [primary]) if primary else []
    matched_excluded = _contains_any(haystack, excluded)

    score = 0.0
    if professor.get("name"):
        score += 12
    if professor.get("email"):
        score += 14
    if professor.get("title"):
        score += 8
    if professor.get("research_summary"):
        score += 8
    if matched_primary:
        score += 18
    score += min(28, len(set(matched_preferred)) * 10)
    score += min(18, len(set(matched_acceptable)) * 6)
    if professor.get("matched_topics"):
        score += min(12, len(professor.get("matched_topics") or []) * 4)
    if not professor.get("name") and not professor.get("email"):
        score -= 25
    if not matched_preferred and not matched_acceptable and not matched_primary:
        score -= 18
    if matched_excluded:
        score -= min(50, 18 * len(set(matched_excluded)))

    score = max(0.0, min(100.0, score))

    # --- label -----------------------------------------------------------
    if matched_excluded and score < 45:
        label = "低匹配"
    elif score >= 75:
        label = "高匹配"
    elif score >= 55:
        label = "中匹配"
    elif score >= 35:
        label = "待复核"
    else:
        label = "低匹配"

    # --- reason ----------------------------------------------------------
    reasons: list[str] = []
    if matched_preferred:
        reasons.append(f"命中重点方向：{'、'.join(sorted(set(matched_preferred))[:4])}")
    if matched_acceptable:
        reasons.append(f"命中可接受方向：{'、'.join(sorted(set(matched_acceptable))[:4])}")
    if matched_excluded:
        reasons.append(f"存在排除方向：{'、'.join(sorted(set(matched_excluded))[:4])}")
    if not professor.get("email"):
        reasons.append("缺少邮箱")
    if not professor.get("name"):
        reasons.append("缺少姓名")
    if not reasons:
        reasons.append("需要人工快速复核")

    # Build Google Scholar URL if none present
    scholar_url = professor.get("scholar_url")
    if not scholar_url:
        name = professor.get("name")
        school = professor.get("school")
        if name:
            query = f'"{name}" {school or ""}'.strip()
            from urllib.parse import quote_plus
            scholar_url = f"https://scholar.google.com/scholar?q={quote_plus(query)}"

    return {
        "fit_score": round(score, 1),
        "fit_label": label,
        "fit_reason": "；".join(reasons),
        "publication_signal": professor.get("publication_signal") or "待补充",
        "scholar_url": scholar_url,
    }
