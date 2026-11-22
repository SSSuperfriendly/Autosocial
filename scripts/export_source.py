"""Export audited current source without Git identities, caches or application data."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path

try:
    from .check_privacy import ROOT, audit
except ImportError:
    from check_privacy import ROOT, audit


def export_source(root: Path, destination: Path) -> int:
    root = root.resolve()
    files, findings = audit(root)
    if findings:
        raise ValueError("Privacy checks found unresolved items. Run scripts/check_privacy.py; no archive was written.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Fixed timestamps and permission bits omit workstation timestamps, owner
    # IDs, absolute paths, Git authors, reflogs and configured remote URLs.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for candidate in files:
            relative = candidate.relative_to(root).as_posix()
            item = zipfile.ZipInfo(f"AutoSocial/{relative}", date_time=(2020, 1, 1, 0, 0, 0))
            item.create_system = 3
            mode = 0o755 if candidate.suffix == ".sh" else 0o644
            item.external_attr = (stat.S_IFREG | mode) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, candidate.read_bytes())
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "releases" / "AutoSocial-source.zip")
    args = parser.parse_args()
    count = export_source(ROOT, args.output)
    print(f"Exported {count} audited source files to {args.output.name}; Git metadata and runtime data excluded.")


if __name__ == "__main__":
    main()
