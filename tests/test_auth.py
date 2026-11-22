from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import create_app
from autosocial.config import AppConfig


class OwnerAuthTests(unittest.TestCase):
    def client(self, **overrides):
        settings = {
            "AUTOSOCIAL_USERNAME": "owner",
            "AUTOSOCIAL_PASSWORD": "test-password-123456",
            "AUTOSOCIAL_REQUIRE_AUTH": "true",
            "AUTOSOCIAL_CORS_ORIGINS": "http://localhost:5173",
        }
        settings.update(overrides)
        with patch.dict(os.environ, settings):
            app = create_app()
        return TestClient(app)

    def test_all_private_surfaces_challenge_before_routes_execute(self):
        with patch("server.main.ensure_workspace"), self.client() as client:
            for endpoint in ("/", "/docs", "/openapi.json", "/api/professors", "/api/preferences/student-profile", "/assets/unknown.js"):
                with self.subTest(endpoint=endpoint):
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Basic", response.headers["www-authenticate"])
            self.assertEqual(client.get("/health").json(), {"ok": True})

    def test_correct_credentials_work_and_invalid_headers_fail_cleanly(self):
        with patch("server.main.ensure_workspace"), self.client() as client:
            self.assertEqual(client.get("/docs", auth=("owner", "test-password-123456")).status_code, 200)
            self.assertEqual(client.get("/docs", auth=("owner", "incorrect")).status_code, 401)
            for value in ("Basic !!!", "Basic bm9jb2xvbg==", "Bearer token", "Basic /w=="):
                self.assertEqual(client.get("/docs", headers={"Authorization": value}).status_code, 401)

    def test_password_requirement_fails_before_workspace_writes(self):
        for password in ("", "too-short"):
            with self.subTest(password=password), patch("server.main.ensure_workspace") as initialize:
                with self.assertRaisesRegex(RuntimeError, "at least 12"):
                    with self.client(AUTOSOCIAL_PASSWORD=password):
                        pass
                initialize.assert_not_called()

    def test_local_mode_can_run_without_password(self):
        with patch("server.main.ensure_workspace"), self.client(AUTOSOCIAL_PASSWORD="", AUTOSOCIAL_REQUIRE_AUTH="false") as client:
            self.assertEqual(client.get("/docs").status_code, 200)

    def test_cors_accepts_only_explicit_development_origin(self):
        with patch("server.main.ensure_workspace"), self.client() as client:
            allowed = client.options("/api/professors", headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            })
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers["access-control-allow-origin"], "http://localhost:5173")
            denied = client.options("/api/professors", headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "PUT",
            })
            self.assertEqual(denied.status_code, 400)
            self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_cross_site_writes_rejected_even_with_credentials(self):
        with patch("server.main.ensure_workspace"), self.client() as client:
            result = client.post("/api/outreach/send", json={"professor_ids": []}, headers={"Origin": "https://untrusted.example"}, auth=("owner", "test-password-123456"))
            self.assertEqual(result.status_code, 403)

    def test_explicit_public_https_origin_works_behind_http_proxy(self):
        with patch("server.main.ensure_workspace"), self.client(AUTOSOCIAL_PUBLIC_ORIGIN="https://apply.example.com") as client:
            # Request uses the container's HTTP scheme; the browser's origin
            # must still be accepted without trusting arbitrary proxy headers.
            accepted = client.post("/api/unknown", json={}, headers={"Origin": "https://apply.example.com"}, auth=("owner", "test-password-123456"))
            self.assertNotEqual(accepted.status_code, 403)
            denied = client.post("/api/unknown", json={}, headers={"Origin": "https://hostile.example"}, auth=("owner", "test-password-123456"))
            self.assertEqual(denied.status_code, 403)

    def test_public_origin_rejects_paths_and_credentials(self):
        for origin in ("https://example.com/path", "https://user:pass@example.com", "javascript:alert(1)"):
            with self.subTest(origin=origin), self.assertRaisesRegex(RuntimeError, "exact http"):
                with self.client(AUTOSOCIAL_PUBLIC_ORIGIN=origin):
                    pass

    def test_real_startup_initializes_workspace_and_protects_created_data(self):
        # Exercise the real lifespan and database instead of mocking bootstrap.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_cwd = Path.cwd()
            config = AppConfig(database_path=str(root / "data/autosocial.db"))
            try:
                os.chdir(root)
                with patch("autosocial.bootstrap.AppConfig", return_value=config), patch("server.routes.professors.AppConfig", return_value=config), self.client() as client:
                    self.assertTrue((root / "data/autosocial.db").is_file())
                    profile = root / "student_profile.md"
                    self.assertTrue(profile.is_file())
                    profile.write_text("私人申请资料\n", encoding="utf-8")
                    self.assertEqual(client.get("/api/preferences/student-profile").status_code, 401)
                    authorized = client.get("/api/preferences/student-profile", auth=("owner", "test-password-123456"))
                    self.assertEqual(authorized.json(), {"content": "私人申请资料\n"})
                    self.assertEqual(client.get("/api/professors", auth=("owner", "test-password-123456")).json(), {"rows": []})
                with patch("autosocial.bootstrap.AppConfig", return_value=config), self.client() as client:
                    self.assertEqual(profile.read_text(encoding="utf-8"), "私人申请资料\n")
                    self.assertEqual(client.get("/docs").status_code, 401)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
