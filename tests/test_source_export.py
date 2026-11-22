import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.check_privacy import audit, scan_text
from scripts.export_source import export_source


class SourceExportPrivacyTests(unittest.TestCase):
    def test_personal_filename_is_rejected_and_redacted(self):
        identity = "fixture" + "-owner"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "autosocial").mkdir()
            (root / "autosocial" / f"{identity}.py").write_text("")
            with patch("scripts.check_privacy.identity_markers", return_value={identity}):
                _, findings = audit(root)
            self.assertEqual(findings[0].category, "sensitive-source-filename")
            self.assertNotIn(identity, repr(findings))

    def test_nested_environment_and_credentials_never_enter_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "frontend").mkdir()
            (root / "docs").mkdir()
            for relative in ("frontend/.env.json", "docs/.env.example", "docs/credentials.json"):
                (root / relative).write_text("local-only")
            (root / "README.md").write_text("Public project")
            destination = root / "release.zip"
            self.assertEqual(export_source(root, destination), 1)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.namelist(), ["AutoSocial/README.md"])

    def test_json_credential_values_are_detected_without_echoing(self):
        value = "fixture" + "-credential-value"
        findings = scan_text("docs/example.json", '{"api_key": "' + value + '"}')
        self.assertEqual(findings[0].category, "credential-literal")
        self.assertNotIn(value, repr(findings))

    def test_identity_checks_do_not_echo_the_matched_value(self):
        identity = "fixture" + "-owner"
        findings = scan_text("README.md", f"Repository owned by {identity}", {identity})
        self.assertEqual(findings[0].category, "original-git-identity")
        self.assertNotIn(identity, repr(findings))

    def test_export_excludes_git_runtime_and_compiled_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (".git", "data", ".venv", "frontend/dist", "frontend/node_modules", "autosocial/__pycache__", "scripts", "autosocial"):
                (root / name).mkdir(parents=True, exist_ok=True)
            for name in (".git/config", ".env", "data/private.json", ".venv/local.py", "frontend/dist/index.html", "frontend/node_modules/module.js", "autosocial/__pycache__/local.pyc", "student_profile.md"):
                (root / name).write_text("local-only")
            (root / "README.md").write_text("Public project description")
            (root / "autosocial/__init__.py").write_text("")
            (root / "scripts/tool.sh").write_text("#!/bin/sh\n")
            destination = root / "releases/source.zip"
            self.assertEqual(export_source(root, destination), 3)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {"AutoSocial/README.md", "AutoSocial/autosocial/__init__.py", "AutoSocial/scripts/tool.sh"})
                for entry in archive.infolist():
                    self.assertEqual(entry.date_time, (2020, 1, 1, 0, 0, 0))
                    self.assertEqual(entry.extra, b"")
                    self.assertEqual(entry.comment, b"")

    def test_sensitive_example_configuration_blocks_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env.example").write_text("LLM_API_KEY=" + "fixture-credential\n")
            _, findings = audit(root)
            self.assertEqual(findings[0].category, "nonempty-sensitive-example-setting")
            destination = root / "source.zip"
            with self.assertRaisesRegex(ValueError, "no archive was written"):
                export_source(root, destination)
            self.assertFalse(destination.exists())
