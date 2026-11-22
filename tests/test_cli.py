from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from autosocial.cli import cmd_send_approved, cmd_sync_replies
from autosocial.config import AppConfig
from autosocial.mail import ReplyRecord
from autosocial.storage import connect, init_db, upsert_draft, upsert_professor


class CliDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "cli.db")
        self.config = AppConfig(
            database_path=self.database, smtp_host="smtp.example.edu", smtp_username="student",
            smtp_password="test-only", sender_email="student@example.edu", imap_host="imap.example.edu",
            imap_username="student", imap_password="test-only",
        )
        self.conn = connect(self.database)
        init_db(self.conn)
        self.professor_id = upsert_professor(self.conn, {
            "name": "Example Mentor", "school": "Example University", "profile_url": "https://example.edu/mentor",
            "email": "mentor@example.edu", "source_domain": "example.edu", "verification_status": "verified", "shortlisted": True,
        })
        self.draft_id = upsert_draft(self.conn, {
            "professor_id": self.professor_id, "subject": "PhD inquiry", "body": "Reviewed email", "approval_status": "approved",
        })

    def tearDown(self):
        self.conn.close()
        self.directory.cleanup()

    def run_send(self, *, dry_run, limit=50):
        output = io.StringIO()
        with patch("autosocial.cli.AppConfig", return_value=self.config), redirect_stdout(output):
            cmd_send_approved(argparse.Namespace(dry_run=dry_run, limit=limit))
        return output.getvalue()

    def test_cli_preview_has_no_network_or_progress_side_effects(self):
        before = [tuple(row) for row in self.conn.execute("SELECT * FROM professors")]
        with patch("autosocial.dashboard_backend.send_via_smtp") as smtp:
            output = self.run_send(dry_run=True)
        smtp.assert_not_called()
        self.assertIn("ready=1 sent=0", output)
        self.assertEqual([tuple(row) for row in self.conn.execute("SELECT * FROM professors")], before)
        self.assertEqual(self.conn.execute("SELECT approval_status FROM drafts").fetchone()[0], "approved")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sent_emails").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM contact_events").fetchone()[0], 0)

    def test_cli_cannot_repeat_delivery_even_if_draft_is_reapproved(self):
        with patch("autosocial.dashboard_backend.send_via_smtp", return_value="message-id") as smtp:
            self.assertIn("sent=1", self.run_send(dry_run=False))
            self.conn.execute("UPDATE drafts SET approval_status = 'approved' WHERE id = ?", (self.draft_id,))
            self.conn.commit()
            self.assertIn("skipped=1", self.run_send(dry_run=False))
            self.assertEqual(smtp.call_count, 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sent_emails WHERE status = 'sent'").fetchone()[0], 1)

    def test_cli_excludes_trash_and_rejects_nonpositive_limit(self):
        self.conn.execute("UPDATE professors SET trashed_at = CURRENT_TIMESTAMP WHERE id = ?", (self.professor_id,))
        self.conn.commit()
        with patch("autosocial.dashboard_backend.send_via_smtp") as smtp:
            self.assertIn("processed=0", self.run_send(dry_run=False))
        smtp.assert_not_called()
        for limit in (0, -1):
            with self.subTest(limit=limit), self.assertRaisesRegex(SystemExit, "greater than zero"):
                self.run_send(dry_run=True, limit=limit)

    def test_cli_sync_counts_only_new_replies_and_keeps_conversation(self):
        record = ReplyRecord("reply-1", "mentor@example.edu", "Re: inquiry", "Let's discuss", "2026-11-22T09:00:00Z", "")
        with patch("autosocial.cli.AppConfig", return_value=self.config), patch("autosocial.dashboard_backend.sync_replies_for_sender", return_value=[record]):
            with redirect_stdout(io.StringIO()) as output:
                cmd_sync_replies(argparse.Namespace(days=30))
            self.assertIn("Synced 1 new replies", output.getvalue())
            self.conn.execute("UPDATE professors SET contact_stage = 'in_conversation' WHERE id = ?", (self.professor_id,))
            self.conn.commit()
            with redirect_stdout(io.StringIO()) as output:
                cmd_sync_replies(argparse.Namespace(days=30))
            self.assertIn("Synced 0 new replies", output.getvalue())
        self.assertEqual(self.conn.execute("SELECT contact_stage FROM professors").fetchone()[0], "in_conversation")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM contact_events").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
