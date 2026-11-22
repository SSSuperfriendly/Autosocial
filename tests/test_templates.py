import unittest

from autosocial.services import render_template


class TemplateTruthfulnessTests(unittest.TestCase):
    def test_blank_background_does_not_invent_credentials(self):
        draft = render_template(
            "Subject: 联系咨询\n\n{{promotion_status_sentence}}{{student_summary_paragraph}}\n{{professor_thinking_paragraph}}",
            {"name": "示例", "title": "副教授", "research_summary": "自然语言处理"},
            "# 个人简介\n姓名：申请者\n学校：示例大学\n", "",
        )
        self.assertNotIn("获得本校推免资格", draft["body"])
        self.assertNotIn("我之前上过", draft["body"])
        self.assertNotIn("正在持续推进相关科研训练", draft["body"])

    def test_associate_professor_title_is_preserved(self):
        draft = render_template("Subject: 咨询\n\n{{professor_salutation}}", {"name": "陈老师", "title": "副教授"}, "", "")
        self.assertEqual(draft["body"], "陈老师副教授")
