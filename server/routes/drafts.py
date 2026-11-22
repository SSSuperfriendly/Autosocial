from __future__ import annotations

from fastapi import APIRouter

from autosocial.config import AppConfig
from autosocial.dashboard_backend import (
    generate_drafts_for_selected,
    get_connection,
    load_drafts,
    save_draft_table,
)
from server.schemas import DraftGenerateRequest, TableRowsPayload


router = APIRouter(prefix="/api/drafts", tags=["drafts"])


@router.get("")
def get_drafts(shortlisted_only: bool = False):
    conn = get_connection(AppConfig())
    return {"rows": load_drafts(conn, shortlisted_only=shortlisted_only)}


@router.post("/generate")
def post_generate_drafts(payload: DraftGenerateRequest):
    conn = get_connection(AppConfig())
    count = generate_drafts_for_selected(
        AppConfig(),
        conn,
        payload.professor_ids,
        auto_approve=payload.auto_approve,
        thinking_mode=payload.thinking_mode,
    )
    return {"generated": count}


@router.put("")
def put_drafts(payload: TableRowsPayload):
    conn = get_connection(AppConfig())
    save_draft_table(conn, payload.rows)
    return {"ok": True}
