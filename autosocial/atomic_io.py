from __future__ import annotations

import csv
import os
import tempfile
import time
from pathlib import Path
from io import StringIO
from typing import Any, Iterable


def _replace_with_retry(source: str, target: Path, *, attempts: int = 200, delay_seconds: float = 0.01) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_seconds)


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding=encoding,
            newline=newline,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        _replace_with_retry(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def atomic_write_csv_rows(path: str | Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig", newline="")
