from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from bs4 import BeautifulSoup

from autosocial import services
from autosocial.config import AppConfig
from autosocial.discovery import discover_urls_via_directory_crawl, fetch_zju_person_directory_rows, _query_templates
from autosocial.preferences import DEFAULT_PREFERENCES, research_profile_summary
from autosocial.scoring import fit
from autosocial.services import _build_thinking_anchor, render_template


class PrivacyDefaultTests(unittest.TestCase):
    def test_new_workspace_has_no_preselected_research_preferences(self):
        research = DEFAULT_PREFERENCES["research"]
        self.assertEqual(research["primary_focus"], "")
        for key in ("preferred_topics", "acceptable_topics", "excluded_topics"):
            self.assertEqual(research[key], [])
        self.assertEqual(research["free_text_notes"], "")
        self.assertIn("未设置", research_profile_summary({"research": {}}))

    def test_fit_uses_no_implicit_research_criteria(self):
        with patch.object(fit, "_contains_any", wraps=fit._contains_any) as match:
            fit.score_professor_fit({"name": "示例导师", "research_summary": "天文学"}, {"research": {}})
        self.assertTrue(all(call.args[1] == [] for call in match.call_args_list))
        queries = _query_templates("示例大学", "", "", [], "university.example")
        self.assertTrue(all("site:university.example" in query for query in queries))
        self.assertTrue(all("( OR )" not in query for query in queries))

    def test_blank_applicant_background_does_not_create_personal_interests(self):
        professor = {"name": "示例导师", "research_summary": "科学史"}
        self.assertEqual(_build_thinking_anchor({}, "科学史", "科学史"), "")
        draft = render_template("Subject: 咨询\n\n{{professor_thinking_paragraph}}", professor, "", "")
        self.assertIn("科学史", draft["body"])
        self.assertNotIn("我", draft["body"])
        self.assertNotIn("兴趣", draft["body"])

    def test_explicit_applicant_ideas_are_preserved_without_topic_inference(self):
        idea = "希望比较两种史料的记载差异"
        draft = render_template(
            "Subject: 咨询\n\n{{professor_thinking_paragraph}}",
            {"name": "示例导师", "research_summary": "科学史"},
            f"# 思考素材\n- {idea}\n", "",
        )
        self.assertIn(idea, draft["body"])
        self.assertIn("科学史", draft["body"])

    def test_optional_directory_credentials_are_not_embedded_or_used_by_default(self):
        self.assertFalse(hasattr(services, "ZJU_PERSON_SECRET_HEX"))
        self.assertFalse(hasattr(services, "ZJU_PERSON_APP_KEY_HEX"))
        self.assertFalse(hasattr(services, "ZJU_PERSON_PRIORITY_COLLEGE_IDS"))
        config = AppConfig(zju_person_app_key="", zju_person_secret="", zju_person_college_ids="")
        with patch("autosocial.discovery.requests.get") as request:
            self.assertEqual(fetch_zju_person_directory_rows(config, "示例大学", "", 4), [])
        request.assert_not_called()

    def test_missing_optional_credentials_fall_back_to_html_crawling(self):
        config = AppConfig(zju_person_app_key="", zju_person_secret="", zju_person_college_ids="")
        domain = urlparse(services.ZJU_PERSON_SERVER_URL).netloc
        profile_url = f"https://{domain}/personage/example"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "targets.csv"
            interests = Path(directory) / "interests.txt"
            target.write_text(f"school,institute,domains,entry_urls,search_hint\n示例大学,,{domain},https://{domain}/,\n", encoding="utf-8")
            interests.write_text("", encoding="utf-8")
            with patch("autosocial.discovery.fetch_zju_person_directory_rows") as specialized, patch(
                "autosocial.discovery.fetch_html",
                return_value=(profile_url, BeautifulSoup("<p>教师简介</p>", "html.parser"), "示例导师 教授", "教师简介"),
            ) as html:
                discover_urls_via_directory_crawl(config, str(target), str(interests), max_pages_per_domain=1)
            specialized.assert_not_called()
            html.assert_called_once()


if __name__ == "__main__":
    unittest.main()
