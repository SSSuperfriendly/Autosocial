from __future__ import annotations

from fastapi import APIRouter, HTTPException

from autosocial.config import AppConfig
from autosocial.dashboard_backend import (
    delete_professor_rows,
    get_connection,
    load_professors,
    refresh_professor_scores,
    restore_professor_rows,
    save_professor_table,
    trash_professor_rows,
)
from server.schemas import ProfessorDeleteRequest, TableRowsPayload


router = APIRouter(prefix="/api/professors", tags=["professors"])


@router.get("")
def get_professors(shortlisted_only: bool = False, trashed_only: bool = False, include_trashed: bool = False):
    conn = get_connection(AppConfig())
    return {
        "rows": load_professors(
            conn,
            shortlisted_only=shortlisted_only,
            trashed_only=trashed_only,
            include_trashed=include_trashed,
        )
    }


@router.put("")
def put_professors(payload: TableRowsPayload):
    conn = get_connection(AppConfig())
    try:
        save_professor_table(conn, payload.rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/delete")
def post_delete_professors(payload: ProfessorDeleteRequest):
    conn = get_connection(AppConfig())
    deleted = delete_professor_rows(conn, payload.professor_ids)
    return {"deleted": deleted}


@router.post("/trash")
def post_trash_professors(payload: ProfessorDeleteRequest):
    conn = get_connection(AppConfig())
    moved = trash_professor_rows(conn, payload.professor_ids)
    return {"moved": moved}


@router.post("/restore")
def post_restore_professors(payload: ProfessorDeleteRequest):
    conn = get_connection(AppConfig())
    restored = restore_professor_rows(conn, payload.professor_ids)
    return {"restored": restored}


@router.post("/rescore")
def post_rescore():
    conn = get_connection(AppConfig())
    updated = refresh_professor_scores(AppConfig(), conn)
    return {"updated": updated}
