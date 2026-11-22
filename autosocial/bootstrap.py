"""Initialize a fresh workspace without overwriting an existing application."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from .config import AppConfig
from .data_io import load_discovery_prompts
from .preferences import load_preferences, sync_interests_file
from .storage import connect, init_db


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMAIL_TEMPLATE = """邮件主题：博士申请咨询 - {{student_name}} - {{student_school}}

{{professor_salutation}}：

您好！我是{{student_school}}的{{student_name}}，希望向您咨询博士招生与研究交流的机会。

{{student_summary_paragraph}}

{{professor_thinking_paragraph}}

如您方便，希望进一步了解您目前的研究计划与招生安排。感谢您阅读这封邮件。

{{student_name}}
{{student_contact}}
"""


def _create_missing(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        pass


def ensure_workspace(workspace: str | Path | None = None, *, database_path: str | None = None) -> None:
    """Create missing files and migrate the database; preserve user content."""
    root = Path(workspace) if workspace is not None else Path.cwd()
    for directory in ("data", "data/attachments", "templates", "runtime"):
        (root / directory).mkdir(parents=True, exist_ok=True)

    example_profile = PROJECT_ROOT / "student_profile.example.md"
    _create_missing(root / "student_profile.md", example_profile.read_text(encoding="utf-8-sig"))
    _create_missing(root / "templates/email_template.md", DEFAULT_EMAIL_TEMPLATE)
    _create_missing(root / "data/target_schools.csv", "school,institute,domains,entry_urls,search_hint\n")

    preferences = load_preferences(str(root / "data/user_preferences.json"))
    if not (root / "data/interests.txt").exists():
        sync_interests_file(preferences, str(root / "data/interests.txt"))
    load_discovery_prompts(str(root / "data/discovery_prompts.json"))

    db_path = Path(database_path if database_path is not None else AppConfig().database_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    with closing(connect(str(db_path))) as conn:
        init_db(conn)
