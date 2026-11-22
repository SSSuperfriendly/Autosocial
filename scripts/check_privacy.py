"""Check publishable source for identity and credential leakage without echoing values."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".dockerignore", ".env.example", ".gitignore", "README.md", "README.en.md",
    "DEPLOY.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE", "Dockerfile",
    "compose.yaml", "requirements.txt", "requirements-dev.txt",
    "student_profile.example.md", "deploy_to_tencent.ps1", "update_server.sh",
}
SOURCE_DIRS = {"autosocial", "server", "frontend", "deploy", "scripts", "tests", "docs", "assets", ".github"}
EXCLUDED_PARTS = {
    ".git", ".venv", "node_modules", "__pycache__", "dist", "build", "runtime",
    "data", "attachments", "附件", "backups", "releases", "logs", ".aws", ".ssh", ".agents", ".codex",
}
SOURCE_SUFFIXES = {".py", ".ps1", ".sh", ".md", ".txt", ".json", ".yaml", ".yml", ".ts", ".tsx", ".css", ".html", ".svg", ".png", ".ico", ".template", ".service", ".timer", ".example"}
GENERATED_NAMES = {"vite.config.js", "vite.config.d.ts"}
PRIVATE_NAMES = {"credentials.json", "secrets.json", "service-account.json", "id_rsa", "id_ed25519"}
ENV_EXAMPLES = {".env.example", "deploy/env.production.example"}
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
HOME_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])([A-Za-z0-9_.\-\u4e00-\u9fff]+)")
KEY_LITERAL = re.compile(r"(?im)^\s*[A-Z_]*(?:API_KEY|APP_KEY|PASSWORD|SECRET|TOKEN)[A-Z_]*\s*=\s*[\"']([^\"'\n]{16,})[\"']")
JSON_CREDENTIAL = re.compile(r'(?i)"[a-z_]*(?:api_key|app_key|password|secret|token)[a-z_]*"\s*:\s*"[^"\n]{16,}"')
TOKEN = re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{24,})\b")
DOCUMENTATION_NETS = tuple(ipaddress.ip_network(value) for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str


def git_output(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def identity_markers(root: Path) -> set[str]:
    """Keep original Git identities in memory only; never copy them into reports."""
    markers: set[str] = set()
    metadata = git_output(root, "log", "--all", "--format=%an%x00%ae%x00%cn%x00%ce")
    for value in re.split(r"[\x00\n]", metadata):
        value = value.strip()
        if value and ("@" in value or len(value) >= 4 or re.search(r"[\u4e00-\u9fff]", value)):
            if value.casefold() not in {"autosocial contributors", "github", "github-actions[bot]"}:
                markers.add(value)
    remotes = git_output(root, "config", "--get-regexp", r"remote\..*\.url")
    for owner in re.findall(r"github\.com[:/]([^/\s]+)/", remotes):
        markers.add(owner)
    return markers


def source_files(root: Path) -> list[Path]:
    """A source allowlist excludes runtime files even if they were force-added."""
    candidates = []
    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories if name not in EXCLUDED_PARTS
                             and (Path(directory) != root or name in SOURCE_DIRS)]
        for filename in filenames:
            candidate = Path(directory) / filename
            relative = candidate.relative_to(root)
            if filename in GENERATED_NAMES:
                continue
            if (filename.lower().startswith(".env") and relative.as_posix() not in ENV_EXAMPLES) or filename.lower() in PRIVATE_NAMES:
                continue
            if relative.parts[0] not in SOURCE_DIRS and relative.as_posix() not in ROOT_FILES:
                continue
            if relative.as_posix() in ROOT_FILES or candidate.suffix in SOURCE_SUFFIXES:
                candidates.append(candidate)
    return sorted(candidates)


def scan_text(relative: str, text: str, markers: set[str] | None = None) -> list[Finding]:
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        categories = set()
        if any(marker.casefold() in line.casefold() for marker in markers or set()):
            categories.add("original-git-identity")
        if re.search(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", line):
            categories.add("private-key-material")
        if TOKEN.search(line) or KEY_LITERAL.search(line) or (relative.endswith(".json") and JSON_CREDENTIAL.search(line)):
            categories.add("credential-literal")
        for match in EMAIL.finditer(line):
            domain = match.group().rsplit("@", 1)[1].lower()
            if domain not in {"example.com", "example.org", "example.net", "example.edu"} and not domain.endswith(".example"):
                categories.add("non-example-email")
        for match in IPV4.finditer(line):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if not (address.is_loopback or address.is_unspecified or any(address in network for network in DOCUMENTATION_NETS)):
                categories.add("non-example-ip-address")
        for match in HOME_PATH.finditer(line):
            if match.group(1).casefold() not in {"example", "user", "username"}:
                categories.add("personal-home-path")
        if re.search(r"https?://(?:www\.)?(?:kdocs\.cn/l/|docs\.google\.com/(?:document|spreadsheets)/d/|notion\.so/[^\s]+[a-f0-9]{32})", line):
            categories.add("personal-document-link")
        findings.extend(Finding(relative, line_number, category) for category in sorted(categories))
    return findings


def safe_location(relative: str, markers: set[str]) -> str:
    if scan_text("", relative, markers):
        code = hashlib.sha256(relative.encode()).hexdigest()[:12]
        return f"[redacted-source-{code}]"
    return relative


def audit(root: Path) -> tuple[list[Path], list[Finding]]:
    root = root.resolve()
    files = source_files(root)
    findings = []
    markers = identity_markers(root)
    for candidate in files:
        relative = candidate.relative_to(root).as_posix()
        location = safe_location(relative, markers)
        if location != relative:
            findings.append(Finding(location, 0, "sensitive-source-filename"))
        if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents if root in parent.parents):
            findings.append(Finding(location, 0, "source-symlink"))
            continue
        payload = candidate.read_bytes()
        if candidate.suffix not in {".png", ".ico"}:
            text = payload.decode("utf-8-sig")
            findings.extend(scan_text(location, text, markers))
            if relative in ENV_EXAMPLES:
                for line_number, line in enumerate(text.splitlines(), 1):
                    if re.match(r"\s*(?:[A-Z_]*(?:API_KEY|APP_KEY|PASSWORD|SECRET|TOKEN)|SENDER_EMAIL|TEST_RECIPIENT_EMAIL)\s*=\s*[^\s#]", line):
                        findings.append(Finding(location, line_number, "nonempty-sensitive-example-setting"))
    # A force-added runtime/credential file is a leak even though the exporter
    # would exclude it. Report its path, never its contents.
    allowed_paths = {candidate.relative_to(root).as_posix() for candidate in files}
    for relative in git_output(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\x00"):
        if not relative or not (root / relative).exists():
            continue
        candidate = Path(relative)
        location = safe_location(relative, markers)
        if any(part in EXCLUDED_PARTS for part in candidate.parts) or candidate.suffix in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".csv", ".pyc"} or candidate.name == ".env" or candidate.name == "student_profile.md":
            findings.append(Finding(location, 0, "tracked-private-or-generated-file"))
        elif relative not in allowed_paths:
            findings.append(Finding(location, 0, "unexpected-file-outside-source-allowlist"))
    return files, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    files, findings = audit(args.root.resolve())
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.category} (value redacted)")
    print(f"Checked {len(files)} publishable files; {len(findings)} findings. Git history and binary image content require separate review.")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
