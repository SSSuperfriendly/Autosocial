from __future__ import annotations

from fastapi import APIRouter, Request

from autosocial.config import AppConfig
from autosocial.dashboard_backend import cleanup_professor_draft_states, get_connection, load_system_status
from autosocial.runtime_manager import (
    browser_session_status,
    end_browser_session,
    start_browser_session,
    touch_browser_session,
)
from server.schemas import BrowserSessionPayload


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def get_system_status():
    return load_system_status(AppConfig())


@router.post("/cleanup-state")
def post_cleanup_state():
    conn = get_connection(AppConfig())
    return cleanup_professor_draft_states(conn)


@router.get("/browser-session")
def get_browser_session_status():
    return browser_session_status()


@router.post("/browser-session/start")
def post_browser_session_start(payload: BrowserSessionPayload, request: Request):
    return start_browser_session(page=payload.page, user_agent=request.headers.get("user-agent", ""))


@router.post("/browser-session/heartbeat")
def post_browser_session_heartbeat(payload: BrowserSessionPayload, request: Request):
    return touch_browser_session(payload.session_id, page=payload.page, user_agent=request.headers.get("user-agent", ""))


@router.post("/browser-session/end")
def post_browser_session_end(payload: BrowserSessionPayload):
    return end_browser_session(payload.session_id)
