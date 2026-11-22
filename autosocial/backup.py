"""Create a portable backup, including committed SQLite WAL changes."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig


def create_backup(output_dir: Path, database_path: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = output_dir / f"autosocial-{stamp}.tar.gz"
    pending: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="autosocial-backup-") as temporary:
            snapshot = Path(temporary) / "autosocial.db"
            if not database_path.is_file():
                raise FileNotFoundError(f"Database does not exist: {database_path}")
            source = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            # NamedTemporaryFile creates mode 0600 before any private content is
            # written, independently of the process umask.
            with tempfile.NamedTemporaryFile("w+b", dir=output_dir, prefix=".autosocial-", suffix=".tmp", delete=False) as handle:
                pending = Path(handle.name)
                with tarfile.open(fileobj=handle, mode="w:gz") as archive:
                    archive.add(snapshot, arcname="data/autosocial.db")
                    for item in (
                        "data/user_preferences.json", "data/discovery_prompts.json",
                        "data/target_schools.csv", "data/interests.txt",
                        "student_profile.md", "templates", "data/attachments", "attachments",
                    ):
                        candidate = Path(item)
                        if candidate.exists():
                            # Legacy systemd deployments link these workspace
                            # paths to /var/lib/autosocial. Store their contents
                            # under portable names, not host-specific symlinks.
                            archive.add(candidate.resolve(), arcname=item)
                    configured_attachments = Path(AppConfig().attachment_dir or "data/attachments")
                    if configured_attachments.is_dir() and configured_attachments.resolve() not in {
                        Path("data/attachments").resolve(), Path("attachments").resolve()
                    }:
                        archive.add(configured_attachments.resolve(), arcname="data/attachments")
                handle.flush()
                # The archive should be durable before reporting its final name.
                os.fsync(handle.fileno())
        pending.replace(destination)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("backups"))
    args = parser.parse_args()
    print(create_backup(args.output, Path(AppConfig().database_path)))


if __name__ == "__main__":
    main()
