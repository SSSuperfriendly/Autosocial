from __future__ import annotations

from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from autosocial.config import AppConfig
from autosocial.dashboard_backend import get_connection, load_professors
from autosocial.tracking import create_contact_event, delete_contact_event, load_contact_events, update_follow_up


router = APIRouter(prefix="/api/tracking", tags=["tracking"])


class FollowUpPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_stage: str | None = None
    next_follow_up: str | None = None
    next_action: str | None = Field(default=None, max_length=2000)


class ContactEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["note", "email_sent", "reply", "meeting"]
    content: str = Field(min_length=1, max_length=20000)
    occurred_at: str | None = None


def _professor(conn, professor_id: int) -> dict:
    for row in load_professors(conn):
        if row["id"] == professor_id:
            return row
    raise LookupError("导师不存在或已移入回收站。")


def _error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc))


@router.get("")
def get_tracking():
    with closing(get_connection(AppConfig())) as conn:
        return {"professors": load_professors(conn), "events": load_contact_events(conn)}


@router.patch("/{professor_id}")
def patch_tracking(professor_id: int, payload: FollowUpPatch):
    with closing(get_connection(AppConfig())) as conn:
        try:
            update_follow_up(conn, professor_id, payload.model_dump(exclude_unset=True))
            return {"professor": _professor(conn, professor_id)}
        except (ValueError, LookupError) as exc:
            raise _error(exc) from exc


@router.get("/{professor_id}/events")
def get_events(professor_id: int):
    with closing(get_connection(AppConfig())) as conn:
        try:
            return {"events": load_contact_events(conn, professor_id)}
        except LookupError as exc:
            raise _error(exc) from exc


@router.post("/{professor_id}/events", status_code=201)
def post_event(professor_id: int, payload: ContactEventPayload):
    with closing(get_connection(AppConfig())) as conn:
        try:
            event = create_contact_event(conn, professor_id, **payload.model_dump())
            return {"event": event, "professor": _professor(conn, professor_id)}
        except (ValueError, LookupError) as exc:
            raise _error(exc) from exc


@router.delete("/events/{event_id}")
def delete_event(event_id: int):
    with closing(get_connection(AppConfig())) as conn:
        try:
            delete_contact_event(conn, event_id)
        except LookupError as exc:
            raise _error(exc) from exc
        return {"ok": True}
