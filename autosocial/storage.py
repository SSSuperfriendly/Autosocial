from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


DEFAULT_FIT_LABEL = "待评估"


def connect(database_path: str) -> sqlite3.Connection:
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if not _column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db(conn: sqlite3.Connection) -> None:
    fit_label_default_sql = f"TEXT NOT NULL DEFAULT '{DEFAULT_FIT_LABEL}'"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS professors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school TEXT NOT NULL,
            institute TEXT,
            name TEXT,
            email TEXT,
            title TEXT,
            lab TEXT,
            profile_url TEXT NOT NULL UNIQUE,
            source_domain TEXT,
            research_summary TEXT,
            matched_topics TEXT,
            verification_status TEXT NOT NULL DEFAULT 'needs_review',
            shortlisted INTEGER NOT NULL DEFAULT 0,
            fit_score REAL NOT NULL DEFAULT 0,
            fit_label {fit_label_default_sql},
            fit_reason TEXT,
            contact_stage TEXT NOT NULL DEFAULT 'new',
            publication_signal TEXT,
            scholar_url TEXT,
            last_contacted_at TEXT,
            last_replied_at TEXT,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id INTEGER NOT NULL UNIQUE,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            approval_status TEXT NOT NULL DEFAULT 'needs_review',
            generator TEXT,
            generation_notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES professors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sent_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            professor_id INTEGER NOT NULL,
            to_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            smtp_message_id TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (draft_id) REFERENCES drafts(id) ON DELETE CASCADE,
            FOREIGN KEY (professor_id) REFERENCES professors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id INTEGER NOT NULL,
            message_id TEXT NOT NULL UNIQUE,
            from_email TEXT NOT NULL,
            subject TEXT,
            body_preview TEXT,
            received_at TEXT,
            raw_headers TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES professors(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS contact_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            professor_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('note', 'email_sent', 'reply', 'meeting')),
            content TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES professors(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS contact_events_professor_date
            ON contact_events(professor_id, occurred_at DESC, id DESC);
        """
    )
    _ensure_column(conn, "professors", "shortlisted", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "professors", "fit_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "professors", "fit_label", fit_label_default_sql)
    _ensure_column(conn, "professors", "fit_reason", "TEXT")
    _ensure_column(conn, "professors", "contact_stage", "TEXT NOT NULL DEFAULT 'new'")
    _ensure_column(conn, "professors", "publication_signal", "TEXT")
    _ensure_column(conn, "professors", "scholar_url", "TEXT")
    _ensure_column(conn, "professors", "last_contacted_at", "TEXT")
    _ensure_column(conn, "professors", "last_replied_at", "TEXT")
    _ensure_column(conn, "professors", "note_priority_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "professors", "note_priority_reason", "TEXT")
    _ensure_column(conn, "professors", "note_priority_source", "TEXT NOT NULL DEFAULT 'heuristic'")
    _ensure_column(conn, "professors", "trashed_at", "TEXT")
    _ensure_column(conn, "professors", "next_follow_up", "TEXT")
    _ensure_column(conn, "professors", "next_action", "TEXT")
    conn.commit()


def upsert_professor(conn: sqlite3.Connection, payload: dict[str, Any], *, commit: bool = True) -> int:
    """Refresh discovered facts while preserving the applicant's review and progress."""
    matched_topics = payload.get("matched_topics", [])
    evidence = payload.get("evidence_json", [])
    conn.execute(
        """
        INSERT INTO professors (
            school, institute, name, email, title, lab, profile_url, source_domain,
            research_summary, matched_topics, verification_status, shortlisted, fit_score,
            fit_label, fit_reason, contact_stage, publication_signal, scholar_url,
            evidence_json, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile_url) DO UPDATE SET
            school=excluded.school,
            institute=excluded.institute,
            name=COALESCE(excluded.name, professors.name),
            email=COALESCE(excluded.email, professors.email),
            title=COALESCE(excluded.title, professors.title),
            lab=COALESCE(excluded.lab, professors.lab),
            source_domain=COALESCE(excluded.source_domain, professors.source_domain),
            research_summary=COALESCE(excluded.research_summary, professors.research_summary),
            matched_topics=CASE
                WHEN excluded.matched_topics IS NOT NULL AND excluded.matched_topics != '[]'
                THEN excluded.matched_topics
                ELSE professors.matched_topics
            END,
            verification_status=professors.verification_status,
            shortlisted=professors.shortlisted,
            fit_score=COALESCE(excluded.fit_score, professors.fit_score),
            fit_label=COALESCE(excluded.fit_label, professors.fit_label),
            fit_reason=COALESCE(excluded.fit_reason, professors.fit_reason),
            contact_stage=professors.contact_stage,
            publication_signal=COALESCE(excluded.publication_signal, professors.publication_signal),
            scholar_url=COALESCE(excluded.scholar_url, professors.scholar_url),
            evidence_json=CASE
                WHEN excluded.evidence_json IS NOT NULL AND excluded.evidence_json != '[]'
                THEN excluded.evidence_json
                ELSE professors.evidence_json
            END,
            notes=professors.notes,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            payload.get("school", ""),
            payload.get("institute"),
            payload.get("name"),
            payload.get("email"),
            payload.get("title"),
            payload.get("lab"),
            payload["profile_url"],
            payload.get("source_domain"),
            payload.get("research_summary"),
            json.dumps(matched_topics, ensure_ascii=False),
            payload.get("verification_status", "needs_review"),
            1 if payload.get("shortlisted") else 0,
            float(payload.get("fit_score", 0) or 0),
            payload.get("fit_label") or DEFAULT_FIT_LABEL,
            payload.get("fit_reason"),
            payload.get("contact_stage") or "new",
            payload.get("publication_signal"),
            payload.get("scholar_url"),
            json.dumps(evidence, ensure_ascii=False),
            payload.get("notes"),
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT id FROM professors WHERE profile_url = ?", (payload["profile_url"],)).fetchone()
    return int(row["id"])


def upsert_draft(conn: sqlite3.Connection, payload: dict[str, Any], *, commit: bool = True) -> int:
    conn.execute(
        """
        INSERT INTO drafts (professor_id, subject, body, approval_status, generator, generation_notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(professor_id) DO UPDATE SET
            subject=excluded.subject,
            body=excluded.body,
            approval_status=CASE
                WHEN drafts.approval_status = 'sent' THEN drafts.approval_status
                ELSE excluded.approval_status
            END,
            generator=excluded.generator,
            generation_notes=excluded.generation_notes,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            payload["professor_id"],
            payload["subject"],
            payload["body"],
            payload.get("approval_status", "needs_review"),
            payload.get("generator"),
            payload.get("generation_notes"),
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute("SELECT id FROM drafts WHERE professor_id = ?", (payload["professor_id"],)).fetchone()
    return int(row["id"])


def update_professor_review(conn: sqlite3.Connection, professor_id: int, status: str, notes: str | None, *, commit: bool = True) -> None:
    conn.execute(
        """
        UPDATE professors
        SET verification_status = ?, notes = COALESCE(?, notes), updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, notes, professor_id),
    )
    if commit:
        conn.commit()


def update_professor_shortlist(conn: sqlite3.Connection, professor_id: int, shortlisted: bool, *, commit: bool = True) -> None:
    conn.execute(
        """
        UPDATE professors
        SET shortlisted = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (1 if shortlisted else 0, professor_id),
    )
    if commit:
        conn.commit()


def update_professor_pipeline(
    conn: sqlite3.Connection,
    professor_id: int,
    verification_status: str,
    shortlisted: bool,
    contact_stage: str,
    publication_signal: str | None,
    notes: str | None,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        UPDATE professors
        SET
            verification_status = ?,
            shortlisted = ?,
            contact_stage = ?,
            publication_signal = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            verification_status,
            1 if shortlisted else 0,
            contact_stage,
            publication_signal,
            notes,
            professor_id,
        ),
    )
    if commit:
        conn.commit()


def update_professor_fit_fields(
    conn: sqlite3.Connection,
    professor_id: int,
    fit_score: float,
    fit_label: str,
    fit_reason: str | None,
    scholar_url: str | None,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        UPDATE professors
        SET
            fit_score = ?,
            fit_label = ?,
            fit_reason = ?,
            scholar_url = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (fit_score, fit_label, fit_reason, scholar_url, professor_id),
    )
    if commit:
        conn.commit()


def update_professor_note_priority(
    conn: sqlite3.Connection,
    professor_id: int,
    note_priority_score: float,
    note_priority_reason: str | None,
    note_priority_source: str,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        UPDATE professors
        SET
            note_priority_score = ?,
            note_priority_reason = ?,
            note_priority_source = ?
        WHERE id = ?
        """,
        (note_priority_score, note_priority_reason, note_priority_source, professor_id),
    )
    if commit:
        conn.commit()


def delete_professors(conn: sqlite3.Connection, professor_ids: list[int], *, commit: bool = True) -> int:
    if not professor_ids:
        return 0
    placeholders = ",".join("?" for _ in professor_ids)
    cursor = conn.execute(f"DELETE FROM professors WHERE id IN ({placeholders})", professor_ids)
    if commit:
        conn.commit()
    return int(cursor.rowcount or 0)


def move_professors_to_trash(conn: sqlite3.Connection, professor_ids: list[int], *, commit: bool = True) -> int:
    if not professor_ids:
        return 0
    placeholders = ",".join("?" for _ in professor_ids)
    cursor = conn.execute(
        f"""
        UPDATE professors
        SET trashed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders}) AND trashed_at IS NULL
        """,
        professor_ids,
    )
    if commit:
        conn.commit()
    return int(cursor.rowcount or 0)


def restore_professors_from_trash(conn: sqlite3.Connection, professor_ids: list[int], *, commit: bool = True) -> int:
    if not professor_ids:
        return 0
    placeholders = ",".join("?" for _ in professor_ids)
    cursor = conn.execute(
        f"""
        UPDATE professors
        SET trashed_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders}) AND trashed_at IS NOT NULL
        """,
        professor_ids,
    )
    if commit:
        conn.commit()
    return int(cursor.rowcount or 0)


def update_draft_content(
    conn: sqlite3.Connection,
    draft_id: int,
    subject: str,
    body: str,
    approval_status: str | None = None,
    *,
    commit: bool = True,
) -> None:
    if approval_status is None:
        conn.execute(
            """
            UPDATE drafts
            SET subject = ?, body = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (subject, body, draft_id),
        )
    else:
        conn.execute(
            """
            UPDATE drafts
            SET subject = ?, body = ?, approval_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (subject, body, approval_status, draft_id),
        )
    if commit:
        conn.commit()


def update_draft_review(conn: sqlite3.Connection, draft_id: int, status: str, notes: str | None, *, commit: bool = True) -> None:
    conn.execute(
        """
        UPDATE drafts
        SET approval_status = ?, generation_notes = COALESCE(?, generation_notes), updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, notes, draft_id),
    )
    if commit:
        conn.commit()


def record_sent_email(
    conn: sqlite3.Connection,
    draft_id: int,
    professor_id: int,
    to_email: str,
    subject: str,
    status: str,
    smtp_message_id: str | None,
    error_message: str | None,
    *,
    commit: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO sent_emails (draft_id, professor_id, to_email, subject, smtp_message_id, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (draft_id, professor_id, to_email, subject, smtp_message_id, status, error_message),
    )
    if status == "sent":
        conn.execute(
            "UPDATE drafts SET approval_status = 'sent', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (draft_id,),
        )
        conn.execute(
            """
            UPDATE professors
            SET contact_stage = CASE WHEN contact_stage IN ('in_conversation', 'rejected') THEN contact_stage ELSE 'sent_waiting' END,
                last_contacted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (professor_id,),
        )
        conn.execute(
            """INSERT INTO contact_events (professor_id, kind, content, occurred_at)
               VALUES (?, 'email_sent', ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
            (professor_id, f"已通过 SMTP 发送邮件：{subject}"),
        )
    if commit:
        conn.commit()


def normalize_received_at(value: str | None) -> str:
    """Normalize both IMAP Date headers and timestamps from older databases."""
    parsed = None
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                pass
    parsed = parsed or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_reply(
    conn: sqlite3.Connection,
    professor_id: int,
    message_id: str,
    from_email: str,
    subject: str | None,
    body_preview: str | None,
    received_at: str | None,
    raw_headers: str | None,
    *,
    commit: bool = True,
) -> bool:
    received_at = normalize_received_at(received_at)
    inserted = conn.execute(
        """
        INSERT OR IGNORE INTO replies (
            professor_id, message_id, from_email, subject, body_preview, received_at, raw_headers
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (professor_id, message_id, from_email, subject, body_preview, received_at, raw_headers),
    ).rowcount > 0
    if inserted:
        conn.execute(
            """
            UPDATE professors
            SET contact_stage = CASE WHEN contact_stage IN ('in_conversation', 'rejected') THEN contact_stage ELSE 'replied' END,
                last_replied_at = CASE WHEN datetime(last_replied_at) > datetime(?) THEN last_replied_at ELSE ? END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (received_at, received_at, professor_id),
        )
        conn.execute(
            """INSERT INTO contact_events (professor_id, kind, content, occurred_at)
               VALUES (?, 'reply', ?, ?)""",
            (professor_id, f"收到邮件：{subject or '（无主题）'}\n{body_preview or ''}".strip(), received_at),
        )
    if commit:
        conn.commit()
    return inserted
