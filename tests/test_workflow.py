"""Exercise the keyless applicant workflow through the actual HTTP routes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import create_app


class ApplicantWorkflowTests(unittest.TestCase):
    def test_manual_contact_plan_history_draft_and_restore(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                with patch.dict(os.environ, {"AUTOSOCIAL_REQUIRE_AUTH": "false", "AUTOSOCIAL_PASSWORD": ""}):
                    application = create_app()
                with TestClient(application) as client:
                    mentor = {"name": "测试导师", "school": "示例大学", "research_summary": "科学史", "email": "mentor@university.example", "notes": "人工核实中的导师"}
                    saved = client.post("/api/writer/professor", json=mentor)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    professor_id = saved.json()["professor"]["id"]
                    plan = {"contact_stage": "in_conversation", "next_follow_up": "2026-12-01", "next_action": "补充研究计划"}
                    self.assertEqual(client.patch(f"/api/tracking/{professor_id}", json=plan).status_code, 200)
                    event = client.post(f"/api/tracking/{professor_id}/events", json={"kind": "reply", "content": "老师希望先看研究计划", "occurred_at": "2026-11-22"})
                    self.assertEqual(event.status_code, 201, event.text)
                    draft = client.post("/api/writer/draft", json={**mentor, "professor_id": professor_id})
                    self.assertEqual(draft.status_code, 200, draft.text)
                    self.assertIn("博士申请咨询", draft.json()["draft"]["subject"])
                    self.assertEqual(len(client.get("/api/drafts").json()["rows"]), 1)
                    row = client.get("/api/tracking").json()["professors"][0]
                    self.assertEqual(row["contact_stage"], "in_conversation")
                    self.assertEqual(row["next_follow_up"], "2026-12-01")
                    self.assertEqual(row["next_action"], "补充研究计划")
                    client.post("/api/professors/trash", json={"professor_ids": [professor_id]})
                    self.assertEqual(client.get("/api/tracking").json(), {"professors": [], "events": []})
                    client.post("/api/professors/restore", json={"professor_ids": [professor_id]})
                    restored = client.get("/api/tracking").json()
                    self.assertEqual(len(restored["events"]), 1)
                    self.assertEqual(restored["professors"][0]["next_action"], "补充研究计划")
            finally:
                os.chdir(original)
