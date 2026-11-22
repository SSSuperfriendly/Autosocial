from __future__ import annotations

from fastapi import APIRouter

from autosocial.dashboard_backend import (
    load_discovery_prompts,
    load_target_schools_table,
    load_user_preferences,
    read_text_file,
    save_discovery_prompts,
    save_target_schools_table,
    save_user_preferences,
    write_text_file,
)
from server.schemas import PreferencesPayload, TableRowsPayload, TextFilePayload


router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("")
def get_preferences():
    return load_user_preferences()


@router.put("")
def put_preferences(payload: PreferencesPayload):
    return save_user_preferences(payload.data)


@router.get("/student-profile")
def get_student_profile():
    return {"content": read_text_file("student_profile.md")}


@router.put("/student-profile")
def put_student_profile(payload: TextFilePayload):
    write_text_file("student_profile.md", payload.content)
    return {"ok": True}


@router.get("/email-template")
def get_email_template():
    return {"content": read_text_file("templates/email_template.md")}


@router.put("/email-template")
def put_email_template(payload: TextFilePayload):
    write_text_file("templates/email_template.md", payload.content)
    return {"ok": True}


@router.get("/targets")
def get_targets():
    return {"rows": load_target_schools_table()}


@router.put("/targets")
def put_targets(payload: TableRowsPayload):
    save_target_schools_table(payload.rows)
    return {"ok": True}


@router.get("/prompts")
def get_prompts():
    return {"rows": load_discovery_prompts()}


@router.put("/prompts")
def put_prompts(payload: TableRowsPayload):
    save_discovery_prompts(payload.rows)
    return {"ok": True}
