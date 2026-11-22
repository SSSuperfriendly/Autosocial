from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path

from .config import AppConfig
from .bootstrap import ensure_workspace
from .mail import (
    attachment_paths_from_dir,
    send_via_smtp,
    sync_replies_for_sender,
    test_imap_login,
)
from .discovery import (
    discover_urls_via_bigmodel_search,
    discover_urls_via_ddg,
    discover_urls_via_directory_crawl,
    discover_urls_via_openai_search,
    write_discovery_rows,
)
from .services import (
    LLMClient,
    email_matches_source_domain,
    fetch_page_content,
    generate_locked_draft,
    heuristic_extract_professor,
    load_interest_keywords,
    read_csv_rows,
    render_template,
    write_csv_rows,
)
from .storage import (
    connect,
    init_db,
    record_reply,
    record_sent_email,
    update_draft_review,
    update_professor_review,
    upsert_draft,
    upsert_professor,
)


def _load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _get_professors(conn, only_verified: bool) -> list[dict]:
    sql = "SELECT * FROM professors"
    params = ()
    if only_verified:
        sql += " WHERE verification_status = ?"
        params = ("verified",)
    sql += " ORDER BY school, name"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _get_drafts(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            d.id AS draft_id,
            d.professor_id,
            d.subject,
            d.body,
            d.approval_status,
            d.generator,
            d.generation_notes,
            p.school,
            p.institute,
            p.name,
            p.email,
            p.profile_url
        FROM drafts d
        JOIN professors p ON p.id = d.professor_id
        ORDER BY p.school, p.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def cmd_init_db(args: argparse.Namespace) -> None:
    config = AppConfig()
    ensure_workspace(database_path=config.database_path)
    print(f"Initialized workspace and database at {config.database_path}")


def cmd_discover_urls(args: argparse.Namespace) -> None:
    config = AppConfig()
    if args.backend == "ddg":
        rows = discover_urls_via_ddg(args.targets, args.interests, args.limit_per_school)
    elif args.backend == "bigmodel-search":
        if not config.bigmodel_search_enabled:
            raise SystemExit("BigModel search is not configured. Fill BIGMODEL_SEARCH_* in .env first.")
        rows = discover_urls_via_bigmodel_search(config, args.targets, args.interests, args.limit_per_school)
    elif args.backend == "openai-search":
        if not config.openai_search_enabled:
            raise SystemExit("OpenAI search is not configured. Fill OPENAI_SEARCH_* in .env first.")
        rows = discover_urls_via_openai_search(config, args.targets, args.interests, args.limit_per_school)
    elif args.backend == "directory":
        rows = discover_urls_via_directory_crawl(
            config,
            args.targets,
            args.limit_per_school,
            max_pages_per_domain=args.max_crawl_pages,
            max_depth=args.max_crawl_depth,
        )
    else:
        rows = discover_urls_via_directory_crawl(
            config,
            args.targets,
            args.limit_per_school,
            max_pages_per_domain=args.max_crawl_pages,
            max_depth=args.max_crawl_depth,
        )
        if config.bigmodel_search_enabled:
            rows.extend(discover_urls_via_bigmodel_search(config, args.targets, args.interests, args.limit_per_school))
        if config.openai_search_enabled:
            rows.extend(discover_urls_via_openai_search(config, args.targets, args.interests, args.limit_per_school))
        if not config.bigmodel_search_enabled and not config.openai_search_enabled:
            print("[INFO] No network search backend configured, hybrid mode used directory crawl only")

    deduped: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows:
        if row["url"] in seen_urls:
            continue
        seen_urls.add(row["url"])
        deduped.append(row)

    write_discovery_rows(args.out, deduped)
    print(f"Wrote {len(deduped)} discovery rows to {args.out}")


def cmd_ingest_urls(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    init_db(conn)
    keywords = load_interest_keywords(args.interests)
    llm = LLMClient(config) if config.llm_enabled else None
    rows = read_csv_rows(args.file)
    success = 0
    failures = 0
    for row in rows:
        url = row.get("url", "").strip()
        if not url:
            continue
        try:
            content = fetch_page_content(url, config)
            if llm:
                extracted = llm.extract_professor(content, row.get("school", ""), row.get("institute", ""), keywords)
            else:
                extracted = heuristic_extract_professor(content, row.get("school", ""), row.get("institute", ""), keywords)
            upsert_professor(conn, extracted)
            success += 1
            print(f"[OK] {url}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {url} -> {exc}")
    print(f"Ingest finished. success={success} failures={failures}")


def cmd_export_professors_review(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    rows = conn.execute(
        """
        SELECT
            id,
            school,
            institute,
            name,
            email,
            title,
            profile_url,
            source_domain,
            research_summary,
            matched_topics,
            verification_status,
            notes
        FROM professors
        ORDER BY school, name
        """
    ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["matched_topics"] = " | ".join(json.loads(item["matched_topics"] or "[]"))
        item["manual_verification"] = ""
        item["manual_notes"] = ""
        output.append(item)
    write_csv_rows(
        args.out,
        [
            "id",
            "school",
            "institute",
            "name",
            "email",
            "title",
            "profile_url",
            "source_domain",
            "research_summary",
            "matched_topics",
            "verification_status",
            "notes",
            "manual_verification",
            "manual_notes",
        ],
        output,
    )
    print(f"Exported professor review sheet to {args.out}")


def cmd_apply_professors_review(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    rows = read_csv_rows(args.file)
    applied = 0
    for row in rows:
        status = (row.get("manual_verification") or "").strip()
        if status not in {"verified", "rejected", "needs_review"}:
            continue
        update_professor_review(conn, int(row["id"]), status, (row.get("manual_notes") or "").strip() or None)
        applied += 1
    print(f"Applied {applied} professor review updates")


def cmd_generate_drafts(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    professors = _get_professors(conn, only_verified=not args.include_needs_review)
    student_profile = _load_text(args.student_profile)
    template = _load_text(args.template)
    created = 0
    for professor in professors:
        professor["matched_topics"] = json.loads(professor["matched_topics"] or "[]")
        draft, generator = generate_locked_draft(
            config,
            professor,
            student_profile,
            template,
            config.sender_email,
            thinking_mode="conservative",
        )
        upsert_draft(
            conn,
            {
                "professor_id": professor["id"],
                "subject": draft["subject"].strip(),
                "body": draft["body"].strip(),
                "approval_status": "needs_review",
                "generator": generator,
                "generation_notes": None,
            },
        )
        created += 1
    print(f"Generated {created} drafts")


def cmd_export_drafts_review(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    rows = _get_drafts(conn)
    output = []
    for row in rows:
        row["manual_approval"] = ""
        row["manual_notes"] = ""
        output.append(row)
    write_csv_rows(
        args.out,
        [
            "draft_id",
            "professor_id",
            "school",
            "institute",
            "name",
            "email",
            "profile_url",
            "subject",
            "body",
            "approval_status",
            "generator",
            "generation_notes",
            "manual_approval",
            "manual_notes",
        ],
        output,
    )
    print(f"Exported draft review sheet to {args.out}")


def cmd_apply_drafts_review(args: argparse.Namespace) -> None:
    config = AppConfig()
    conn = connect(config.database_path)
    rows = read_csv_rows(args.file)
    applied = 0
    for row in rows:
        status = (row.get("manual_approval") or "").strip()
        if status not in {"approved", "rejected", "needs_review"}:
            continue
        update_draft_review(conn, int(row["draft_id"]), status, (row.get("manual_notes") or "").strip() or None)
        applied += 1
    print(f"Applied {applied} draft review updates")


def cmd_send_approved(args: argparse.Namespace) -> None:
    # Keep CLI and HTTP deliveries behind the same approval and deduplication rules.
    from .dashboard_backend import send_selected_professors

    if args.limit <= 0:
        raise SystemExit("--limit must be greater than zero.")
    config = AppConfig()
    if not args.dry_run and not config.smtp_enabled:
        raise SystemExit("SMTP is not configured. Fill .env first.")
    with closing(connect(config.database_path)) as conn:
        rows = conn.execute(
            """SELECT p.id FROM drafts d JOIN professors p ON p.id = d.professor_id
               WHERE d.approval_status = 'approved' AND p.trashed_at IS NULL
               ORDER BY p.school, p.name LIMIT ?""",
            (args.limit,),
        ).fetchall()
        result = send_selected_professors(
            config, conn, [int(row["id"]) for row in rows],
            auto_prepare=False, dry_run=bool(args.dry_run),
        )
    for failure in result["failures"]:
        print(f"[SKIP/FAIL] {failure['name']} -> {failure['reason']}")
    print(
        f"Finished send-approved. processed={result['processed']} ready={result['ready']} "
        f"sent={result['sent']} skipped={result['skipped']} dry_run={result['dry_run']}"
    )


def cmd_send_test(args: argparse.Namespace) -> None:
    config = AppConfig()
    if not config.smtp_enabled:
        raise SystemExit("SMTP is not configured. Fill .env first.")
    attachments = attachment_paths_from_dir(config.attachment_dir if not args.no_attachments else "")
    body = args.body
    if not body:
        body = (
            "您好！\n\n"
            "这是一封来自 AutoSocial 的测试邮件，用于验证 SMTP、附件和发件配置是否正常。\n\n"
            f"发件人：{config.sender_email}\n"
            "发送时间：本地测试\n"
        )
    if args.dry_run:
        print(f"[DRY-RUN] to={args.to} subject={args.subject} attachments={len(attachments)}")
        return
    message_id = send_via_smtp(
        config,
        args.to,
        args.subject,
        body,
        attachment_paths=attachments,
    )
    print(f"[SENT] to={args.to} message_id={message_id} attachments={len(attachments)}")


def cmd_test_imap(args: argparse.Namespace) -> None:
    config = AppConfig()
    if not config.imap_enabled:
        raise SystemExit("IMAP is not configured. Fill .env first.")
    ok, message = test_imap_login(config)
    if ok:
        print(f"[OK] {message}")
    else:
        print(f"[FAIL] {message}")


def cmd_sync_replies(args: argparse.Namespace) -> None:
    from .dashboard_backend import sync_all_replies

    if not 1 <= args.days <= 3650:
        raise SystemExit("--days must be between 1 and 3650.")
    config = AppConfig()
    if not config.imap_enabled:
        raise SystemExit("IMAP is not configured. Fill .env first.")
    with closing(connect(config.database_path)) as conn:
        total = sync_all_replies(config, conn, days=args.days)
    print(f"Synced {total} new replies")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autosocial", description="Safe outreach automation for contacting professors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="Initialize SQLite database")
    init_db_parser.set_defaults(func=cmd_init_db)

    discover_parser = subparsers.add_parser("discover-urls", help="Discover candidate faculty profile URLs")
    discover_parser.add_argument("--targets", default="data/target_schools.csv")
    discover_parser.add_argument("--interests", default="data/interests.txt")
    discover_parser.add_argument("--out", default="data/discovered_urls.csv")
    discover_parser.add_argument("--limit-per-school", type=int, default=20)
    discover_parser.add_argument("--backend", choices=["ddg", "bigmodel-search", "openai-search", "directory", "hybrid"], default="hybrid")
    discover_parser.add_argument("--max-crawl-pages", type=int, default=24)
    discover_parser.add_argument("--max-crawl-depth", type=int, default=2)
    discover_parser.set_defaults(func=cmd_discover_urls)

    ingest_parser = subparsers.add_parser("ingest-urls", help="Fetch URLs and extract professor information")
    ingest_parser.add_argument("--file", required=True)
    ingest_parser.add_argument("--interests", default="data/interests.txt")
    ingest_parser.set_defaults(func=cmd_ingest_urls)

    export_prof_parser = subparsers.add_parser("export-professors-review", help="Export professor review CSV")
    export_prof_parser.add_argument("--out", required=True)
    export_prof_parser.set_defaults(func=cmd_export_professors_review)

    apply_prof_parser = subparsers.add_parser("apply-professors-review", help="Apply professor review CSV")
    apply_prof_parser.add_argument("--file", required=True)
    apply_prof_parser.set_defaults(func=cmd_apply_professors_review)

    generate_parser = subparsers.add_parser("generate-drafts", help="Generate email drafts")
    generate_parser.add_argument("--student-profile", required=True)
    generate_parser.add_argument("--template", default="templates/email_template.md")
    generate_parser.add_argument("--include-needs-review", action="store_true")
    generate_parser.set_defaults(func=cmd_generate_drafts)

    export_drafts_parser = subparsers.add_parser("export-drafts-review", help="Export draft review CSV")
    export_drafts_parser.add_argument("--out", required=True)
    export_drafts_parser.set_defaults(func=cmd_export_drafts_review)

    apply_drafts_parser = subparsers.add_parser("apply-drafts-review", help="Apply draft review CSV")
    apply_drafts_parser.add_argument("--file", required=True)
    apply_drafts_parser.set_defaults(func=cmd_apply_drafts_review)

    send_parser = subparsers.add_parser("send-approved", help="Send approved drafts")
    send_parser.add_argument("--limit", type=int, default=50)
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.set_defaults(func=cmd_send_approved)

    send_test_parser = subparsers.add_parser("send-test", help="Send a test email")
    send_test_parser.add_argument("--to", required=True)
    send_test_parser.add_argument("--subject", default="AutoSocial 测试邮件")
    send_test_parser.add_argument("--body", default="")
    send_test_parser.add_argument("--dry-run", action="store_true")
    send_test_parser.add_argument("--no-attachments", action="store_true")
    send_test_parser.set_defaults(func=cmd_send_test)

    test_imap_parser = subparsers.add_parser("test-imap", help="Test IMAP login")
    test_imap_parser.set_defaults(func=cmd_test_imap)

    sync_parser = subparsers.add_parser("sync-replies", help="Sync replies from IMAP inbox")
    sync_parser.add_argument("--days", type=int, default=30)
    sync_parser.set_defaults(func=cmd_sync_replies)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
