from __future__ import annotations

from fastapi import APIRouter

from autosocial.dashboard_backend import get_connection, load_metrics
from autosocial.config import AppConfig


router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("/metrics")
def get_metrics():
    conn = get_connection(AppConfig())
    return load_metrics(conn)
