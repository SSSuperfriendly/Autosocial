from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DiscoveryRequest(BaseModel):
    backend: str = "bigmodel-search"
    schools: list[str] = Field(default_factory=list)
    limit_per_school: int = 4
    max_crawl_pages: int = 8
    max_crawl_depth: int = 1


class PreferencesPayload(BaseModel):
    data: dict[str, Any]


class TextFilePayload(BaseModel):
    content: str


class TableRowsPayload(BaseModel):
    rows: list[dict[str, Any]]


class DraftGenerateRequest(BaseModel):
    professor_ids: list[int] = Field(default_factory=list)
    auto_approve: bool = False
    thinking_mode: str = "conservative"


class SendRequest(BaseModel):
    professor_ids: list[int] = Field(default_factory=list)
    auto_prepare: bool = False
    dry_run: bool = True


class ReplySyncRequest(BaseModel):
    days: int = 30


class ProfessorDeleteRequest(BaseModel):
    professor_ids: list[int] = Field(default_factory=list)


class BrowserSessionPayload(BaseModel):
    session_id: str = ""
    page: str = ""


class WriterDraftRequest(BaseModel):
    professor_id: int | None = None
    name: str = ""
    email: str = ""
    school: str = ""
    institute: str = ""
    title: str = ""
    profile_url: str = ""
    research_summary: str = ""
    professor_intro: str = ""
    notes: str = ""
    thinking_mode: str = "conservative"


class WriterDraftSaveRequest(BaseModel):
    draft_id: int
    professor_id: int
    subject: str = ""
    body: str = ""
