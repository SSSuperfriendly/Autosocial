"""Provision private server credentials without putting them in shell output."""

from __future__ import annotations

import os
import re
import secrets
import shlex
import sys
import tempfile
from pathlib import Path


def _unquote(value: str) -> str:
    try:
        parts = shlex.split(value, comments=False, posix=True)
        return " ".join(parts)
    except ValueError:
        return ""


def configure_auth(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    assignments: dict[str, str] = {}
    for line in original.splitlines():
        match = re.match(r"^\s*(AUTOSOCIAL_(?:USERNAME|PASSWORD|REQUIRE_AUTH))\s*=(.*)$", line)
        if match:
            assignments[match[1]] = match[2]

    username = _unquote(assignments.get("AUTOSOCIAL_USERNAME", ""))
    password = _unquote(assignments.get("AUTOSOCIAL_PASSWORD", ""))
    updates = {"AUTOSOCIAL_REQUIRE_AUTH": "true"}
    if not username or ":" in username:
        updates["AUTOSOCIAL_USERNAME"] = "autosocial"
    if len(password) < 12:
        updates["AUTOSOCIAL_PASSWORD"] = secrets.token_urlsafe(32)

    output = []
    for line in original.splitlines():
        match = re.match(r"^\s*([A-Z_]+)\s*=", line)
        if not match or match[1] not in updates:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in updates.items())

    # Restrictive mode is set before the replacement, including on a fresh
    # installation where the example file may originally have been world-readable.
    existing = path.stat()
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".autosocial-auth-", delete=False) as handle:
            temporary_name = handle.name
            os.chmod(temporary_name, 0o640)
            if hasattr(os, "chown"):
                os.chown(temporary_name, existing.st_uid, existing.st_gid)
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: configure_auth.py /etc/autosocial/autosocial.env")
    configure_auth(Path(sys.argv[1]))
