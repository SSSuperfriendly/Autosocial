"""Applicant-owned follow-up plans and communication history.

These operations record progress only; they never send mail or call a model.
All changes belonging to a single action commit together.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from .storage import normalize_received_at


CONTACT_STAGES = (
    "new", "reviewing", "shortlisted", "draft_ready", "ready_to_send",
    "sent_waiting", "replied", "in_conversation", "rejected",
)
EVENT_KINDS = ("note", "email_sent", "reply", "meeting")


def require_professor(conn: sqlite3.Connection, professor_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM professors WHERE id = ? AND trashed_at IS NULL", (professor_id,)
    ).fetchone()
    if row is None:
        raise LookupError("导师不存在或已移入回收站。")
    return row


def normalize_follow_up(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("下次跟进日期请使用 YYYY-MM-DD 格式。")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("下次跟进日期无效。") from exc


def normalize_occurred_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("沟通时间不能为空。")
    value = value.strip()
    try:
        if len(value) == 10:
            normalized_date = normalize_follow_up(value)
            parsed = datetime.fromisoformat(str(normalized_date))
        else:
            if "T" not in value and " " not in value:
                raise ValueError
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("沟通时间请使用 ISO 日期或日期时间格式。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError) as exc:
        raise ValueError("沟通时间超出有效日期范围。") from exc


def update_follow_up(conn: sqlite3.Connection, professor_id: int, patch: dict[str, Any]) -> None:
    allowed = {"contact_stage", "next_follow_up", "next_action"}
    if set(patch) - allowed:
        raise ValueError("包含不支持的跟进字段。")
    values: dict[str, Any] = {}
    if "contact_stage" in patch:
        if patch["contact_stage"] not in CONTACT_STAGES:
            raise ValueError("请选择有效的联系阶段。")
        values["contact_stage"] = patch["contact_stage"]
    if "next_follow_up" in patch:
        values["next_follow_up"] = normalize_follow_up(patch["next_follow_up"])
    if "next_action" in patch:
        action = patch["next_action"]
        if action is not None and not isinstance(action, str):
            raise ValueError("下一步行动必须是文字。")
        action = (action or "").strip()
        if len(action) > 2000:
            raise ValueError("下一步行动请控制在 2000 字以内。")
        values["next_action"] = action or None
    with conn:
        require_professor(conn, professor_id)
        if values:
            assignments = ", ".join(f"{column} = ?" for column in values)
            conn.execute(
                f"UPDATE professors SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*values.values(), professor_id),
            )


def load_contact_events(conn: sqlite3.Connection, professor_id: int | None = None) -> list[dict[str, Any]]:
    if professor_id is not None:
        require_professor(conn, professor_id)
    query = """
        SELECT e.*, p.name AS professor_name, p.school
        FROM contact_events e JOIN professors p ON p.id = e.professor_id
        WHERE p.trashed_at IS NULL
    """
    parameters: tuple[Any, ...] = ()
    if professor_id is not None:
        query += " AND e.professor_id = ?"
        parameters = (professor_id,)
    query += " ORDER BY e.occurred_at DESC, e.id DESC"
    return [dict(row) for row in conn.execute(query, parameters).fetchall()]


def create_contact_event(
    conn: sqlite3.Connection,
    professor_id: int,
    kind: str,
    content: str,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    if kind not in EVENT_KINDS:
        raise ValueError("请选择有效的沟通记录类型。")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("请填写沟通内容。")
    content = content.strip()
    if len(content) > 20000:
        raise ValueError("沟通内容请控制在 20000 字以内。")
    occurred_at = normalize_occurred_at(occurred_at)
    with conn:
        professor = require_professor(conn, professor_id)
        cursor = conn.execute(
            "INSERT INTO contact_events (professor_id, kind, content, occurred_at) VALUES (?, ?, ?, ?)",
            (professor_id, kind, content, occurred_at),
        )
        if kind in {"email_sent", "reply"}:
            column = "last_contacted_at" if kind == "email_sent" else "last_replied_at"
            stage = "sent_waiting" if kind == "email_sent" else "replied"
            preserved_stages = {"in_conversation", "rejected"}
            if kind == "email_sent":
                preserved_stages.add("replied")
            if professor["contact_stage"] in preserved_stages:
                stage = professor["contact_stage"]
            conn.execute(
                f"""UPDATE professors SET {column} =
                    CASE WHEN datetime({column}) > datetime(?) THEN {column} ELSE ? END,
                    contact_stage = ?, shortlisted = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                (occurred_at, occurred_at, stage, professor_id),
            )
        event = dict(conn.execute("SELECT * FROM contact_events WHERE id = ?", (cursor.lastrowid,)).fetchone())
    return event


def delete_contact_event(conn: sqlite3.Connection, event_id: int) -> None:
    """Remove a mistaken entry and recompute summaries, preserving the user's stage."""
    with conn:
        event = conn.execute("SELECT professor_id FROM contact_events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise LookupError("沟通记录不存在。")
        professor_id = int(event["professor_id"])
        require_professor(conn, professor_id)
        conn.execute("DELETE FROM contact_events WHERE id = ?", (event_id,))
        dates: dict[str, str | None] = {}
        for kind, column, source in (
            ("email_sent", "last_contacted_at", "SELECT sent_at FROM sent_emails WHERE professor_id = ? AND status = 'sent'"),
            ("reply", "last_replied_at", "SELECT COALESCE(received_at, created_at) FROM replies WHERE professor_id = ?"),
        ):
            rows = conn.execute(
                "SELECT occurred_at FROM contact_events WHERE professor_id = ? AND kind = ? UNION ALL " + source,
                (professor_id, kind, professor_id),
            ).fetchall()
            dates[column] = max((normalize_received_at(row[0]) for row in rows), default=None)
        conn.execute(
            """UPDATE professors SET last_contacted_at = ?, last_replied_at = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (dates["last_contacted_at"], dates["last_replied_at"], professor_id),
        )
