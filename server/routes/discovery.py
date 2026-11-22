from __future__ import annotations

from fastapi import APIRouter, HTTPException

from autosocial.config import AppConfig
from autosocial.dashboard_backend import discover_and_ingest
from server.schemas import DiscoveryRequest
from server.task_manager import get_task_snapshot, start_discovery_task


router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/run")
def run_discovery(payload: DiscoveryRequest):
    events: list[dict] = []

    def on_progress(event: dict) -> None:
        events.append(event)

    result = discover_and_ingest(
        config=AppConfig(),
        backend=payload.backend,
        schools=payload.schools,
        limit_per_school=payload.limit_per_school,
        max_crawl_pages=payload.max_crawl_pages,
        max_crawl_depth=payload.max_crawl_depth,
        progress_callback=on_progress,
    )
    result["progress_events"] = events
    return result


@router.post("/tasks")
def create_discovery_task(payload: DiscoveryRequest):
    return {"task_id": start_discovery_task(payload)}


@router.get("/tasks/{task_id}")
def get_discovery_task(task_id: str):
    snapshot = get_task_snapshot(task_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="task not found")
    return snapshot
