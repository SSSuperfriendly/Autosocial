from __future__ import annotations

from autosocial.config import AppConfig
from autosocial.dashboard_backend import get_connection


def get_config() -> AppConfig:
    return AppConfig()


def get_db_connection():
    return get_connection(AppConfig())
