from __future__ import annotations

import tempfile
import threading
import unittest
import sqlite3
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autosocial.config import AppConfig
from autosocial.dashboard_backend import load_professors, send_selected_professors, sync_all_replies
from autosocial.mail import ReplyRecord, sync_replies_for_sender
from autosocial.storage import connect, init_db, record_reply, record_sent_email, upsert_draft, upsert_professor
from autosocial.tracking import (
    create_contact_event, delete_contact_event, load_contact_events, require_professor, update_follow_up,
)
from server.routes.tracking import router


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "test.db")
        self.conn = connect(self.database)
        init_db(self.conn)
        self.professor_id = upsert_professor(self.conn, {
            "name": "Example Mentor", "school": "Example University", "email": "mentor@example.edu",
            "profile_url": "https://example.edu/mentor", "source_domain": "example.edu",
        })

    def tearDown(self):
        self.conn.close()
        self.directory.cleanup()

    def professor(self):
        return dict(require_professor(self.conn, self.professor_id))

    def approved_draft(self):
        self.conn.execute("UPDATE professors SET verification_status = 'verified' WHERE id = ?", (self.professor_id,))
        self.conn.commit()
        return upsert_draft(self.conn, {
            "professor_id": self.professor_id, "subject": "PhD inquiry", "body": "An individually reviewed email.",
            "approval_status": "approved",
        })

    def mail_config(self, **extra):
        return AppConfig(
            database_path=self.database, smtp_host="mail.example.edu", smtp_username="student",
            smtp_password="test-only", sender_email="student@example.edu", **extra,
        )

    def test_migration_is_idempotent_and_preserves_plan(self):
        update_follow_up(self.conn, self.professor_id, {
            "contact_stage": "in_conversation", "next_follow_up": "2027-01-10", "next_action": "Discuss research proposal",
        })
        init_db(self.conn)
        self.assertEqual(self.professor()["next_follow_up"], "2027-01-10")
        self.assertEqual(load_professors(self.conn)[0]["next_action"], "Discuss research proposal")

    def test_patch_is_partial_and_invalid_date_is_atomic(self):
        update_follow_up(self.conn, self.professor_id, {"next_action": "Read paper", "next_follow_up": "2027-02-15"})
        update_follow_up(self.conn, self.professor_id, {"contact_stage": "shortlisted"})
        self.assertEqual(self.professor()["next_action"], "Read paper")
        with self.assertRaises(ValueError):
            update_follow_up(self.conn, self.professor_id, {"contact_stage": "replied", "next_follow_up": "2027-02-30"})
        self.assertEqual(self.professor()["contact_stage"], "shortlisted")
        for value in ("20270215", "tomorrow", "2027-2-15"):
            with self.assertRaises(ValueError):
                update_follow_up(self.conn, self.professor_id, {"next_follow_up": value})
        update_follow_up(self.conn, self.professor_id, {"next_follow_up": None, "next_action": None})
        self.assertIsNone(self.professor()["next_follow_up"])
        self.assertIsNone(self.professor()["next_action"])

    def test_manual_history_updates_dates_without_sending(self):
        create_contact_event(self.conn, self.professor_id, "email_sent", "Sent from own inbox", "2026-11-21T18:00:00+08:00")
        create_contact_event(self.conn, self.professor_id, "reply", "Invited to discuss", "2026-11-22")
        create_contact_event(self.conn, self.professor_id, "email_sent", "Older email", "2026-10-01")
        professor = self.professor()
        self.assertEqual(professor["last_contacted_at"], "2026-11-21T10:00:00Z")
        self.assertEqual(professor["last_replied_at"], "2026-11-22T00:00:00Z")
        self.assertEqual(professor["contact_stage"], "replied")
        self.assertEqual(len(load_contact_events(self.conn)), 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sent_emails").fetchone()[0], 0)

    def test_note_meeting_and_invalid_event_do_not_change_progress(self):
        for kind in ("note", "meeting"):
            create_contact_event(self.conn, self.professor_id, kind, "Research notes", "2026-11-22")
        for kind, text, timestamp in (("other", "text", None), ("note", "   ", None), ("note", "text", "yesterday")):
            with self.assertRaises(ValueError):
                create_contact_event(self.conn, self.professor_id, kind, text, timestamp)
        self.assertEqual(len(load_contact_events(self.conn)), 2)
        self.assertEqual(self.professor()["contact_stage"], "new")
        self.assertIsNone(self.professor()["last_contacted_at"])

    def test_delete_recomputes_dates_and_preserves_manual_stage(self):
        create_contact_event(self.conn, self.professor_id, "email_sent", "Older email", "2026-11-10")
        wrong = create_contact_event(self.conn, self.professor_id, "email_sent", "Mistaken date", "2027-01-01")
        reply = create_contact_event(self.conn, self.professor_id, "reply", "Wrong contact", "2026-11-20")
        update_follow_up(self.conn, self.professor_id, {"contact_stage": "in_conversation"})
        delete_contact_event(self.conn, wrong["id"])
        delete_contact_event(self.conn, reply["id"])
        self.assertEqual(self.professor()["last_contacted_at"], "2026-11-10T00:00:00Z")
        self.assertIsNone(self.professor()["last_replied_at"])
        self.assertEqual(self.professor()["contact_stage"], "in_conversation")

    def test_delete_retains_actual_mail_summary(self):
        draft_id = self.approved_draft()
        record_sent_email(self.conn, draft_id, self.professor_id, "mentor@example.edu", "Inquiry", "sent", "msg-1", None)
        event = load_contact_events(self.conn)[0]
        delete_contact_event(self.conn, event["id"])
        self.assertIsNotNone(self.professor()["last_contacted_at"])
        self.assertEqual(load_contact_events(self.conn), [])

    def test_trashed_contacts_are_hidden_and_cannot_be_modified(self):
        event = create_contact_event(self.conn, self.professor_id, "note", "Notes")
        self.conn.execute("UPDATE professors SET trashed_at = CURRENT_TIMESTAMP WHERE id = ?", (self.professor_id,))
        self.conn.commit()
        self.assertEqual(load_contact_events(self.conn), [])
        for action in (
            lambda: update_follow_up(self.conn, self.professor_id, {"next_action": "Change"}),
            lambda: create_contact_event(self.conn, self.professor_id, "reply", "Text"),
            lambda: delete_contact_event(self.conn, event["id"]),
        ):
            with self.assertRaises(LookupError):
                action()
        self.conn.execute("DELETE FROM professors WHERE id = ?", (self.professor_id,))
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM contact_events").fetchone()[0], 0)

    def test_rediscovery_does_not_erase_applicant_progress(self):
        self.conn.execute(
            "UPDATE professors SET verification_status = 'verified', shortlisted = 1, notes = 'Discussed funding' WHERE id = ?",
            (self.professor_id,),
        )
        self.conn.commit()
        update_follow_up(self.conn, self.professor_id, {"contact_stage": "in_conversation", "next_action": "Prepare proposal"})
        upsert_professor(self.conn, {
            "school": "Example University", "profile_url": "https://example.edu/mentor", "research_summary": "Updated public facts",
            "verification_status": "needs_review", "shortlisted": False, "contact_stage": "reviewing", "notes": "Missing email",
        })
        professor = self.professor()
        self.assertEqual(professor["notes"], "Discussed funding")
        self.assertEqual(professor["contact_stage"], "in_conversation")
        self.assertEqual(professor["verification_status"], "verified")
        self.assertEqual(professor["shortlisted"], 1)
        self.assertEqual(professor["research_summary"], "Updated public facts")
        self.assertEqual(professor["next_action"], "Prepare proposal")

    def test_reply_sync_is_idempotent_and_preserves_conversation(self):
        self.conn.execute("UPDATE professors SET shortlisted = 1 WHERE id = ?", (self.professor_id,))
        self.conn.commit()
        record = ReplyRecord("reply-1", "mentor@example.edu", "Re: Inquiry", "Let's discuss", "Sat, 21 Nov 2026 10:00:00 +0800", "")
        with patch("autosocial.dashboard_backend.sync_replies_for_sender", return_value=[record]):
            self.assertEqual(sync_all_replies(AppConfig(), self.conn), 1)
            update_follow_up(self.conn, self.professor_id, {"contact_stage": "in_conversation"})
            self.assertEqual(sync_all_replies(AppConfig(), self.conn), 0)
        self.assertEqual(self.professor()["contact_stage"], "in_conversation")
        self.assertEqual(len(load_contact_events(self.conn)), 1)
        self.assertEqual(self.professor()["last_replied_at"], "2026-11-21T02:00:00Z")

    def test_preview_does_not_deliver_or_write_even_with_test_override(self):
        self.approved_draft()
        before = self.professor()
        with patch("autosocial.dashboard_backend.send_via_smtp") as smtp:
            result = send_selected_professors(
                self.mail_config(force_test_recipient=True, test_recipient_email="test@example.edu"),
                self.conn, [self.professor_id], auto_prepare=True, dry_run=True,
            )
        smtp.assert_not_called()
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(self.professor(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sent_emails").fetchone()[0], 0)
        self.assertEqual(load_contact_events(self.conn), [])

    def test_implicit_approval_and_repeat_delivery_are_blocked(self):
        draft_id = upsert_draft(self.conn, {"professor_id": self.professor_id, "subject": "Inquiry", "body": "Text"})
        with patch("autosocial.dashboard_backend.send_via_smtp", return_value="msg-id") as smtp:
            result = send_selected_professors(self.mail_config(), self.conn, [self.professor_id], auto_prepare=True, dry_run=False)
            self.assertEqual(result["skipped"], 1)
            smtp.assert_not_called()
            self.approved_draft()
            result = send_selected_professors(self.mail_config(), self.conn, [self.professor_id, self.professor_id], dry_run=False)
            self.assertEqual(result["sent"], 1)
            result = send_selected_professors(self.mail_config(), self.conn, [self.professor_id], dry_run=False)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(smtp.call_count, 1)
        self.assertEqual(self.conn.execute("SELECT approval_status FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0], "sent")
        self.assertEqual(len(load_contact_events(self.conn)), 1)

    def test_ambiguous_smtp_failure_blocks_automatic_retry(self):
        self.approved_draft()
        with patch("autosocial.dashboard_backend.send_via_smtp", side_effect=TimeoutError("delivery unknown")) as smtp:
            result = send_selected_professors(self.mail_config(), self.conn, [self.professor_id], dry_run=False)
            self.assertEqual(len(result["failures"]), 1)
            result = send_selected_professors(self.mail_config(), self.conn, [self.professor_id], dry_run=False)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(smtp.call_count, 1)
        self.assertIsNone(self.professor()["last_contacted_at"])

    def test_concurrent_send_uses_a_persisted_claim(self):
        self.approved_draft()
        entered = threading.Event()
        release = threading.Event()
        results = []

        def deliver(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test timed out")
            return "msg-id"

        def first_request():
            connection = connect(self.database)
            try:
                results.append(send_selected_professors(self.mail_config(), connection, [self.professor_id], dry_run=False))
            finally:
                connection.close()

        with patch("autosocial.dashboard_backend.send_via_smtp", side_effect=deliver) as smtp:
            thread = threading.Thread(target=first_request)
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=5))
                second = send_selected_professors(self.mail_config(), self.conn, [self.professor_id], dry_run=False)
                self.assertEqual(second["skipped"], 1)
            finally:
                release.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(smtp.call_count, 1)
        self.assertEqual(results[0]["sent"], 1)


class ImapTests(unittest.TestCase):
    def test_sync_uses_from_and_reads_raw_message_without_marking_read(self):
        message = EmailMessage()
        message["From"] = "Example Mentor <mentor@example.edu>"
        message["To"] = "student@example.edu"
        message["Subject"] = "Re: PhD inquiry"
        message["Message-ID"] = "<reply@example.edu>"
        message["Date"] = "Sun, 22 Nov 2026 10:00:00 +0800"
        message.set_content("Thanks for getting in touch.")
        wrong = EmailMessage()
        wrong["From"] = "another-mentor@example.edu"
        wrong["Message-ID"] = "<other@example.edu>"
        wrong.set_content("Wrong sender")
        mailbox = MagicMock()
        mailbox.__enter__.return_value = mailbox
        mailbox.select.return_value = ("OK", [b"2"])
        mailbox.uid.side_effect = [
            ("OK", [b"1 2"]),
            ("OK", [(b"1 (BODY[] {300}", message.as_bytes()), b")"]),
            ("OK", [(b"2 (BODY[] {100}", wrong.as_bytes()), b")"]),
        ]
        with patch("autosocial.mail.imaplib.IMAP4_SSL", return_value=mailbox):
            records = sync_replies_for_sender(AppConfig(), "mentor@example.edu", 30)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].message_id, "<reply@example.edu>")
        self.assertIn("Thanks", records[0].body_preview)
        self.assertEqual(mailbox.uid.call_args_list[0].args[2], "FROM")
        self.assertEqual(mailbox.uid.call_args_list[1].args[-1], "(BODY.PEEK[])")
        mailbox.select.assert_called_once_with("INBOX", readonly=True)


class TrackingApiTests(unittest.TestCase):
    def test_http_contract_validation_and_connection_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "api.db")
            conn = connect(database)
            init_db(conn)
            professor_id = upsert_professor(conn, {"name": "Mentor", "school": "Example", "profile_url": "manual://mentor"})
            conn.close()
            connections = []

            class ObservedConnection(sqlite3.Connection):
                was_closed = False

                def close(self):
                    self.was_closed = True
                    super().close()

            def connection_factory(config):
                connection = sqlite3.connect(database, factory=ObservedConnection)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connections.append(connection)
                return connection

            app = FastAPI()
            app.include_router(router)
            with patch("server.routes.tracking.get_connection", side_effect=connection_factory), TestClient(app) as client:
                response = client.get("/api/tracking")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["events"], [])
                response = client.patch(f"/api/tracking/{professor_id}", json={
                    "contact_stage": "shortlisted", "next_follow_up": "2027-01-20", "next_action": "Read a recent paper",
                })
                self.assertEqual(response.json()["professor"]["next_follow_up"], "2027-01-20")
                self.assertEqual(client.patch(f"/api/tracking/{professor_id}", json={"next_follow_up": "2027-02-30"}).status_code, 400)
                self.assertEqual(client.patch(f"/api/tracking/{professor_id}", json={"contact_stage": None}).status_code, 400)
                self.assertEqual(client.patch(f"/api/tracking/{professor_id}", json={"unexpected": "field"}).status_code, 422)
                self.assertEqual(client.post(f"/api/tracking/{professor_id}/events", json={"kind": "reply", "content": "  "}).status_code, 400)
                response = client.post(f"/api/tracking/{professor_id}/events", json={
                    "kind": "reply", "content": "Interview invitation", "occurred_at": "2026-11-22",
                })
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["professor"]["contact_stage"], "replied")
                event_id = response.json()["event"]["id"]
                self.assertEqual(len(client.get(f"/api/tracking/{professor_id}/events").json()["events"]), 1)
                self.assertEqual(client.delete(f"/api/tracking/events/{event_id}").status_code, 200)
                self.assertEqual(client.delete(f"/api/tracking/events/{event_id}").status_code, 404)
                self.assertEqual(client.get("/api/tracking/999/events").status_code, 404)
            for connection in connections:
                self.assertTrue(connection.was_closed)


if __name__ == "__main__":
    unittest.main()
