"""Single-owner HTTP Basic authentication for self-hosted instances."""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from urllib.parse import urlsplit
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class AuthSettings:
    username: str
    password: str
    required: bool
    cors_origins: tuple[str, ...]
    public_origin: str = ""

    @classmethod
    def from_env(cls) -> "AuthSettings":
        return cls(
            username=os.getenv("AUTOSOCIAL_USERNAME", "autosocial"),
            password=os.getenv("AUTOSOCIAL_PASSWORD", ""),
            public_origin=os.getenv("AUTOSOCIAL_PUBLIC_ORIGIN", "").strip().rstrip("/"),
            required=os.getenv("AUTOSOCIAL_REQUIRE_AUTH", "false").lower() in {"1", "true", "yes", "on"},
            cors_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.getenv(
                    "AUTOSOCIAL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
                ).split(",")
                if origin.strip()
            ),
        )

    def validate(self) -> None:
        if self.required and len(self.password) < 12:
            raise RuntimeError("AUTOSOCIAL_PASSWORD must contain at least 12 characters when AUTOSOCIAL_REQUIRE_AUTH=true.")
        if self.password and (not self.username or ":" in self.username):
            raise RuntimeError("AUTOSOCIAL_USERNAME must be non-empty and cannot contain a colon.")
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                    or parsed.path or parsed.query or parsed.fragment or parsed.username):
                raise RuntimeError("AUTOSOCIAL_PUBLIC_ORIGIN must be an exact http(s) origin, for example https://apply.example.com.")
        if "*" in self.cors_origins:
            raise RuntimeError("AUTOSOCIAL_CORS_ORIGINS must list explicit origins; '*' is not supported.")


class OwnerAuthMiddleware:
    def __init__(self, app: ASGIApp, settings: AuthSettings):
        self.app = app
        self.settings = settings

    def _authorized(self, authorization: str) -> bool:
        try:
            scheme, value = authorization.split(" ", 1)
            if scheme.lower() != "basic":
                return False
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeError, binascii.Error):
            return False
        username_matches = secrets.compare_digest(username.encode("utf-8"), self.settings.username.encode("utf-8"))
        password_matches = secrets.compare_digest(password.encode("utf-8"), self.settings.password.encode("utf-8"))
        return username_matches and password_matches

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if self.settings.password and not self._authorized(headers.get("authorization", "")):
            response = JSONResponse(
                {"detail": "请使用实例所有者的用户名和密码登录。"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="AutoSocial", charset="UTF-8"', "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        # Browsers retain Basic credentials. Reject cross-site writes, including
        # simple form requests that do not go through a CORS preflight.
        origin = headers.get("origin")
        if origin and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            own_origin = f"{scope.get('scheme', 'http')}://{headers.get('host', '')}"
            if origin.rstrip("/") not in {own_origin, self.settings.public_origin, *self.settings.cors_origins}:
                await JSONResponse({"detail": "不允许来自其他网站的写入请求。"}, status_code=403)(scope, receive, send)
                return

        await self.app(scope, receive, send)
