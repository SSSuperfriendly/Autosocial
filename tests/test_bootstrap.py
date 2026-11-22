from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from autosocial.bootstrap import ensure_workspace
from autosocial.storage import connect


class BootstrapTests(unittest.TestCase):
    def test_empty_workspace_is_ready_without_any_external_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_workspace(root, database_path="data/autosocial.db")
            for relative in ("student_profile.md", "templates/email_template.md", "data/target_schools.csv", "data/discovery_prompts.json", "data/user_preferences.json", "data/interests.txt"):
                self.assertTrue((root / relative).is_file(), relative)
            self.assertIn("邮件主题：", (root / "templates/email_template.md").read_text())
            self.assertEqual(json.loads((root / "data/user_preferences.json").read_text())["research"]["preferred_topics"], [])
            with closing(connect(str(root / "data/autosocial.db"))) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM professors").fetchone()[0], 0)

    def test_repeated_startup_preserves_user_files_and_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_workspace(root, database_path="data/autosocial.db")
            content_by_file = {
                "student_profile.md": "我的真实经历，不可覆盖\n",
                "templates/email_template.md": "邮件主题：自定义模板\n",
                "data/target_schools.csv": "school,institute,domains,entry_urls,search_hint\nMy School,,,,\n",
                "data/interests.txt": "custom direction\n",
                "data/discovery_prompts.json": "[]",
                "data/user_preferences.json": '{"research":{"primary_focus":"history"}}',
            }
            for relative, content in content_by_file.items():
                (root / relative).write_text(content, encoding="utf-8")
            with closing(connect(str(root / "data/autosocial.db"))) as conn:
                conn.execute("INSERT INTO professors (school, name, profile_url) VALUES ('School', 'Professor', 'https://example.edu/p')")
                conn.commit()
            ensure_workspace(root, database_path="data/autosocial.db")
            for relative, content in content_by_file.items():
                self.assertEqual((root / relative).read_text(encoding="utf-8"), content, relative)
            with closing(connect(str(root / "data/autosocial.db"))) as conn:
                self.assertEqual(conn.execute("SELECT name FROM professors").fetchone()[0], "Professor")


if __name__ == "__main__":
    unittest.main()
