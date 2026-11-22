from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BASE_DIR / "runtime"
BROWSER_SESSIONS_FILE = RUNTIME_DIR / "browser_sessions.json"

_LOCK = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "has_connected": False,
        "updated_at": _now_iso(),
        "sessions": {},
    }


def _ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _read_state() -> dict:
    _ensure_runtime_dir()
    if not BROWSER_SESSIONS_FILE.exists():
        return _default_state()
    try:
        data = json.loads(BROWSER_SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    state = _default_state()
    state["has_connected"] = bool(data.get("has_connected", False))
    raw_sessions = data.get("sessions", {})
    if isinstance(raw_sessions, dict):
        normalized_sessions: dict[str, dict] = {}
        for session_id, payload in raw_sessions.items():
            if not isinstance(session_id, str) or not isinstance(payload, dict):
                continue
            normalized_sessions[session_id] = {
                "started_at": str(payload.get("started_at") or _now_iso()),
                "last_seen": str(payload.get("last_seen") or _now_iso()),
                "page": str(payload.get("page") or ""),
                "user_agent": str(payload.get("user_agent") or ""),
            }
        state["sessions"] = normalized_sessions
    state["updated_at"] = str(data.get("updated_at") or _now_iso())
    return state


def _write_state(state: dict) -> None:
    _ensure_runtime_dir()
    state["updated_at"] = _now_iso()
    tmp_file = BROWSER_SESSIONS_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(BROWSER_SESSIONS_FILE)


def reset_browser_sessions() -> dict:
    with _LOCK:
        state = _default_state()
        _write_state(state)
        return state


def start_browser_session(page: str = "", user_agent: str = "") -> dict[str, str | int]:
    with _LOCK:
        state = _read_state()
        session_id = uuid4().hex
        now = _now_iso()
        state["has_connected"] = True
        state["sessions"][session_id] = {
            "started_at": now,
            "last_seen": now,
            "page": page.strip(),
            "user_agent": user_agent.strip(),
        }
        _write_state(state)
        return {
            "session_id": session_id,
            "active_sessions": len(state["sessions"]),
            "started_at": now,
        }


def touch_browser_session(session_id: str, page: str = "", user_agent: str = "") -> dict[str, int]:
    with _LOCK:
        state = _read_state()
        if not session_id.strip():
            return {"active_sessions": len(state["sessions"])}
        session = state["sessions"].get(session_id)
        if session is None:
            state["has_connected"] = True
            session = {
                "started_at": _now_iso(),
                "last_seen": _now_iso(),
                "page": page.strip(),
                "user_agent": user_agent.strip(),
            }
            state["sessions"][session_id] = session
        session["last_seen"] = _now_iso()
        if page.strip():
            session["page"] = page.strip()
        if user_agent.strip():
            session["user_agent"] = user_agent.strip()
        _write_state(state)
        return {"active_sessions": len(state["sessions"])}


def end_browser_session(session_id: str) -> dict[str, int]:
    with _LOCK:
        state = _read_state()
        if not session_id.strip():
            return {"active_sessions": len(state["sessions"])}
        state["sessions"].pop(session_id, None)
        _write_state(state)
        return {"active_sessions": len(state["sessions"])}


def browser_session_status() -> dict:
    with _LOCK:
        state = _read_state()
        return {
            "has_connected": bool(state.get("has_connected", False)),
            "active_sessions": len(state.get("sessions", {})),
            "updated_at": state.get("updated_at"),
            "sessions": state.get("sessions", {}),
        }
