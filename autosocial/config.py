from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(slots=True)
class AppConfig:
    database_path: str = os.getenv("DATABASE_PATH", "data/autosocial.db")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    openai_search_api_key: str = os.getenv("OPENAI_SEARCH_API_KEY", "")
    openai_search_base_url: str = os.getenv("OPENAI_SEARCH_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    openai_search_model: str = os.getenv("OPENAI_SEARCH_MODEL", "gpt-4o-mini-search-preview")
    bigmodel_search_api_key: str = os.getenv("BIGMODEL_SEARCH_API_KEY", "")
    bigmodel_search_base_url: str = os.getenv("BIGMODEL_SEARCH_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    bigmodel_search_model: str = os.getenv("BIGMODEL_SEARCH_MODEL", "glm-4-air")
    bigmodel_search_engine: str = os.getenv("BIGMODEL_SEARCH_ENGINE", "search_pro")
    zju_person_app_key: str = os.getenv("ZJU_PERSON_APP_KEY", "").strip()
    zju_person_secret: str = os.getenv("ZJU_PERSON_SECRET", "").strip()
    zju_person_college_ids: str = os.getenv("ZJU_PERSON_COLLEGE_IDS", "").strip()
    sender_name: str = os.getenv("SENDER_NAME", "")
    sender_email: str = os.getenv("SENDER_EMAIL", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "465"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_ssl: bool = _env_bool("SMTP_USE_SSL", True)
    force_test_recipient: bool = _env_bool("FORCE_TEST_RECIPIENT", False)
    test_recipient_dry_run_only: bool = _env_bool("TEST_RECIPIENT_DRY_RUN_ONLY", False)
    test_recipient_email: str = os.getenv("TEST_RECIPIENT_EMAIL", "").strip()
    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_username: str = os.getenv("IMAP_USERNAME", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_folder: str = os.getenv("IMAP_FOLDER", "INBOX")
    attachment_dir: str = os.getenv("ATTACHMENT_DIR", "")
    http_timeout_seconds: int = int(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
    user_agent: str = os.getenv("USER_AGENT", "AutoSocial/0.1")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def openai_search_enabled(self) -> bool:
        return bool(self.openai_search_api_key and self.openai_search_base_url and self.openai_search_model)

    @property
    def bigmodel_search_enabled(self) -> bool:
        return bool(self.bigmodel_search_api_key and self.bigmodel_search_base_url and self.bigmodel_search_model)

    @property
    def zju_person_enabled(self) -> bool:
        return bool(self.zju_person_app_key and self.zju_person_secret)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password and self.sender_email)

    @property
    def imap_enabled(self) -> bool:
        return bool(self.imap_host and self.imap_username and self.imap_password)

    @property
    def test_recipient_enabled(self) -> bool:
        return bool(self.force_test_recipient and self.test_recipient_email)

    def should_use_test_recipient(self, dry_run: bool) -> bool:
        if not self.test_recipient_enabled:
            return False
        if self.test_recipient_dry_run_only:
            return dry_run
        return True

    @property
    def test_recipient_mode(self) -> str:
        if not self.test_recipient_enabled:
            return "off"
        if self.test_recipient_dry_run_only:
            return "dry_run_only"
        return "all"
