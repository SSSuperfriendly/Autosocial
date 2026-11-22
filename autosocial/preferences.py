from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_text


DEFAULT_PREFERENCES: dict[str, Any] = {
    "research": {
        "primary_focus": "",
        "preferred_topics": [],
        "acceptable_topics": [],
        "excluded_topics": [],
        "free_text_notes": "",
    },
    "discovery": {
        "preferred_backend": "directory",
        "allow_bigmodel_search": True,
        "allow_openai_search": True,
        "allow_directory_crawl": True,
        "allow_ddg": False,
        "allow_hybrid": True,
        "limit_per_school": 4,
        "max_crawl_pages": 8,
        "max_crawl_depth": 1,
        "min_match_score": 35,
    },
    "workflow": {
        "default_contact_stage": "new",
        "auto_shortlist_after_verify": False,
    },
}


def _merge_defaults(defaults: Any, current: Any) -> Any:
    if isinstance(defaults, dict):
        merged = deepcopy(defaults)
        if isinstance(current, dict):
            for key, value in current.items():
                if key in merged:
                    merged[key] = _merge_defaults(merged[key], value)
                else:
                    merged[key] = value
        return merged
    return current if current is not None else deepcopy(defaults)


def normalize_text_list(items: list[str] | None) -> list[str]:
    if not items:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        value = str(item).strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def load_preferences(path: str = "data/user_preferences.json") -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        prefs = deepcopy(DEFAULT_PREFERENCES)
        save_preferences(prefs, path=path)
        return prefs
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        current = {}
    prefs = _merge_defaults(DEFAULT_PREFERENCES, current)
    prefs["research"]["preferred_topics"] = normalize_text_list(prefs["research"].get("preferred_topics"))
    prefs["research"]["acceptable_topics"] = normalize_text_list(prefs["research"].get("acceptable_topics"))
    prefs["research"]["excluded_topics"] = normalize_text_list(prefs["research"].get("excluded_topics"))
    return prefs


def save_preferences(data: dict[str, Any], path: str = "data/user_preferences.json") -> dict[str, Any]:
    prefs = _merge_defaults(DEFAULT_PREFERENCES, data)
    prefs["research"]["preferred_topics"] = normalize_text_list(prefs["research"].get("preferred_topics"))
    prefs["research"]["acceptable_topics"] = normalize_text_list(prefs["research"].get("acceptable_topics"))
    prefs["research"]["excluded_topics"] = normalize_text_list(prefs["research"].get("excluded_topics"))
    atomic_write_text(path, json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    return prefs


def preference_keywords(prefs: dict[str, Any]) -> list[str]:
    research = prefs.get("research", {})
    values = [
        research.get("primary_focus", ""),
        *(research.get("preferred_topics") or []),
        *(research.get("acceptable_topics") or []),
    ]
    return normalize_text_list(values)


def excluded_keywords(prefs: dict[str, Any]) -> list[str]:
    return normalize_text_list((prefs.get("research") or {}).get("excluded_topics") or [])


def sync_interests_file(prefs: dict[str, Any], path: str = "data/interests.txt") -> None:
    keywords = preference_keywords(prefs)
    target = Path(path)
    atomic_write_text(target, "\n".join(keywords) + "\n", encoding="utf-8")


def research_profile_summary(prefs: dict[str, Any]) -> str:
    research = prefs.get("research", {})
    primary = str(research.get("primary_focus") or "未设置").strip()
    preferred = "、".join(normalize_text_list(research.get("preferred_topics") or [])[:5])
    acceptable = "、".join(normalize_text_list(research.get("acceptable_topics") or [])[:5])
    excluded = "、".join(normalize_text_list(research.get("excluded_topics") or [])[:6])
    note = str(research.get("free_text_notes") or "").strip()
    parts = [f"主方向：{primary}"]
    if preferred:
        parts.append(f"重点偏好：{preferred}")
    if acceptable:
        parts.append(f"可接受交叉：{acceptable}")
    if excluded:
        parts.append(f"排除方向：{excluded}")
    if note:
        parts.append(f"补充说明：{note}")
    return "；".join(parts)
