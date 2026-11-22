import os
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autosocial.backup import create_backup


class BackupTests(unittest.TestCase):
    def test_private_archive_permissions_apply_before_writing(self):
        previous = Path.cwd()
        real_tar_open = tarfile.open
        observed = []
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                with sqlite3.connect("database.db") as connection:
                    connection.execute("CREATE TABLE example(value TEXT)")

                def checked_open(*args, **kwargs):
                    private_file = Path(kwargs["fileobj"].name)
                    observed.append(private_file.stat().st_mode & 0o777)
                    return real_tar_open(*args, **kwargs)

                with patch("autosocial.backup.tarfile.open", side_effect=checked_open):
                    result = create_backup(Path("backups"), Path("database.db"))
                self.assertEqual(observed, [0o600])
                self.assertEqual(result.stat().st_mode & 0o777, 0o600)
                self.assertEqual(list(Path("backups").glob("*.tmp")), [])
            finally:
                os.chdir(previous)

    def test_legacy_symlinked_profile_and_templates_restore_as_portable_content(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            state = base / "legacy-state"
            workspace.mkdir()
            (state / "templates").mkdir(parents=True)
            (state / "data").mkdir()
            (state / "student_profile.md").write_text("real applicant profile", encoding="utf-8")
            (state / "templates/email_template.md").write_text("custom email template", encoding="utf-8")
            (workspace / "student_profile.md").symlink_to(state / "student_profile.md")
            (workspace / "templates").symlink_to(state / "templates", target_is_directory=True)
            (workspace / "data").symlink_to(state / "data", target_is_directory=True)
            os.chdir(workspace)
            try:
                with sqlite3.connect("data/autosocial.db") as connection:
                    connection.execute("CREATE TABLE example(value TEXT)")
                result = create_backup(Path("backups"), Path("data/autosocial.db"))
                with tarfile.open(result) as archive:
                    self.assertTrue(archive.getmember("student_profile.md").isfile())
                    self.assertTrue(archive.getmember("templates").isdir())
                    self.assertEqual(archive.extractfile("student_profile.md").read(), b"real applicant profile")
                    self.assertEqual(archive.extractfile("templates/email_template.md").read(), b"custom email template")
                    restored = base / "restored"
                    archive.extractall(restored, filter="data")
                self.assertFalse((restored / "student_profile.md").is_symlink())
                self.assertFalse((restored / "templates").is_symlink())
                self.assertEqual((restored / "templates/email_template.md").read_text(), "custom email template")
            finally:
                os.chdir(previous)

    def test_includes_wal_data_profile_and_templates_without_secrets(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                Path("data").mkdir()
                Path("templates").mkdir()
                Path("student_profile.md").write_text("profile")
                Path("templates/email_template.md").write_text("template")
                Path(".env").write_text("SECRET=do-not-back-up")
                connection = sqlite3.connect("data/autosocial.db")
                try:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.execute("CREATE TABLE example(value TEXT)")
                    connection.execute("INSERT INTO example VALUES ('committed-in-wal')")
                    connection.commit()
                    backup = create_backup(Path("backups"), Path("data/autosocial.db"))
                    with tarfile.open(backup) as archive:
                        names = archive.getnames()
                        self.assertIn("student_profile.md", names)
                        self.assertIn("templates/email_template.md", names)
                        self.assertNotIn(".env", names)
                        restored = Path(tmp) / "restored.db"
                        with archive.extractfile("data/autosocial.db") as handle:
                            restored.write_bytes(handle.read())
                    with sqlite3.connect(restored) as restored_connection:
                        self.assertEqual(restored_connection.execute("SELECT value FROM example").fetchone()[0], "committed-in-wal")
                    self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                finally:
                    connection.close()
            finally:
                os.chdir(previous)
