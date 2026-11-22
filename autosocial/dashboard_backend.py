from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse
from uuid import uuid4

from .preferences import research_profile_summary
from .config import AppConfig
from .data_io import (
    active_prompt_suffix,
    load_discovery_prompts,
    load_target_schools_table,
    load_user_preferences,
    read_text_file,
    save_discovery_prompts,
    save_target_schools_table,
    save_user_preferences,
    write_text_file,
)
from .scoring import (
    score_note_priority_heuristic,
    score_professor_fit,
    score_professor_interaction_priority,
)
from .mail import (
    attachment_paths_from_dir,
    send_via_smtp,
    sync_replies_for_sender,
    test_imap_login,
    test_smtp_login,
)
from .discovery import (
    discover_urls_via_bigmodel_search,
    discover_urls_via_ddg,
    discover_urls_via_directory_crawl,
    discover_urls_via_openai_search,
)
from .services import (
    LLMClient,
    email_matches_source_domain,
    fetch_page_content,
    generate_locked_draft,
    heuristic_extract_professor,
    load_interest_keywords,
    render_template,
    write_csv_rows,
)
from .storage import (
    connect,
    delete_professors,
    init_db,
    move_professors_to_trash,
    record_reply,
    record_sent_email,
    restore_professors_from_trash,
    update_draft_content,
    update_professor_fit_fields,
    update_professor_note_priority,
    upsert_draft,
    upsert_professor,
)


ProgressCallback = Callable[[dict[str, Any]], None]


CONTACT_STAGE_OPTIONS = [
    "new",
    "reviewing",
    "shortlisted",
    "draft_ready",
    "ready_to_send",
    "sent_waiting",
    "replied",
    "in_conversation",
    "rejected",
]

FIT_LABELS = ["高匹配", "中匹配", "待复核", "低匹配"]


def _normalize_school_key(value: str | None) -> str:
    return "".join(str(value or "").replace("\ufeff", " ").split()).casefold()


def _filter_targets_to_temp_csv(targets_path: str, schools: list[str]) -> tuple[str, dict[str, Any]]:
    prompt_suffix = active_prompt_suffix()
    requested_schools = [str(item).strip() for item in schools if str(item).strip()]
    requested_keys = {_normalize_school_key(item) for item in requested_schools}
    if not requested_keys and not prompt_suffix:
        return targets_path, {
            "requested_schools": requested_schools,
            "matched_schools": [],
            "unmatched_schools": [],
            "matched_target_rows": 0,
        }
    rows = []
    matched_schools: list[str] = []
    matched_keys: set[str] = set()
    with open(targets_path, "r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        for row in reader:
            school = str(row.get("school") or "").strip()
            school_key = _normalize_school_key(school)
            if requested_keys and school_key not in requested_keys:
                continue
            if prompt_suffix:
                row["search_hint"] = f"{(row.get('search_hint') or '').strip()} {prompt_suffix}".strip()
            rows.append(row)
            if school and school_key not in matched_keys:
                matched_keys.add(school_key)
                matched_schools.append(school)
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", encoding="utf-8-sig", newline="")
    temp.close()
    write_csv_rows(temp.name, fieldnames, rows)
    unmatched_schools = [school for school in requested_schools if _normalize_school_key(school) not in matched_keys]
    return temp.name, {
        "requested_schools": requested_schools,
        "matched_schools": matched_schools,
        "unmatched_schools": unmatched_schools,
        "matched_target_rows": len(rows),
    }


def _emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    *,
    current: int | None = None,
    total: int | None = None,
    percent: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    payload: dict[str, Any] = {"stage": stage, "message": message}
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if percent is not None:
        payload["percent"] = max(0.0, min(1.0, percent))
    if details:
        payload["details"] = details
    callback(payload)


def get_connection(config: AppConfig | None = None) -> sqlite3.Connection:
    cfg = config or AppConfig()
    conn = connect(cfg.database_path)
    init_db(conn)
    return conn


def _ai_note_priority_by_id(config: AppConfig, rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    if not config.llm_enabled:
        return {}
    candidates = [row for row in rows if str(row.get("notes") or "").strip()]
    if not candidates:
        return {}

    llm = LLMClient(config)
    output: dict[int, dict[str, Any]] = {}
    chunk_size = 20
    for index in range(0, len(candidates), chunk_size):
        chunk = candidates[index : index + chunk_size]
        scored = llm.score_priority_notes(chunk)
        for item in scored:
            professor_id = int(item.get("id") or 0)
            if professor_id <= 0:
                continue
            output[professor_id] = {
                "note_priority_score": float(item.get("note_priority_score") or 0),
                "note_priority_reason": str(item.get("note_priority_reason") or "AI 备注评分"),
                "note_priority_source": "ai",
            }
    return output


def _allowed_backend(config: AppConfig, backend: str, prefs: dict[str, Any]) -> str:
    discovery = prefs.get("discovery", {})
    enabled_map = {
        "bigmodel-search": bool(discovery.get("allow_bigmodel_search", True) and config.bigmodel_search_enabled),
        "openai-search": bool(discovery.get("allow_openai_search", True) and config.openai_search_enabled),
        "directory": bool(discovery.get("allow_directory_crawl", True)),
        "ddg": bool(discovery.get("allow_ddg", False)),
        "hybrid": bool(discovery.get("allow_hybrid", True)),
    }
    if enabled_map.get(backend):
        return backend
    for candidate in ["bigmodel-search", "hybrid", "directory", "openai-search", "ddg"]:
        if enabled_map.get(candidate):
            return candidate
    return "directory"


def _derive_contact_stage(
    *,
    current_stage: str,
    verification_status: str,
    shortlisted: bool,
    draft_status: str | None,
    sent_count: int,
    reply_count: int,
) -> str:
    if verification_status == "rejected":
        return "rejected"
    if current_stage in {"rejected", "in_conversation"}:
        return current_stage
    if reply_count > 0:
        return "replied"
    if sent_count > 0 or draft_status == "sent":
        return "sent_waiting"
    if current_stage in CONTACT_STAGE_OPTIONS and current_stage != "new":
        return current_stage
    if draft_status == "approved" and verification_status == "verified":
        return "ready_to_send"
    if draft_status in {"approved", "needs_review"}:
        return "draft_ready"
    if draft_status == "rejected":
        return "reviewing"
    if shortlisted:
        return "shortlisted"
    if verification_status == "needs_review" and current_stage == "reviewing":
        return "reviewing"
    return "new"


def cleanup_professor_draft_states(conn: sqlite3.Connection, *, commit: bool = True) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT
            p.id,
            p.verification_status,
            p.shortlisted,
            p.contact_stage,
            d.id AS draft_id,
            d.approval_status AS draft_status,
            (
                SELECT COUNT(*)
                FROM sent_emails s
                WHERE s.professor_id = p.id AND s.status = 'sent'
            ) AS sent_count,
            (
                SELECT COUNT(*)
                FROM replies r
                WHERE r.professor_id = p.id
            ) AS reply_count
        FROM professors p
        LEFT JOIN drafts d ON d.professor_id = p.id
        """
    ).fetchall()

    professor_updates = 0
    draft_updates = 0
    changed_professor_ids: list[int] = []

    for row in rows:
        item = dict(row)
        professor_id = int(item["id"])
        draft_id = item.get("draft_id")
        draft_status = str(item.get("draft_status") or "").strip() or None
        sent_count = int(item.get("sent_count") or 0)
        reply_count = int(item.get("reply_count") or 0)
        verification_status = str(item.get("verification_status") or "needs_review")
        shortlisted = bool(item.get("shortlisted"))
        current_stage = str(item.get("contact_stage") or "new")

        normalized_verification = verification_status
        if verification_status != "rejected" and (sent_count > 0 or reply_count > 0):
            normalized_verification = "verified"

        normalized_shortlisted = shortlisted or bool(draft_status) or sent_count > 0 or reply_count > 0
        normalized_stage = _derive_contact_stage(
            current_stage=current_stage,
            verification_status=normalized_verification,
            shortlisted=normalized_shortlisted,
            draft_status=draft_status,
            sent_count=sent_count,
            reply_count=reply_count,
        )

        if (
            normalized_verification != verification_status
            or normalized_shortlisted != shortlisted
            or normalized_stage != current_stage
        ):
            conn.execute(
                """
                UPDATE professors
                SET verification_status = ?,
                    shortlisted = ?,
                    contact_stage = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    normalized_verification,
                    1 if normalized_shortlisted else 0,
                    normalized_stage,
                    professor_id,
                ),
            )
            professor_updates += 1
            changed_professor_ids.append(professor_id)

        if draft_id and draft_status != "sent" and (sent_count > 0 or reply_count > 0):
            conn.execute(
                """
                UPDATE drafts
                SET approval_status = 'sent', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(draft_id),),
            )
            draft_updates += 1

    if commit:
        conn.commit()
    return {
        "checked": len(rows),
        "professor_updates": professor_updates,
        "draft_updates": draft_updates,
        "changed_professor_ids": changed_professor_ids,
    }


def discover_and_ingest(
    config: AppConfig,
    backend: str,
    schools: list[str],
    limit_per_school: int,
    max_crawl_pages: int,
    max_crawl_depth: int,
    *,
    progress_callback: ProgressCallback | None = None,
    targets_path: str = "data/target_schools.csv",
    interests_path: str = "data/interests.txt",
    preferences_path: str = "data/user_preferences.json",
) -> dict[str, Any]:
    conn = get_connection(config)
    preferences = load_user_preferences(preferences_path)
    backend = _allowed_backend(config, backend, preferences)
    min_match_score = int(preferences.get("discovery", {}).get("min_match_score", 35) or 35)
    fallback_backend_used: str | None = None
    search_warnings: list[str] = []

    filtered_targets_path, target_filter_meta = _filter_targets_to_temp_csv(targets_path, schools)
    try:
        if target_filter_meta["requested_schools"] and target_filter_meta["matched_target_rows"] == 0:
            message = "当前所选学校没有匹配到任何入口页配置，请先检查学校名称、目标学校表或入口页。"
            _emit_progress(
                progress_callback,
                "done",
                message,
                current=0,
                total=0,
                percent=1.0,
                details=target_filter_meta,
            )
            not_ingested_rows = [
                {
                    "school": school,
                    "institute": "",
                    "title": "",
                    "url": "",
                    "reason": "未匹配到目标学校配置，无法开始检索",
                }
                for school in target_filter_meta["requested_schools"]
            ]
            return {
                "backend": backend,
                "discovered_count": 0,
                "ingested_count": 0,
                "discovered_rows": [],
                "ingest_failures": [],
                "filtered_out": [],
                "review_required_rows": [],
                "not_ingested_rows": not_ingested_rows,
                "research_profile_summary": research_profile_summary(preferences),
                "fallback_backend_used": None,
                "selection_diagnostics": target_filter_meta,
                "search_warnings": [],
            }

        _emit_progress(progress_callback, "prepare", "已加载研究偏好，准备开始检索。", percent=0.05)
        if backend == "ddg":
            rows = discover_urls_via_ddg(filtered_targets_path, interests_path, limit_per_school)
        elif backend == "bigmodel-search":
            rows = discover_urls_via_bigmodel_search(config, filtered_targets_path, interests_path, limit_per_school)
            if not rows:
                fallback_backend_used = "directory"
                search_warnings.append("智谱联网搜索本轮没有返回可用候选，已自动回退到官网目录抓取。")
                _emit_progress(
                    progress_callback,
                    "search",
                    search_warnings[-1],
                    current=0,
                    total=1,
                    percent=0.18,
                    details=target_filter_meta,
                )
                rows = discover_urls_via_directory_crawl(
                    config,
                    filtered_targets_path,
                    limit_per_school=limit_per_school,
                    max_pages_per_domain=max_crawl_pages,
                    max_depth=max_crawl_depth,
                )
        elif backend == "openai-search":
            rows = discover_urls_via_openai_search(config, filtered_targets_path, interests_path, limit_per_school)
            if not rows:
                fallback_backend_used = "directory"
                search_warnings.append("OpenAI 搜索本轮没有返回可用候选，已自动回退到官网目录抓取。")
                _emit_progress(
                    progress_callback,
                    "search",
                    search_warnings[-1],
                    current=0,
                    total=1,
                    percent=0.18,
                    details=target_filter_meta,
                )
                rows = discover_urls_via_directory_crawl(
                    config,
                    filtered_targets_path,
                    limit_per_school=limit_per_school,
                    max_pages_per_domain=max_crawl_pages,
                    max_depth=max_crawl_depth,
                )
        elif backend == "directory":
            rows = discover_urls_via_directory_crawl(
                config,
                filtered_targets_path,
                limit_per_school=limit_per_school,
                max_pages_per_domain=max_crawl_pages,
                max_depth=max_crawl_depth,
            )
        else:
            rows = discover_urls_via_directory_crawl(
                config,
                filtered_targets_path,
                limit_per_school=limit_per_school,
                max_pages_per_domain=max_crawl_pages,
                max_depth=max_crawl_depth,
            )
            if config.bigmodel_search_enabled and preferences.get("discovery", {}).get("allow_bigmodel_search", True):
                rows.extend(discover_urls_via_bigmodel_search(config, filtered_targets_path, interests_path, limit_per_school))
            if config.openai_search_enabled and preferences.get("discovery", {}).get("allow_openai_search", True):
                rows.extend(discover_urls_via_openai_search(config, filtered_targets_path, interests_path, limit_per_school))

        _emit_progress(
            progress_callback,
            "search",
            f"检索完成，拿到 {len(rows)} 条候选链接，正在去重。",
            current=len(rows),
            total=len(rows) or 1,
            percent=0.35,
            details={
                **target_filter_meta,
                "fallback_backend_used": fallback_backend_used,
                "search_warnings": search_warnings,
            },
        )

        deduped: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for row in rows:
            if row["url"] in seen_urls:
                continue
            seen_urls.add(row["url"])
            deduped.append(row)

        if not deduped:
            not_ingested_rows = [
                {
                    "school": school,
                    "institute": "",
                    "title": "",
                    "url": "",
                    "reason": "没有发现满足规则的导师主页候选，请检查官网入口页、域名白名单，或切换到官网目录/混合模式。",
                }
                for school in (target_filter_meta["matched_schools"] or target_filter_meta["requested_schools"] or ["未指定学校"])
            ]
            _emit_progress(
                progress_callback,
                "done",
                "本轮没有拿到可入池的候选链接，已给出明确原因，方便你继续调入口页或切换后端。",
                current=0,
                total=0,
                percent=1.0,
                details={
                    "ingested": 0,
                    "failed": 0,
                    "review_required": 0,
                    "not_ingested": len(not_ingested_rows),
                    **target_filter_meta,
                    "fallback_backend_used": fallback_backend_used,
                    "search_warnings": search_warnings,
                },
            )
            return {
                "backend": backend,
                "discovered_count": 0,
                "ingested_count": 0,
                "discovered_rows": [],
                "ingest_failures": [],
                "filtered_out": [],
                "review_required_rows": [],
                "not_ingested_rows": not_ingested_rows,
                "research_profile_summary": research_profile_summary(preferences),
                "fallback_backend_used": fallback_backend_used,
                "selection_diagnostics": target_filter_meta,
                "search_warnings": search_warnings,
            }

        _emit_progress(
            progress_callback,
            "dedupe",
            f"去重后剩余 {len(deduped)} 条候选，开始抓取与抽取。",
            current=0,
            total=len(deduped) or 1,
            percent=0.42,
        )

        llm = LLMClient(config) if config.llm_enabled else None
        keywords = load_interest_keywords(interests_path)
        ingest_success = 0
        ingest_failures: list[dict[str, str]] = []
        review_required_rows: list[dict[str, Any]] = []
        not_ingested_rows: list[dict[str, Any]] = []

        total = len(deduped) or 1
        for index, row in enumerate(deduped, start=1):
            try:
                content = fetch_page_content(row["url"], config)
                if llm:
                    extracted = llm.extract_professor(content, row.get("school", ""), row.get("institute", ""), keywords)
                else:
                    extracted = heuristic_extract_professor(content, row.get("school", ""), row.get("institute", ""), keywords)

                extracted["profile_url"] = str(extracted.get("profile_url") or row["url"]).strip()
                extracted["school"] = str(extracted.get("school") or row.get("school") or "").strip()
                extracted["institute"] = str(extracted.get("institute") or row.get("institute") or "").strip() or None
                extracted["source_domain"] = str(extracted.get("source_domain") or row.get("source_domain") or "").strip() or None

                fit_meta = score_professor_fit(extracted, preferences)
                extracted.update(fit_meta)

                review_reasons: list[str] = []
                if not extracted.get("name"):
                    review_reasons.append("缺少姓名")
                if not extracted.get("email"):
                    review_reasons.append("缺少邮箱")
                if float(extracted["fit_score"]) < min_match_score:
                    review_reasons.append(f"匹配分低于阈值 {min_match_score}")

                extracted["contact_stage"] = (
                    "reviewing" if review_reasons else preferences.get("workflow", {}).get("default_contact_stage", "new")
                )
                extracted["notes"] = "；".join(review_reasons) if review_reasons else extracted.get("notes")

                upsert_professor(conn, extracted, commit=False)
                ingest_success += 1

                if review_reasons:
                    review_required_rows.append(
                        {
                            "school": extracted.get("school"),
                            "institute": extracted.get("institute"),
                            "url": row["url"],
                            "name": extracted.get("name"),
                            "email": extracted.get("email"),
                            "fit_score": extracted["fit_score"],
                            "fit_label": extracted["fit_label"],
                            "fit_reason": extracted["fit_reason"],
                            "review_reason": "；".join(review_reasons),
                        }
                    )
            except Exception as exc:
                failure = {"url": row["url"], "error": str(exc), "school": row.get("school", ""), "title": row.get("title", "")}
                ingest_failures.append(failure)
                not_ingested_rows.append(
                    {
                        "url": row["url"],
                        "school": row.get("school", ""),
                        "institute": row.get("institute", ""),
                        "title": row.get("title", ""),
                        "reason": str(exc),
                    }
                )

            percent = 0.42 + (index / total) * 0.54
            _emit_progress(
                progress_callback,
                "extract",
                f"已处理 {index}/{total} 条候选。",
                current=index,
                total=total,
                percent=percent,
                details={
                    "ingested": ingest_success,
                    "failed": len(ingest_failures),
                    "review_required": len(review_required_rows),
                    "not_ingested": len(not_ingested_rows),
                },
            )

        _emit_progress(
            progress_callback,
            "done",
            f"完成：入库 {ingest_success} 条，需重点复核 {len(review_required_rows)} 条，真正未入库 {len(not_ingested_rows)} 条。",
            current=total,
            total=total,
            percent=1.0,
        )
        conn.commit()
        return {
            "backend": backend,
            "discovered_count": len(deduped),
            "ingested_count": ingest_success,
            "discovered_rows": deduped,
            "ingest_failures": ingest_failures,
            "filtered_out": [],
            "review_required_rows": review_required_rows,
            "not_ingested_rows": not_ingested_rows,
            "research_profile_summary": research_profile_summary(preferences),
            "fallback_backend_used": fallback_backend_used,
            "selection_diagnostics": target_filter_meta,
            "search_warnings": search_warnings,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        if filtered_targets_path != targets_path:
            Path(filtered_targets_path).unlink(missing_ok=True)


def refresh_professor_scores(
    config: AppConfig,
    conn: sqlite3.Connection,
    preferences_path: str = "data/user_preferences.json",
) -> int:
    preferences = load_user_preferences(preferences_path)
    rows = conn.execute(
        """
        SELECT
            id, school, institute, name, email, title, profile_url,
            research_summary, matched_topics, publication_signal, scholar_url,
            contact_stage, notes
        FROM professors
        """
    ).fetchall()
    payloads = [dict(row) for row in rows]
    ai_note_scores: dict[int, dict[str, Any]] = {}
    try:
        ai_note_scores = _ai_note_priority_by_id(config, payloads)
    except Exception:
        ai_note_scores = {}

    updated = 0
    try:
        for payload in payloads:
            payload["matched_topics"] = json.loads(payload.get("matched_topics") or "[]")
            fit_meta = score_professor_fit(payload, preferences)
            update_professor_fit_fields(
                conn,
                professor_id=int(payload["id"]),
                fit_score=float(fit_meta["fit_score"]),
                fit_label=str(fit_meta["fit_label"]),
                fit_reason=fit_meta.get("fit_reason"),
                scholar_url=fit_meta.get("scholar_url"),
                commit=False,
            )
            note_meta = ai_note_scores.get(int(payload["id"])) or score_note_priority_heuristic(payload.get("notes"))
            update_professor_note_priority(
                conn,
                professor_id=int(payload["id"]),
                note_priority_score=float(note_meta.get("note_priority_score") or 0),
                note_priority_reason=str(note_meta.get("note_priority_reason") or ""),
                note_priority_source=str(note_meta.get("note_priority_source") or "heuristic"),
                commit=False,
            )
            updated += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return updated


def load_professors(
    conn: sqlite3.Connection,
    shortlisted_only: bool = False,
    trashed_only: bool = False,
    include_trashed: bool = False,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            p.id,
            p.school,
            p.institute,
            p.name,
            p.email,
            p.title,
            p.profile_url,
            p.source_domain,
            p.research_summary,
            p.matched_topics,
            p.verification_status,
            p.shortlisted,
            p.fit_score,
            p.fit_label,
            p.fit_reason,
            p.contact_stage,
            p.publication_signal,
            p.scholar_url,
            p.last_contacted_at,
            p.last_replied_at,
            p.next_follow_up,
            p.next_action,
            p.notes,
            p.note_priority_score,
            p.note_priority_reason,
            p.note_priority_source,
            p.trashed_at,
            p.created_at,
            d.approval_status AS draft_status,
            p.updated_at
        FROM professors p
        LEFT JOIN drafts d ON d.professor_id = p.id
    """
    conditions: list[str] = []
    if shortlisted_only:
        conditions.append("p.shortlisted = 1")
    if trashed_only:
        conditions.append("p.trashed_at IS NOT NULL")
    elif not include_trashed:
        conditions.append("p.trashed_at IS NULL")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY p.shortlisted DESC, p.fit_score DESC, p.school, p.name"
    rows = conn.execute(sql).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["matched_topics"] = " | ".join(json.loads(item["matched_topics"] or "[]"))
        item["shortlisted"] = bool(item["shortlisted"])
        if item.get("notes") and (
            item.get("note_priority_source") == "none"
            or (not item.get("note_priority_reason") and float(item.get("note_priority_score") or 0) == 0)
        ):
            item.update(score_note_priority_heuristic(item.get("notes")))
        item.update(score_professor_interaction_priority(item))
        output.append(item)
    return output


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_topics(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    text = text.replace("；", "|").replace("，", "|").replace(",", "|").replace("/", "|")
    return [item.strip() for item in text.split("|") if item.strip()]


def _manual_profile_url(row: dict[str, Any]) -> str:
    parts = [
        _clean_text(row.get("school")),
        _clean_text(row.get("institute")),
        _clean_text(row.get("name")),
    ]
    slug = "-".join(part for part in parts if part)
    token = quote_plus(slug) if slug else uuid4().hex[:10]
    return f"manual://{token}-{uuid4().hex[:8]}"


def _source_domain_from_profile_url(profile_url: str | None) -> str | None:
    if not profile_url:
        return None
    parsed = urlparse(profile_url)
    if parsed.netloc:
        return parsed.netloc.lower()
    if parsed.scheme == "manual":
        return "manual"
    return None


def _row_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(value)


def save_professor_table(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    preferences = load_user_preferences()
    for row in rows:
        professor_id = int(row["id"]) if str(row.get("id") or "").strip().lstrip("-").isdigit() else None
        existing = None
        if professor_id and professor_id > 0:
            existing = conn.execute("SELECT * FROM professors WHERE id = ?", (professor_id,)).fetchone()

        existing_data = dict(existing) if existing else {}
        existing_topics = _parse_topics(existing_data.get("matched_topics"))

        school = _clean_text(row.get("school")) or _clean_text(existing_data.get("school")) or ""
        if not school:
            continue

        payload: dict[str, Any] = {
            "school": school,
            "institute": _clean_text(row.get("institute")) if "institute" in row else _clean_text(existing_data.get("institute")),
            "name": _clean_text(row.get("name")) if "name" in row else _clean_text(existing_data.get("name")),
            "email": _clean_text(row.get("email")) if "email" in row else _clean_text(existing_data.get("email")),
            "title": _clean_text(row.get("title")) if "title" in row else _clean_text(existing_data.get("title")),
            "research_summary": (
                _clean_text(row.get("research_summary"))
                if "research_summary" in row
                else _clean_text(existing_data.get("research_summary"))
            ),
            "profile_url": _clean_text(row.get("profile_url")) or _clean_text(existing_data.get("profile_url")),
            "verification_status": str(row.get("verification_status") or existing_data.get("verification_status") or "needs_review"),
            "shortlisted": _row_bool(row.get("shortlisted"), bool(existing_data.get("shortlisted"))),
            "contact_stage": str(row.get("contact_stage") or existing_data.get("contact_stage") or "new"),
            "publication_signal": (
                _clean_text(row.get("publication_signal"))
                if "publication_signal" in row
                else _clean_text(existing_data.get("publication_signal"))
            ),
            "notes": _clean_text(row.get("notes")) if "notes" in row else _clean_text(existing_data.get("notes")),
            "scholar_url": _clean_text(row.get("scholar_url")) or _clean_text(existing_data.get("scholar_url")),
            "matched_topics": _parse_topics(row.get("matched_topics")) if "matched_topics" in row else existing_topics,
        }
        if not payload["profile_url"]:
            payload["profile_url"] = _manual_profile_url(payload)

        profile_conflict = conn.execute(
            "SELECT id, name, school FROM professors WHERE profile_url = ? AND id != ?",
            (payload["profile_url"], professor_id or -1),
        ).fetchone()
        if profile_conflict:
            if professor_id:
                owner_name = profile_conflict["name"] or "未命名导师"
                owner_school = profile_conflict["school"] or "学校未填"
                raise ValueError(f"该主页已属于导师：{owner_name}（{owner_school}），请先在导师池中编辑原记录，或更换主页链接。")
            professor_id = int(profile_conflict["id"])
            existing = conn.execute("SELECT * FROM professors WHERE id = ?", (professor_id,)).fetchone()
            existing_data = dict(existing) if existing else {}

        payload["source_domain"] = _source_domain_from_profile_url(payload["profile_url"])

        fit_meta = score_professor_fit(payload, preferences)
        payload["fit_score"] = float(fit_meta["fit_score"])
        payload["fit_label"] = str(fit_meta["fit_label"])
        payload["fit_reason"] = fit_meta.get("fit_reason")
        payload["scholar_url"] = payload["scholar_url"] or fit_meta.get("scholar_url")

        if existing:
            conn.execute(
                """
                UPDATE professors
                SET
                    school = ?,
                    institute = ?,
                    name = ?,
                    email = ?,
                    title = ?,
                    profile_url = ?,
                    source_domain = ?,
                    research_summary = ?,
                    matched_topics = ?,
                    verification_status = ?,
                    shortlisted = ?,
                    fit_score = ?,
                    fit_label = ?,
                    fit_reason = ?,
                    contact_stage = ?,
                    publication_signal = ?,
                    scholar_url = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload["school"],
                    payload["institute"],
                    payload["name"],
                    payload["email"],
                    payload["title"],
                    payload["profile_url"],
                    payload["source_domain"],
                    payload["research_summary"],
                    json.dumps(payload["matched_topics"], ensure_ascii=False),
                    payload["verification_status"],
                    1 if payload["shortlisted"] else 0,
                    payload["fit_score"],
                    payload["fit_label"],
                    payload["fit_reason"],
                    payload["contact_stage"],
                    payload["publication_signal"],
                    payload["scholar_url"],
                    payload["notes"],
                    professor_id,
                ),
            )
            note_meta = score_note_priority_heuristic(payload.get("notes"))
            update_professor_note_priority(
                conn,
                professor_id=professor_id,
                note_priority_score=float(note_meta.get("note_priority_score") or 0),
                note_priority_reason=str(note_meta.get("note_priority_reason") or ""),
                note_priority_source=str(note_meta.get("note_priority_source") or "heuristic"),
                commit=False,
            )
        else:
            new_professor_id = upsert_professor(
                conn,
                {
                    **payload,
                    "fit_score": payload["fit_score"],
                    "fit_label": payload["fit_label"],
                    "fit_reason": payload["fit_reason"],
                },
                commit=False,
            )
            note_meta = score_note_priority_heuristic(payload.get("notes"))
            update_professor_note_priority(
                conn,
                professor_id=new_professor_id,
                note_priority_score=float(note_meta.get("note_priority_score") or 0),
                note_priority_reason=str(note_meta.get("note_priority_reason") or ""),
                note_priority_source=str(note_meta.get("note_priority_source") or "heuristic"),
                commit=False,
            )
    cleanup_professor_draft_states(conn, commit=False)
    conn.commit()


def delete_professor_rows(conn: sqlite3.Connection, professor_ids: list[int]) -> int:
    cleaned = sorted({int(item) for item in professor_ids if item is not None})
    return delete_professors(conn, cleaned)


def trash_professor_rows(conn: sqlite3.Connection, professor_ids: list[int]) -> int:
    cleaned = sorted({int(item) for item in professor_ids if item is not None})
    return move_professors_to_trash(conn, cleaned)


def restore_professor_rows(conn: sqlite3.Connection, professor_ids: list[int]) -> int:
    cleaned = sorted({int(item) for item in professor_ids if item is not None})
    return restore_professors_from_trash(conn, cleaned)


def generate_drafts_for_selected(
    config: AppConfig,
    conn: sqlite3.Connection,
    selected_professor_ids: list[int],
    student_profile_path: str = "student_profile.md",
    template_path: str = "templates/email_template.md",
    auto_approve: bool = False,
    thinking_mode: str = "conservative",
) -> int:
    if not selected_professor_ids:
        return 0
    placeholders = ",".join("?" for _ in selected_professor_ids)
    rows = conn.execute(
        f"SELECT * FROM professors WHERE id IN ({placeholders}) AND trashed_at IS NULL ORDER BY fit_score DESC, school, name",
        selected_professor_ids,
    ).fetchall()
    student_profile = Path(student_profile_path).read_text(encoding="utf-8")
    template = Path(template_path).read_text(encoding="utf-8")
    created = 0
    try:
        for row in rows:
            professor = dict(row)
            professor["matched_topics"] = json.loads(professor["matched_topics"] or "[]")
            draft, generator = generate_locked_draft(
                config,
                professor,
                student_profile,
                template,
                config.sender_email,
                thinking_mode=thinking_mode,
            )
            upsert_draft(
                conn,
                {
                    "professor_id": professor["id"],
                    "subject": draft["subject"].strip(),
                    "body": draft["body"].strip(),
                    "approval_status": "approved" if auto_approve else "needs_review",
                    "generator": generator,
                    "generation_notes": None,
                },
                commit=False,
            )
            conn.execute(
                """
                UPDATE professors
                SET contact_stage = CASE WHEN contact_stage IN ('sent_waiting', 'replied', 'in_conversation', 'rejected')
                        THEN contact_stage ELSE ? END, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("ready_to_send" if auto_approve else "draft_ready", professor["id"]),
            )
            created += 1
        cleanup_professor_draft_states(conn, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return created


def load_drafts(conn: sqlite3.Connection, shortlisted_only: bool = False) -> list[dict[str, Any]]:
    sql = """
        SELECT
            d.id AS draft_id,
            d.professor_id,
            d.subject,
            d.body,
            d.approval_status,
            d.generator,
            d.generation_notes,
            p.school,
            p.name,
            p.email,
            p.fit_score,
            p.contact_stage,
            p.shortlisted
        FROM drafts d
        JOIN professors p ON p.id = d.professor_id
    """
    conditions = ["p.trashed_at IS NULL"]
    if shortlisted_only:
        conditions.append("p.shortlisted = 1")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY p.shortlisted DESC, p.fit_score DESC, p.school, p.name"
    return [dict(row) for row in conn.execute(sql).fetchall()]


def save_draft_table(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    try:
        for row in rows:
            status = str(row.get("approval_status") or "needs_review")
            update_draft_content(
                conn,
                int(row["draft_id"]),
                str(row.get("subject") or ""),
                str(row.get("body") or ""),
                status,
                commit=False,
            )
            next_stage = None
            if status == "approved":
                next_stage = "ready_to_send"
            elif status == "needs_review":
                next_stage = "draft_ready"
            elif status == "rejected":
                next_stage = "reviewing"
            if next_stage and row.get("professor_id"):
                conn.execute(
                    "UPDATE professors SET contact_stage = CASE WHEN contact_stage IN ('sent_waiting', 'replied', 'in_conversation', 'rejected') THEN contact_stage ELSE ? END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (next_stage, int(row["professor_id"])),
                )
        cleanup_professor_draft_states(conn, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def send_selected_professors(
    config: AppConfig,
    conn: sqlite3.Connection,
    professor_ids: list[int],
    auto_prepare: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Preview or send reviewed drafts. Legacy auto_prepare never approves mail.

    A persisted 'sending' claim prevents concurrent requests from sending the
    same draft twice. An interrupted delivery stays claimed for manual review;
    SMTP acceptance cannot be rolled back by a database transaction.
    """
    use_test_recipient = not dry_run and config.should_use_test_recipient(False)
    mode = "simulation_only" if dry_run else ("test_recipient_override_all" if use_test_recipient else "direct_send")
    result: dict[str, Any] = {
        "processed": 0, "sent": 0, "ready": 0, "skipped": 0, "failures": [],
        "safety_mode": mode, "dry_run": dry_run,
        "test_recipient_email": config.test_recipient_email if use_test_recipient else None,
    }
    attachments = attachment_paths_from_dir(config.attachment_dir) if not dry_run else []

    def load_candidate(professor_id: int):
        return conn.execute(
            """SELECT d.id AS draft_id, d.subject, d.body, d.approval_status,
                      p.id AS professor_id, p.name, p.email, p.profile_url,
                      p.source_domain, p.verification_status,
                      EXISTS (SELECT 1 FROM sent_emails s WHERE s.professor_id = p.id
                              AND s.status IN ('sent', 'sending')) AS already_sent
               FROM professors p LEFT JOIN drafts d ON d.professor_id = p.id
               WHERE p.id = ? AND p.trashed_at IS NULL""", (professor_id,)
        ).fetchone()

    def rejection(item) -> str | None:
        if item is None:
            return "导师不存在或已移入回收站"
        if item["already_sent"] or item["approval_status"] == "sent":
            return "已发送或正在发送，请在跟进工作台记录后续沟通，避免重复投递"
        if item["verification_status"] != "verified":
            return "导师未核验"
        if item["draft_id"] is None or item["approval_status"] != "approved":
            return "草稿未批准"
        if not str(item["subject"] or "").strip() or not str(item["body"] or "").strip():
            return "邮件主题或正文为空"
        if not item["name"] or not item["email"] or not item["profile_url"]:
            return "姓名、邮箱或主页信息不完整"
        if not email_matches_source_domain(item["email"], item["source_domain"] or ""):
            return "邮箱域名与来源主页不一致"
        if not dry_run and not config.smtp_enabled:
            return "SMTP 未配置完整"
        return None

    for professor_id in dict.fromkeys(professor_ids):
        result["processed"] += 1
        claim_id = None
        item = None
        try:
            if not dry_run:
                conn.execute("BEGIN IMMEDIATE")
            item = load_candidate(professor_id)
            reason = rejection(item)
            if reason:
                if not dry_run:
                    conn.rollback()
                result["skipped"] += 1
                result["failures"].append({"name": item["name"] if item else str(professor_id), "reason": reason})
                continue
            result["ready"] += 1
            if dry_run:
                continue
            delivery_email = config.test_recipient_email if use_test_recipient else item["email"]
            subject = item["subject"]
            body = item["body"]
            if use_test_recipient:
                subject = f"[测试覆盖→{item['name']}<{item['email']}>] {subject}"
                body = f"测试投递，真实导师未收到此邮件。原始目标：{item['email']}\n\n{body}"
            cursor = conn.execute(
                """INSERT INTO sent_emails (draft_id, professor_id, to_email, subject, status)
                   VALUES (?, ?, ?, ?, 'sending')""",
                (item["draft_id"], item["professor_id"], delivery_email, subject),
            )
            claim_id = cursor.lastrowid
            conn.commit()
            message_id = send_via_smtp(config, delivery_email, subject, body, attachment_paths=attachments)
            with conn:
                record_sent_email(
                    conn, draft_id=item["draft_id"], professor_id=item["professor_id"],
                    to_email=delivery_email, subject=subject,
                    status="test" if use_test_recipient else "sent",
                    smtp_message_id=message_id, error_message=None, commit=False,
                )
                conn.execute("DELETE FROM sent_emails WHERE id = ?", (claim_id,))
            result["sent"] += 1
        except Exception as exc:
            conn.rollback()
            if claim_id is not None:
                # SMTP may have accepted a message before a connection failed.
                # Keep the claim blocked rather than retrying an ambiguous send.
                with conn:
                    conn.execute(
                        "UPDATE sent_emails SET error_message = ? WHERE id = ?", (str(exc), claim_id)
                    )
            result["failures"].append({"name": item["name"] if item else str(professor_id), "reason": str(exc)})
    return result


def sync_all_replies(config: AppConfig, conn: sqlite3.Connection, days: int = 30) -> int:
    professors = conn.execute(
        "SELECT id, name, email FROM professors WHERE shortlisted = 1 AND email IS NOT NULL AND trashed_at IS NULL ORDER BY fit_score DESC, school, name"
    ).fetchall()
    total = 0
    try:
        for professor in professors:
            records = sync_replies_for_sender(config, professor["email"], days)
            for record in records:
                inserted = record_reply(
                    conn,
                    professor_id=int(professor["id"]),
                    message_id=record.message_id,
                    from_email=record.from_email,
                    subject=record.subject,
                    body_preview=record.body_preview,
                    received_at=record.received_at,
                    raw_headers=record.raw_headers,
                    commit=False,
                )
                total += int(inserted)
        cleanup_professor_draft_states(conn, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return total


def load_replies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            r.id,
            p.school,
            p.name,
            p.email,
            p.contact_stage,
            r.from_email,
            r.subject,
            r.body_preview,
            r.received_at,
            r.created_at
        FROM replies r
        JOIN professors p ON p.id = r.professor_id
        ORDER BY r.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    metrics["professors_total"] = conn.execute("SELECT COUNT(*) FROM professors WHERE trashed_at IS NULL").fetchone()[0]
    metrics["shortlisted_total"] = conn.execute("SELECT COUNT(*) FROM professors WHERE shortlisted = 1 AND trashed_at IS NULL").fetchone()[0]
    metrics["verified_total"] = conn.execute(
        "SELECT COUNT(*) FROM professors WHERE verification_status = 'verified' AND trashed_at IS NULL"
    ).fetchone()[0]
    metrics["drafts_total"] = conn.execute(
        "SELECT COUNT(*) FROM drafts d JOIN professors p ON p.id = d.professor_id WHERE p.trashed_at IS NULL"
    ).fetchone()[0]
    metrics["approved_total"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM drafts d
        JOIN professors p ON p.id = d.professor_id
        WHERE d.approval_status IN ('approved', 'sent') AND p.trashed_at IS NULL
        """
    ).fetchone()[0]
    metrics["sent_total"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM sent_emails s
        JOIN professors p ON p.id = s.professor_id
        WHERE s.status = 'sent' AND p.trashed_at IS NULL
        """
    ).fetchone()[0]
    metrics["replies_total"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM replies r
        JOIN professors p ON p.id = r.professor_id
        WHERE p.trashed_at IS NULL
        """
    ).fetchone()[0]
    metrics["stage_breakdown"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT contact_stage, COUNT(*) AS count
            FROM professors
            WHERE trashed_at IS NULL
            GROUP BY contact_stage
            ORDER BY count DESC, contact_stage
            """
        ).fetchall()
    ]
    metrics["fit_breakdown"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT fit_label, COUNT(*) AS count
            FROM professors
            WHERE trashed_at IS NULL
            GROUP BY fit_label
            ORDER BY count DESC, fit_label
            """
        ).fetchall()
    ]
    metrics["school_breakdown"] = [
        dict(row)
        for row in conn.execute(
            """
            SELECT school, COUNT(*) AS count
            FROM professors
            WHERE trashed_at IS NULL
            GROUP BY school
            ORDER BY count DESC, school
            """
        ).fetchall()
    ]
    return metrics


def load_system_status(config: AppConfig, preferences_path: str = "data/user_preferences.json") -> dict[str, Any]:
    preferences = load_user_preferences(preferences_path)
    discovery = preferences.get("discovery", {})
    # Loading the workspace must not connect to external mail servers.
    smtp_ok, smtp_message = False, "已配置，尚未检测" if config.smtp_enabled else "未配置"
    imap_ok, imap_message = False, "已配置，尚未检测" if config.imap_enabled else "未配置"
    return {
        "llm": {
            "configured": config.llm_enabled,
            "provider": config.llm_provider,
            "model": config.llm_model,
        },
        "bigmodel_search": {
            "configured": config.bigmodel_search_enabled,
            "enabled_by_preference": bool(discovery.get("allow_bigmodel_search", True)),
            "model": config.bigmodel_search_model,
        },
        "openai_search": {
            "configured": config.openai_search_enabled,
            "enabled_by_preference": bool(discovery.get("allow_openai_search", True)),
            "model": config.openai_search_model,
        },
        "directory_crawl": {
            "configured": True,
            "enabled_by_preference": bool(discovery.get("allow_directory_crawl", True)),
            "model": "builtin",
        },
        "ddg": {
            "configured": True,
            "enabled_by_preference": bool(discovery.get("allow_ddg", False)),
            "model": "duckduckgo-search",
        },
        "smtp": {
            "configured": config.smtp_enabled,
            "healthy": smtp_ok,
            "message": smtp_message,
            "sender": config.sender_email,
            "test_recipient_enabled": config.test_recipient_enabled,
            "test_recipient_mode": config.test_recipient_mode,
            "test_recipient_email": config.test_recipient_email if config.test_recipient_enabled else "",
        },
        "imap": {
            "configured": config.imap_enabled,
            "healthy": imap_ok,
            "message": imap_message,
            "folder": config.imap_folder,
        },
    }
