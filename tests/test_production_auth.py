from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy/scripts/configure_auth.py"
SPEC = importlib.util.spec_from_file_location("configure_production_auth", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProductionAuthTests(unittest.TestCase):
    def test_old_config_receives_private_credentials_and_forced_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autosocial.env"
            path.write_text("DATABASE_PATH=/state/app.db\nSMTP_PASSWORD=keep-this\nAUTOSOCIAL_REQUIRE_AUTH=false\n", encoding="utf-8")
            MODULE.configure_auth(path)
            content = path.read_text()
            assignments = dict(line.split("=", 1) for line in content.splitlines())
            self.assertEqual(assignments["AUTOSOCIAL_REQUIRE_AUTH"], "true")
            self.assertEqual(assignments["AUTOSOCIAL_USERNAME"], "autosocial")
            self.assertGreaterEqual(len(assignments["AUTOSOCIAL_PASSWORD"]), 32)
            self.assertEqual(assignments["SMTP_PASSWORD"], "keep-this")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_existing_strong_password_and_other_settings_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autosocial.env"
            original = 'AUTOSOCIAL_USERNAME=owner\nAUTOSOCIAL_PASSWORD="private-password-with-$#-chars"\nDATABASE_PATH=data/existing.db\n'
            path.write_text(original, encoding="utf-8")
            MODULE.configure_auth(path)
            first = path.read_text()
            self.assertIn(original, first)
            MODULE.configure_auth(path)
            self.assertEqual(first, path.read_text())

    def test_blank_and_weak_passwords_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "autosocial.env"
            for password in ("", '""', "short"):
                path.write_text(f"AUTOSOCIAL_PASSWORD={password}\n", encoding="utf-8")
                MODULE.configure_auth(path)
                assigned = next(line.split("=", 1)[1] for line in path.read_text().splitlines() if line.startswith("AUTOSOCIAL_PASSWORD="))
                self.assertGreaterEqual(len(assigned), 32)


if __name__ == "__main__":
    unittest.main()
