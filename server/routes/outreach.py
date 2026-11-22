from __future__ import annotations

from fastapi import APIRouter

from autosocial.config import AppConfig
from autosocial.dashboard_backend import (
    get_connection,
    load_replies,
    send_selected_professors,
    sync_all_replies,
)
from server.schemas import ReplySyncRequest, SendRequest


router = APIRouter(prefix="/api/outreach", tags=["outreach"])


@router.post("/send")
def post_send(payload: SendRequest):
    conn = get_connection(AppConfig())
    return send_selected_professors(
        AppConfig(),
        conn,
        payload.professor_ids,
        auto_prepare=payload.auto_prepare,
        dry_run=payload.dry_run,
    )


@router.post("/replies/sync")
def post_sync_replies(payload: ReplySyncRequest):
    conn = get_connection(AppConfig())
    total = sync_all_replies(AppConfig(), conn, payload.days)
    return {"total": total}


@router.get("/replies")
def get_replies():
    conn = get_connection(AppConfig())
    return {"rows": load_replies(conn)}
