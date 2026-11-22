from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from autosocial.config import AppConfig
from autosocial.dashboard_backend import generate_drafts_for_selected, get_connection, save_professor_table
from autosocial.storage import update_draft_content
from server.schemas import WriterDraftRequest, WriterDraftSaveRequest


router = APIRouter(prefix="/api/writer", tags=["writer"])


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _find_professor(conn: sqlite3.Connection, payload: WriterDraftRequest) -> sqlite3.Row | None:
    if payload.professor_id and payload.professor_id > 0:
        row = conn.execute("SELECT * FROM professors WHERE id = ?", (payload.professor_id,)).fetchone()
        if row:
            return row

    email = _clean(payload.email)
    profile_url = _clean(payload.profile_url)
    name = _clean(payload.name)
    school = _clean(payload.school)

    if profile_url:
        row = conn.execute("SELECT * FROM professors WHERE profile_url = ? ORDER BY updated_at DESC LIMIT 1", (profile_url,)).fetchone()
        if row:
            return row
    if email:
        row = conn.execute("SELECT * FROM professors WHERE lower(email) = lower(?) ORDER BY updated_at DESC LIMIT 1", (email,)).fetchone()
        if row:
            return row
    if name and school:
        row = conn.execute(
            "SELECT * FROM professors WHERE name = ? AND school = ? ORDER BY updated_at DESC LIMIT 1",
            (name, school),
        ).fetchone()
        if row:
            return row
    return None


def _load_latest_draft(conn: sqlite3.Connection, professor_id: int) -> dict:
    row = conn.execute(
        """
        SELECT
            d.id AS draft_id,
            d.professor_id,
            d.subject,
            d.body,
            d.approval_status,
            d.generator,
            d.generation_notes,
            p.school,
            p.name,
            p.email,
            p.fit_score,
            p.contact_stage,
            p.shortlisted
        FROM drafts d
        JOIN professors p ON p.id = d.professor_id
        WHERE d.professor_id = ?
        ORDER BY d.updated_at DESC, d.id DESC
        LIMIT 1
        """,
        (professor_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="草稿生成失败，请检查后端日志。")
    return dict(row)


def _load_draft_by_id(conn: sqlite3.Connection, draft_id: int, professor_id: int) -> dict:
    row = conn.execute(
        """
        SELECT
            d.id AS draft_id,
            d.professor_id,
            d.subject,
            d.body,
            d.approval_status,
            d.generator,
            d.generation_notes,
            p.school,
            p.name,
            p.email,
            p.fit_score,
            p.contact_stage,
            p.shortlisted
        FROM drafts d
        JOIN professors p ON p.id = d.professor_id
        WHERE d.id = ? AND d.professor_id = ?
        """,
        (draft_id, professor_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="草稿不存在或不属于当前导师。")
    return dict(row)


def _merge_contact_stage(existing: sqlite3.Row | None, requested_stage: str) -> str:
    current_stage = str(existing["contact_stage"] or "new") if existing else "new"
    requested = _clean(requested_stage) or "new"
    if not existing:
        return requested
    if requested == "new":
        return current_stage
    if current_stage in {"sent_waiting", "replied", "in_conversation", "rejected"} and requested in {"new", "draft_ready"}:
        return current_stage
    return requested


def _save_professor_from_payload(conn: sqlite3.Connection, payload: WriterDraftRequest, contact_stage: str = "new") -> dict:
    if not _clean(payload.name):
        raise HTTPException(status_code=400, detail="请先填写导师姓名。")
    if not _clean(payload.school):
        raise HTTPException(status_code=400, detail="请先填写学校。")

    research_parts = [_clean(payload.research_summary), _clean(payload.professor_intro)]
    research_summary = "\n".join(part for part in research_parts if part)
    existing = _find_professor(conn, payload)
    professor_id = int(existing["id"]) if existing else int(payload.professor_id or 0)

    try:
        save_professor_table(
            conn,
            [
                {
                    "id": professor_id if professor_id > 0 else "",
                "school": _clean(payload.school),
                "institute": _clean(payload.institute),
                "name": _clean(payload.name),
                "email": _clean(payload.email),
                "title": _clean(payload.title),
                "profile_url": _clean(payload.profile_url),
                "research_summary": research_summary,
                "verification_status": str(existing["verification_status"] or "needs_review") if existing else "needs_review",
                "shortlisted": bool(existing["shortlisted"]) if existing else True,
                "contact_stage": _merge_contact_stage(existing, contact_stage),
                "notes": _clean(payload.notes),
                }
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    professor = _find_professor(conn, payload)
    if professor is None:
        raise HTTPException(status_code=500, detail="导师信息保存失败。")
    return dict(professor)


@router.post("/professor")
def post_writer_professor(payload: WriterDraftRequest):
    conn = get_connection(AppConfig())
    professor = _save_professor_from_payload(conn, payload, contact_stage="new")
    return {"professor": professor}


@router.post("/draft")
def post_writer_draft(payload: WriterDraftRequest):
    conn = get_connection(AppConfig())
    professor = _save_professor_from_payload(conn, payload, contact_stage="draft_ready")

    generated = generate_drafts_for_selected(
        AppConfig(),
        conn,
        [int(professor["id"])],
        auto_approve=False,
        thinking_mode=payload.thinking_mode,
    )
    if generated == 0:
        raise HTTPException(status_code=500, detail="没有生成任何草稿。")

    return {
        "professor": professor,
        "draft": _load_latest_draft(conn, int(professor["id"])),
    }


@router.post("/draft/save")
def post_writer_draft_save(payload: WriterDraftSaveRequest):
    if not payload.draft_id or not payload.professor_id:
        raise HTTPException(status_code=400, detail="缺少草稿 ID 或导师 ID。")
    if not _clean(payload.subject):
        raise HTTPException(status_code=400, detail="请先填写邮件主题。")
    if not _clean(payload.body):
        raise HTTPException(status_code=400, detail="请先填写邮件正文。")

    conn = get_connection(AppConfig())
    current = _load_draft_by_id(conn, payload.draft_id, payload.professor_id)
    update_draft_content(
        conn,
        payload.draft_id,
        _clean(payload.subject),
        str(payload.body or "").strip(),
        str(current.get("approval_status") or "needs_review"),
    )
    return {"draft": _load_draft_by_id(conn, payload.draft_id, payload.professor_id)}
