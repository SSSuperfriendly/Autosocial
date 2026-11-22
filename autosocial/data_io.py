"""File I/O helpers for preferences, prompts, targets, and text files.

These functions are thin wrappers that centralise path defaults and
atomic-write behaviour so the rest of the codebase doesn't repeat them.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_text
from .preferences import (
    load_preferences,
    save_preferences,
    sync_interests_file,
)
from .services import write_csv_rows


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def load_user_preferences(path: str = "data/user_preferences.json") -> dict[str, Any]:
    prefs = load_preferences(path)
    sync_interests_file(prefs)
    return prefs


def save_user_preferences(data: dict[str, Any], path: str = "data/user_preferences.json") -> dict[str, Any]:
    prefs = save_preferences(data, path)
    sync_interests_file(prefs)
    return prefs


# ---------------------------------------------------------------------------
# Target schools CSV
# ---------------------------------------------------------------------------

def load_target_schools_table(path: str = "data/target_schools.csv") -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def save_target_schools_table(rows: list[dict[str, Any]], path: str = "data/target_schools.csv") -> None:
    fieldnames = ["school", "institute", "domains", "entry_urls", "search_hint"]
    cleaned: list[dict[str, str]] = []
    for row in rows:
        if not str(row.get("school") or "").strip():
            continue
        cleaned.append({name: str(row.get(name) or "").strip() for name in fieldnames})
    write_csv_rows(path, fieldnames, cleaned)


# ---------------------------------------------------------------------------
# Discovery prompts JSON
# ---------------------------------------------------------------------------

def load_discovery_prompts(path: str = "data/discovery_prompts.json") -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        defaults = [
            {
                "id": "research-fit",
                "name": "研究方向匹配",
                "enabled": True,
                "content": "根据用户填写的研究兴趣检索导师；保留可核查的研究方向、主页和邮箱，不推断未公开的招生名额。",
            },
            {
                "id": "official-page-only",
                "name": "官网页面约束",
                "enabled": True,
                "content": "优先导师主页、教师详情页、师资页、实验室成员页；排除新闻、公告、招生通知、泛首页。",
            },
        ]
        save_discovery_prompts(defaults, path)
        return defaults
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    output: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        output.append(
            {
                "id": str(item.get("id") or f"prompt-{index+1}"),
                "name": str(item.get("name") or f"提示词 {index+1}").strip(),
                "enabled": bool(item.get("enabled", True)),
                "content": str(item.get("content") or "").strip(),
            }
        )
    return output


def save_discovery_prompts(rows: list[dict[str, Any]], path: str = "data/discovery_prompts.json") -> None:
    cleaned: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        name = str(row.get("name") or "").strip()
        content = str(row.get("content") or "").strip()
        if not name and not content:
            continue
        cleaned.append(
            {
                "id": str(row.get("id") or f"prompt-{index+1}"),
                "name": name or f"提示词 {index+1}",
                "enabled": bool(row.get("enabled", True)),
                "content": content,
            }
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def active_prompt_suffix(path: str = "data/discovery_prompts.json") -> str:
    prompts = load_discovery_prompts(path)
    contents = [
        str(item.get("content") or "").strip()
        for item in prompts
        if item.get("enabled") and str(item.get("content") or "").strip()
    ]
    return " ".join(contents).strip()


# ---------------------------------------------------------------------------
# Plain-text helpers (student profile, email template, etc.)
# ---------------------------------------------------------------------------

def read_text_file(path: str) -> str:
    target = Path(path)
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8")


def write_text_file(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, content, encoding="utf-8")
