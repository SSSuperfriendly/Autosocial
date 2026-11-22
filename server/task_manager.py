from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from typing import Any

from autosocial.config import AppConfig
from autosocial.dashboard_backend import discover_and_ingest
from server.schemas import DiscoveryRequest


_LOCK = threading.Lock()
_TASKS: dict[str, dict[str, Any]] = {}


def _set_task(task_id: str, patch: dict[str, Any]) -> None:
    with _LOCK:
        _TASKS[task_id].update(patch)


def _append_event(task_id: str, event: dict[str, Any]) -> None:
    with _LOCK:
        task = _TASKS[task_id]
        task["events"].append(event)
        if "percent" in event:
            task["progress"] = event["percent"]
        task["updated_at"] = time.time()


def start_discovery_task(payload: DiscoveryRequest) -> str:
    task_id = uuid.uuid4().hex
    with _LOCK:
        _TASKS[task_id] = {
            "task_id": task_id,
            "kind": "discovery",
            "status": "queued",
            "progress": 0.0,
            "events": [],
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def worker() -> None:
        _set_task(task_id, {"status": "running"})
        try:
            result = discover_and_ingest(
                config=AppConfig(),
                backend=payload.backend,
                schools=payload.schools,
                limit_per_school=payload.limit_per_school,
                max_crawl_pages=payload.max_crawl_pages,
                max_crawl_depth=payload.max_crawl_depth,
                progress_callback=lambda event: _append_event(task_id, event),
            )
            _set_task(task_id, {"status": "completed", "progress": 1.0, "result": result, "updated_at": time.time()})
        except Exception as exc:
            _set_task(task_id, {"status": "failed", "error": str(exc), "updated_at": time.time()})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return task_id


def get_task_snapshot(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return None
        return deepcopy(task)
