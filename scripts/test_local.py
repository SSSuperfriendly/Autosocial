from __future__ import annotations

import csv
import json
import multiprocessing as mp
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autosocial.atomic_io import atomic_write_csv_rows, atomic_write_text


def _write_json_worker(path: str, worker_id: int, loops: int) -> None:
    target = Path(path)
    for index in range(loops):
        payload = {
            "worker": worker_id,
            "index": index,
            "marker": "autosocial-atomic-json",
            "items": [{"n": n, "text": f"{worker_id}-{index}-{n}"} for n in range(200)],
        }
        atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text_worker(path: str, worker_id: int, loops: int) -> None:
    target = Path(path)
    for index in range(loops):
        lines = [f"autosocial-atomic-text worker={worker_id} index={index}"]
        lines.extend(f"line-{n}: {worker_id}-{index}-{n}" for n in range(300))
        atomic_write_text(target, "\n".join(lines) + "\n", encoding="utf-8")


def _write_csv_worker(path: str, worker_id: int, loops: int) -> None:
    for index in range(loops):
        rows = [
            {
                "school": f"School {worker_id}",
                "institute": f"Institute {index}",
                "domains": "example.edu",
                "entry_urls": f"https://example.edu/{worker_id}/{index}/{n}",
                "search_hint": f"hint {n}",
            }
            for n in range(120)
        ]
        atomic_write_csv_rows(path, ["school", "institute", "domains", "entry_urls", "search_hint"], rows)


def _assert_json_ok(path: Path) -> None:
    raw = _read_text_with_retry(path, encoding="utf-8")
    if not raw:
        raise AssertionError(f"{path.name} was truncated to empty")
    payload = json.loads(raw)
    if payload.get("marker") != "autosocial-atomic-json" or len(payload.get("items") or []) != 200:
        raise AssertionError(f"{path.name} content is incomplete")


def _assert_text_ok(path: Path) -> None:
    raw = _read_text_with_retry(path, encoding="utf-8")
    if not raw:
        raise AssertionError(f"{path.name} was truncated to empty")
    lines = raw.splitlines()
    if not lines or not lines[0].startswith("autosocial-atomic-text") or len(lines) != 301:
        raise AssertionError(f"{path.name} content is incomplete")


def _assert_csv_ok(path: Path) -> None:
    raw = _read_text_with_retry(path, encoding="utf-8-sig")
    if not raw:
        raise AssertionError(f"{path.name} was truncated to empty")
    rows = list(csv.DictReader(raw.splitlines()))
    if len(rows) != 120:
        raise AssertionError(f"{path.name} row count is incomplete: {len(rows)}")
    required = {"school", "institute", "domains", "entry_urls", "search_hint"}
    if set(rows[0]) != required:
        raise AssertionError(f"{path.name} header is incomplete")


def _read_text_with_retry(path: Path, *, encoding: str, attempts: int = 100) -> str:
    for attempt in range(attempts):
        try:
            return path.read_text(encoding=encoding)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.01)
    raise AssertionError(f"unable to read {path}")


def _watch_files(paths: dict[str, Path], stop: mp.Event, errors: mp.Queue) -> None:
    checks = {
        "json": _assert_json_ok,
        "text": _assert_text_ok,
        "csv": _assert_csv_ok,
    }
    while not stop.is_set():
        for name, path in paths.items():
            if not path.exists():
                continue
            try:
                checks[name](path)
            except Exception as exc:
                errors.put(f"{name}: {exc}")
                stop.set()
                return
        time.sleep(0.005)


def main() -> int:
    workers = 6
    loops = 80
    with tempfile.TemporaryDirectory(prefix="autosocial-local-test-") as tmp:
        base = Path(tmp)
        paths = {
            "json": base / "user_preferences.json",
            "text": base / "interests.txt",
            "csv": base / "target_schools.csv",
        }

        atomic_write_text(paths["json"], json.dumps({"marker": "autosocial-atomic-json", "items": [{"n": n} for n in range(200)]}))
        atomic_write_text(paths["text"], "autosocial-atomic-text worker=seed index=0\n" + "\n".join(f"line-{n}" for n in range(300)) + "\n")
        atomic_write_csv_rows(
            str(paths["csv"]),
            ["school", "institute", "domains", "entry_urls", "search_hint"],
            [
                {
                    "school": "Seed",
                    "institute": "Seed",
                    "domains": "example.edu",
                    "entry_urls": f"https://example.edu/{n}",
                    "search_hint": "seed",
                }
                for n in range(120)
            ],
        )

        stop = mp.Event()
        errors: mp.Queue = mp.Queue()
        processes: list[mp.Process] = [
            mp.Process(target=_watch_files, args=(paths, stop, errors)),
        ]
        for worker_id in range(workers):
            processes.extend(
                [
                    mp.Process(target=_write_json_worker, args=(str(paths["json"]), worker_id, loops)),
                    mp.Process(target=_write_text_worker, args=(str(paths["text"]), worker_id, loops)),
                    mp.Process(target=_write_csv_worker, args=(str(paths["csv"]), worker_id, loops)),
                ]
            )

        for process in processes:
            process.start()
        for process in processes[1:]:
            process.join()
        stop.set()
        processes[0].join()

        failures = [process.exitcode for process in processes if process.exitcode not in (0, None)]
        if failures:
            print(f"FAILED: worker process exited with {failures}", file=sys.stderr)
            return 1
        if not errors.empty():
            print(f"FAILED: {errors.get()}", file=sys.stderr)
            return 1

        _assert_json_ok(paths["json"])
        _assert_text_ok(paths["text"])
        _assert_csv_ok(paths["csv"])
        print("OK: concurrent JSON/TXT/CSV writes stayed complete; no truncation detected.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
