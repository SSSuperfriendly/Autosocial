"""Populate an empty workspace with fictional mentors. Never sends email."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autosocial.bootstrap import ensure_workspace
from autosocial.config import AppConfig
from autosocial.storage import connect, init_db, upsert_professor


def main() -> None:
    ensure_workspace()
    conn = connect(AppConfig().database_path)
    try:
        init_db(conn)
        if conn.execute("SELECT COUNT(*) FROM professors").fetchone()[0]:
            raise SystemExit("Demo data requires an empty database. Use a separate workspace to keep existing records safe.")
        today = date.today()
        mentors = [
            ("林知远", "青川大学（虚构）", "计算社会科学", "in_conversation", -1, "整理面谈问题与研究计划", "meeting", "已交流研究兴趣，约定下次讨论研究计划。"),
            ("陈思宁", "海岚大学（虚构）", "人机交互", "sent_waiting", 0, "跟进上周的联系邮件", "email_sent", "发送了个人简介，询问博士招生与研究方向。"),
            ("周予安", "星河大学（虚构）", "可持续城市", "replied", 2, "补充一页研究计划", "reply", "老师建议先发一页研究问题，暂未确认招生名额。"),
            ("许明澈", "青川大学（虚构）", "自然语言处理", "shortlisted", 5, "阅读近期论文并准备初次联系", "note", "关注课题组近期研究，计划阅读两篇论文。"),
            ("宋以南", "海岚大学（虚构）", "科学史", "new", None, "核对博士招生要求", "note", "从官网收集到导师信息，尚未联系。"),
        ]
        with conn:
            for index, (name, school, research, stage, offset, action, kind, content) in enumerate(mentors, 1):
                professor_id = upsert_professor(conn, {
                    "name": name, "school": school, "research_summary": research,
                    "email": f"mentor{index}@university.example",
                    "profile_url": f"https://university.example/faculty/{index}",
                    "title": "教授", "verification_status": "needs_review",
                    "shortlisted": index < 5, "contact_stage": stage,
                    "notes": "虚构演示数据，请替换为自己的记录。",
                }, commit=False)
                day = today + timedelta(days=offset) if offset is not None else None
                event_day = today - timedelta(days=7)
                conn.execute("UPDATE professors SET next_follow_up=?, next_action=? WHERE id=?", (day.isoformat() if day else None, action, professor_id))
                conn.execute("INSERT INTO contact_events(professor_id, kind, content, occurred_at) VALUES(?, ?, ?, ?)", (professor_id, kind, content, event_day.isoformat() + "T09:00:00+00:00"))
                if kind == "email_sent":
                    conn.execute("UPDATE professors SET last_contacted_at=? WHERE id=?", (event_day.isoformat() + "T09:00:00+00:00", professor_id))
                if kind == "reply":
                    conn.execute("UPDATE professors SET last_replied_at=? WHERE id=?", (event_day.isoformat() + "T09:00:00+00:00", professor_id))
        print("Added 5 fictional mentors. No email was sent. Open the workbench to explore.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
