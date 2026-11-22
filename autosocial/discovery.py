"""URL discovery backends for finding faculty profile pages.

This module contains the four discovery backends (DuckDuckGo, OpenAI Search,
BigModel Search, Directory Crawl) and their supporting helpers.  It imports
shared utilities (URL normalisation, HTTP fetching, text matching) from
.services.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

from .config import AppConfig
from .services import (
    # --- constants ---
    ASSET_SUFFIXES,
    CANDIDATE_DIRECTORY_PATH_TOKENS,
    COMMON_DIRECTORY_PATHS,
    COMMON_CHINESE_SURNAMES,
    DIRECTORY_KEYWORDS,
    DIRECTORY_PAGE_NEGATIVE_HINTS,
    DIRECTORY_URL_HINTS,
    DISCOVERY_FIELDS,
    GENERIC_ANCHOR_KEYWORDS,
    GENERIC_DETAIL_ANCHORS,
    GENERIC_URL_TOKENS,
    NEGATIVE_DISCOVERY_KEYWORDS,
    NJU_SHORT_PROFILE_PATH_RE,
    ORG_NAME_STOPWORDS,
    PAGINATION_KEYWORDS,
    PKU_CS_PROFILE_PATH_RE,
    PROFILE_KEYWORDS,
    PROFILE_TEXT_HINTS,
    PROFILE_URL_HINTS,
    RICH_TEACHER_CARD_PATTERN,
    TSINGHUA_CS_PROFILE_PATH_RE,
    USTC_FACULTY_PROFILE_PATH_RE,
    ZJU_PERSON_REFERER,
    ZJU_PERSON_SERVER_URL,
    # --- shared utilities ---
    contains_any_keyword,
    count_keyword_hits,
    fetch_html,
    host_matches,
    is_probable_person_name,
    is_probably_asset,
    load_interest_keywords,
    looks_like_directory_page,
    maybe_json_loads,
    normalize_url,
    normalize_whitespace,
    parse_pipe_separated,
    read_csv_rows,
    safe_preview,
    same_root_domain,
    write_csv_rows,
)


# ---------------------------------------------------------------------------
# Discovery data pipeline
# ---------------------------------------------------------------------------


def _build_discovery_row(
    school: str,
    institute: str,
    query: str,
    url: str,
    title: str,
    snippet: str,
) -> dict[str, str]:
    return {
        "school": school,
        "institute": institute,
        "query": query,
        "url": url,
        "title": title,
        "snippet": snippet,
    }


def _limit_rows_per_school(rows: list[dict[str, str]], limit_per_school: int) -> list[dict[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    limited: list[dict[str, str]] = []
    for row in rows:
        key = (row.get("school", ""), row.get("institute", ""))
        current = counts.get(key, 0)
        if current >= limit_per_school:
            continue
        counts[key] = current + 1
        limited.append(row)
    return limited


def _query_templates(school: str, institute: str, search_hint: str, keywords: list[str], domain: str) -> list[str]:
    focus = search_hint or (keywords[0] if keywords else "")
    keyword_slice = keywords[:4]
    extra = " OR ".join(keyword_slice) if keyword_slice else focus
    research_terms = f"({focus} OR {extra})" if focus and extra and focus != extra else focus or extra
    org = f"{school} {institute}".strip()
    return [
        f"site:{domain} {org} {focus} 导师",
        f"site:{domain} {org} {focus} 教授",
        f"site:{domain} {org} {focus} 教师主页",
        f"site:{domain} {org} {focus} 导师主页",
        f"site:{domain} {org} {focus} 师资队伍",
        f"site:{domain} {org} {focus} 教师信息",
        f"site:{domain} {org} {research_terms} 师资",
        f"site:{domain} {org} {research_terms} 研究员",
    ]


def write_discovery_rows(path: str, rows: list[dict[str, str]]) -> None:
    write_csv_rows(path, DISCOVERY_FIELDS, rows)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def looks_like_negative_candidate(url: str, title: str, snippet: str) -> bool:
    haystack = f"{url} {title} {snippet}".lower()
    return contains_any_keyword(haystack, NEGATIVE_DISCOVERY_KEYWORDS)


def school_specific_directory_link_score(anchor_text: str, href: str, page_url: str = "") -> int:
    anchor = normalize_whitespace(anchor_text)
    parsed = urlparse(href)
    host = parsed.netloc.lower() or urlparse(page_url).netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    score = 0

    if host_matches(host, "cs.tsinghua.edu.cn") and re.search(r"/szzk/(jzgml|jcrc|jxms|xnjzjs|myxx)\.htm$", path):
        score += 10
    if host_matches(host, "air.tsinghua.edu.cn") and (
        "/airtd/" in path
        or "wbtreeid=1028" in query
        or any(token in anchor for token in ["教职员工", "研究团队", "AIR团队"])
    ):
        score += 9
    if host_matches(host, "cs.pku.edu.cn") and (
        "/szdw/" in path or any(token in anchor for token in ["师资队伍", "院士", "研究系列", "教研系列", "教学系列"])
    ):
        score += 9
    if host_matches(host, "ai.zju.edu.cn", "cs.zju.edu.cn"):
        if any(token in anchor for token in ["师资", "教师", "导师", "研究团队"]):
            score += 8
        if path.endswith("/list.htm") and any(token in anchor for token in ["学院简介", "组织架构", "领导班子", "通知公告"]):
            score -= 8
    if host_matches(host, "lamda.nju.edu.cn") and ("ch.people.ashx" in path or anchor == "People" or "教师成员" in anchor):
        score += 10
    if host_matches(host, "ai.nju.edu.cn") and path in {"/people/list.htm", "/18540/list.htm"}:
        score += 12
    if host_matches(host, "cs.nju.edu.cn") and path in {"/1651/list.htm", "/2639/list.htm", "/2640/list.htm", "/2641/list.htm", "/zzp/list.htm", "/kxkbd/list.htm"}:
        score += 12
    if host_matches(host, "faculty.ustc.edu.cn") and (
        any(token in path for token in ["xyjslb.jsp", "pyjslb.jsp", "xylbx.jsp"]) or "pagenum=" in query or "totalpage=" in query
    ):
        score += 11
    if host_matches(host, "hr.ustc.edu.cn") and "shizi.aspx" in path:
        score -= 6

    return score


def school_specific_profile_link_score(
    anchor_text: str,
    href: str,
    *,
    page_url: str = "",
    source_is_directory: bool = False,
) -> int:
    anchor = normalize_whitespace(anchor_text)
    parsed = urlparse(href)
    host = parsed.netloc.lower() or urlparse(page_url).netloc.lower()
    path = parsed.path.lower()
    score = 0

    if host_matches(host, "cs.tsinghua.edu.cn"):
        if TSINGHUA_CS_PROFILE_PATH_RE.fullmatch(path):
            score += 12
        if source_is_directory and is_probable_person_name(anchor):
            score += 6
    if host_matches(host, "air.tsinghua.edu.cn"):
        if path.endswith("/gyair/yzjj.htm") or path.endswith("/gyair/csyz.htm"):
            score += 10
        if source_is_directory and any(token in anchor for token in ["教授", "研究员", "院长"]):
            score += 5
    if host_matches(host, "cs.pku.edu.cn"):
        if PKU_CS_PROFILE_PATH_RE.fullmatch(path):
            score += 12
        if source_is_directory and (is_probable_person_name(anchor) or bool(RICH_TEACHER_CARD_PATTERN.search(anchor))):
            score += 7
    if host_matches(host, "person.zju.edu.cn"):
        if any(token in path for token in ["/personage", "/person/", "/teacher/"]):
            score += 12
        if source_is_directory and is_probable_person_name(anchor):
            score += 6
    if host_matches(host, "ai.zju.edu.cn", "cs.zju.edu.cn"):
        if path.endswith("/list.htm"):
            score -= 8
        if path.endswith("/page.htm") and anchor in GENERIC_DETAIL_ANCHORS:
            score -= 12
    if host_matches(host, "lamda.nju.edu.cn") and "ch.people.ashx" in path:
        score -= 10
    if host_matches(host, "cs.nju.edu.cn"):
        if re.search(r"/c26(39|40|41)a\d+/page\.htm$", path):
            score += 13
        if NJU_SHORT_PROFILE_PATH_RE.fullmatch(path) and path not in {"/", "/main.htm", "/index.htm"} and path.count("/") <= 2:
            score += 11
        if source_is_directory and is_probable_person_name(anchor):
            score += 5
    if host_matches(host, "ai.nju.edu.cn"):
        if re.search(r"/c18540a\d+/(?:page|pagem)\.htm$", path):
            score += 13
        if NJU_SHORT_PROFILE_PATH_RE.fullmatch(path) and path not in {"/", "/main.htm", "/people/list.htm"} and path.count("/") <= 2:
            score += 10
        if path.endswith("/page.htm") and anchor in GENERIC_DETAIL_ANCHORS:
            score -= 8
    if host_matches(host, "faculty.ustc.edu.cn"):
        if USTC_FACULTY_PROFILE_PATH_RE.fullmatch(path):
            score += 14
        if re.search(r"[一-鿿]{2,16}\s+[一-鿿]{2,4}$", anchor):
            score += 7
    if host_matches(host, "hr.ustc.edu.cn") and "shizi.aspx" in path:
        score -= 10

    return score


def school_specific_candidate_score(url: str, title: str, snippet: str, query: str = "") -> int:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    score = school_specific_profile_link_score(
        title,
        url,
        page_url=url,
        source_is_directory=query.startswith("directory-crawl::"),
    )

    if host_matches(host, "ai.zju.edu.cn"):
        if title.strip() in GENERIC_DETAIL_ANCHORS or title.strip() in {"学院简介", "组织架构", "领导班子", "通知公告"}:
            score -= 12
        if path.endswith("/list.htm"):
            score -= 8
    if host_matches(host, "ai.nju.edu.cn") and "/c18541a" in path:
        score -= 12
    if host_matches(host, "hr.ustc.edu.cn") and "shizi.aspx" in path:
        score -= 12
    if host_matches(host, "faculty.ustc.edu.cn") and USTC_FACULTY_PROFILE_PATH_RE.fullmatch(path):
        score += 10

    return score


def discovery_candidate_score(
    *,
    url: str,
    title: str,
    snippet: str,
    search_hint: str,
    keywords: list[str],
    query: str = "",
) -> int:
    haystack = normalize_whitespace(f"{title} {snippet} {url}")
    haystack_lower = haystack.lower()
    path = urlparse(url).path.lower()
    href_lower = url.lower()
    score = 0

    if contains_any_keyword(haystack_lower, PROFILE_KEYWORDS):
        score += 6
    if is_probable_person_name(title):
        score += 8
    if contains_any_keyword(path, PROFILE_URL_HINTS):
        score += 7
    if contains_any_keyword(href_lower, PROFILE_URL_HINTS):
        score += 4
    if contains_any_keyword(haystack_lower, DIRECTORY_KEYWORDS):
        score += 4
    if contains_any_keyword(path, DIRECTORY_URL_HINTS):
        score += 3
    if contains_any_keyword(href_lower, DIRECTORY_URL_HINTS):
        score += 2
    if contains_any_keyword(haystack_lower, PROFILE_TEXT_HINTS):
        score += 5
    if query.startswith("directory-crawl::") and is_probable_person_name(title):
        score += 6
    if query.startswith("directory-crawl::") and "/info/" in path:
        score += 4
    score += school_specific_candidate_score(url, title, snippet, query)

    if search_hint and search_hint.lower() in haystack_lower:
        score += 4
    score += min(8, count_keyword_hits(haystack_lower, keywords[:8]) * 2)

    if looks_like_negative_candidate(url, title, snippet):
        score -= 12
    if contains_any_keyword(path, GENERIC_URL_TOKENS):
        score -= 6

    return score


# ---------------------------------------------------------------------------
# URL validation & post-processing
# ---------------------------------------------------------------------------


def validate_discovery_url(url: str, config: AppConfig) -> tuple[bool, str, str]:
    try:
        final_url, _, title, text = fetch_html(url, config)
    except Exception:
        return False, url, ""
    preview = safe_preview(f"{title} {text}", 240)
    return True, final_url, preview


def postprocess_discovery_rows(
    rows: list[dict[str, str]],
    *,
    search_hint: str,
    keywords: list[str],
    limit: int,
    config: AppConfig | None = None,
    verify_live_urls: bool = False,
) -> list[dict[str, str]]:
    ranked: list[tuple[int, dict[str, str]]] = []
    seen_urls: set[str] = set()
    for row in rows:
        url = normalize_url(row.get("url", "").strip())
        if not url or url in seen_urls:
            continue
        if urlparse(url).path.lower().endswith("/list.htm"):
            continue
        seen_urls.add(url)
        title = str(row.get("title", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        score = discovery_candidate_score(
            url=url,
            title=title,
            snippet=snippet,
            search_hint=search_hint,
            keywords=keywords,
            query=str(row.get("query", "")),
        )
        if score < 4:
            continue
        cleaned = dict(row)
        cleaned["url"] = url
        ranked.append((score, cleaned))

    ranked.sort(
        key=lambda item: (
            -item[0],
            len(item[1].get("title", "")),
            item[1].get("url", ""),
        )
    )

    selected: list[dict[str, str]] = []
    for _, row in ranked:
        candidate = dict(row)
        if verify_live_urls and config is not None:
            ok, final_url, preview = validate_discovery_url(candidate["url"], config)
            if not ok:
                continue
            candidate["url"] = final_url
            if preview and not candidate.get("snippet"):
                candidate["snippet"] = preview
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


# ---------------------------------------------------------------------------
# Directory crawl helpers
# ---------------------------------------------------------------------------


def looks_like_pagination_link(anchor_text: str, href: str) -> bool:
    haystack = f"{anchor_text} {href}".lower()
    return contains_any_keyword(haystack, PAGINATION_KEYWORDS)


def looks_like_directory_link(anchor_text: str, href: str, page_url: str = "") -> bool:
    haystack = f"{anchor_text} {href}".lower()
    if looks_like_negative_candidate(href, anchor_text, ""):
        return False
    specific_score = school_specific_directory_link_score(anchor_text, href, page_url)
    if specific_score >= 6:
        return True
    if specific_score <= -6:
        return False
    return contains_any_keyword(haystack, DIRECTORY_KEYWORDS + DIRECTORY_URL_HINTS) or looks_like_pagination_link(anchor_text, href)


def looks_like_profile_link(anchor_text: str, href: str, source_is_directory: bool, page_url: str = "") -> bool:
    anchor = normalize_whitespace(anchor_text)
    path = urlparse(href).path.lower()
    href_lower = href.lower()
    if not anchor and not path:
        return False
    person_name_like = is_probable_person_name(anchor)
    title_like = contains_any_keyword(anchor.lower(), [item.lower() for item in PROFILE_KEYWORDS] + PROFILE_TEXT_HINTS)
    rich_teacher_card = bool(RICH_TEACHER_CARD_PATTERN.search(anchor))
    path_like = contains_any_keyword(href_lower, CANDIDATE_DIRECTORY_PATH_TOKENS + PROFILE_URL_HINTS)
    directory_like = contains_any_keyword(anchor, DIRECTORY_KEYWORDS) or contains_any_keyword(href_lower, DIRECTORY_URL_HINTS)
    generic_anchor = any(keyword in anchor for keyword in GENERIC_ANCHOR_KEYWORDS)
    generic_path = contains_any_keyword(href_lower, GENERIC_URL_TOKENS)
    specific_score = school_specific_profile_link_score(
        anchor,
        href,
        page_url=page_url,
        source_is_directory=source_is_directory,
    )
    if specific_score >= 8:
        return True
    if specific_score <= -8:
        return False
    if path.endswith("/list.htm") and not person_name_like and not rich_teacher_card:
        return False
    if generic_anchor:
        return False
    if generic_path and not path_like:
        return False
    if directory_like and not person_name_like and not title_like:
        return False
    if len(anchor) > 64 and not path_like:
        return False
    if source_is_directory and (person_name_like or rich_teacher_card):
        return True
    return title_like or path_like or rich_teacher_card


def extract_same_domain_links(base_url: str, soup: BeautifulSoup, domain: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if not href or is_probably_asset(href):
            continue
        host = urlparse(href).netloc.lower()
        if not same_root_domain(host, domain):
            continue
        text = normalize_whitespace(anchor.get_text(" ", strip=True))
        if not text:
            text = normalize_whitespace(
                str(anchor.get("title") or anchor.get("aria-label") or anchor.get("alt") or "")
            )
        item = (href, text)
        if item in seen:
            continue
        seen.add(item)
        links.append(item)
    return links


def default_entry_urls(domains: list[str]) -> list[str]:
    urls: list[str] = []
    for domain in domains:
        urls.append(f"https://{domain}/")
        for path in COMMON_DIRECTORY_PATHS[1:]:
            urls.append(f"https://{domain}{path}")
    return urls


# ---------------------------------------------------------------------------
# ZJU person API
# ---------------------------------------------------------------------------


def zju_person_api_sign(path: str, params: dict[str, Any], timestamp_ms: int, secret: str) -> str:
    payload = secret + path
    for key in sorted(params):
        value = params[key]
        if value in ("", None):
            continue
        payload += f"{key}{value}"
    payload += f"{timestamp_ms} {secret}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def zju_person_api_get(path: str, params: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    if not config.zju_person_enabled:
        raise ValueError("Optional faculty-directory API credentials are not configured.")
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    signed_params = dict(params)
    signed_params.setdefault("lang", "cn")
    response = requests.get(
        f"{ZJU_PERSON_SERVER_URL}{path}",
        params=signed_params,
        headers={
            "User-Agent": config.user_agent,
            "Referer": ZJU_PERSON_REFERER,
            "appKey": config.zju_person_app_key,
            "sign": zju_person_api_sign(path, signed_params, timestamp_ms, config.zju_person_secret),
            "timestamp": str(timestamp_ms),
        },
        timeout=config.http_timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def fetch_zju_person_directory_rows(
    config: AppConfig,
    school: str,
    institute: str,
    limit: int,
) -> list[dict[str, str]]:
    if not config.zju_person_enabled:
        return []
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    college_ids = [value.strip() for value in config.zju_person_college_ids.split(",") if value.strip()] or [""]
    for college_id in college_ids:
        page_number = 1
        while len(rows) < limit:
            params: dict[str, Any] = {
                "pageNumber": str(page_number),
                "pageSize": str(min(limit * 2, 60)),
            }
            if college_id:
                params["collegeId"] = college_id
            try:
                data = zju_person_api_get(
                    "/api/profile/list",
                    params,
                    config,
                )
            except Exception:
                break
            items = data.get("data") or data.get("list") or []
            if isinstance(items, dict):
                items = items.get("records") or items.get("items") or []
            if not isinstance(items, list) or not items:
                break
            for item in items:
                person_id = str(item.get("id") or item.get("userId") or "")
                name = str(item.get("name") or item.get("userName") or "").strip()
                if not person_id or person_id in seen_ids:
                    continue
                seen_ids.add(person_id)
                profile_url = f"https://person.zju.edu.cn/personage/{person_id}"
                rows.append(
                    _build_discovery_row(
                        school,
                        institute,
                        f"directory-crawl::person.zju.edu.cn",
                        profile_url,
                        name or profile_url,
                        "",
                    )
                )
                if len(rows) >= limit:
                    break
            page_number += 1
    return rows


# ---------------------------------------------------------------------------
# OpenAI / BigModel search clients
# ---------------------------------------------------------------------------


def extract_response_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    texts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(content["text"])
    return "\n".join(texts).strip()


class OpenAISearchClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.openai_search_api_key}",
            "Content-Type": "application/json",
        }

    def _chat_search(self, prompt: str) -> str:
        response = requests.post(
            f"{self.config.openai_search_base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.config.openai_search_model,
                "web_search_options": {},
                "messages": [
                    {"role": "system", "content": "Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
            },
            timeout=self.config.http_timeout_seconds * 3,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    def _responses_search(self, prompt: str, allowed_domains: list[str]) -> str:
        response = requests.post(
            f"{self.config.openai_search_base_url}/responses",
            headers=self._headers(),
            json={
                "model": self.config.openai_search_model,
                "tools": [
                    {
                        "type": "web_search",
                        "filters": {"allowed_domains": allowed_domains},
                    }
                ],
                "tool_choice": "auto",
                "input": prompt,
            },
            timeout=self.config.http_timeout_seconds * 3,
        )
        response.raise_for_status()
        return extract_response_output_text(response.json())

    def search_faculty_urls_for_domain(
        self,
        school: str,
        institute: str,
        domain: str,
        search_hint: str,
        keywords: list[str],
        limit_per_school: int,
    ) -> list[dict[str, str]]:
        prompt = f"""
Find official faculty profile pages for professors in {school} {institute}.
Research focus should be related to: {search_hint or "the applicant-provided interests, if any; otherwise do not restrict the discipline"}.
Interest keywords: {keywords[:8]}.

Hard rules:
1. Return only pages hosted under {domain}
2. Prefer faculty profile pages, faculty directory pages, lab member pages, or supervisor intro pages
3. Avoid news pages, admissions notices, encyclopedia pages, and generic homepages
4. Only include URLs that explicitly appear in search results. Do not fabricate URLs.
5. Prefer pages whose title or snippet clearly mention a person, faculty, professor, teacher, member, lab, or supervisor
6. Return strict JSON array only
7. Each item must contain: url, title, snippet
8. Return at most {limit_per_school * 2} items
        """.strip()

        if "search-preview" in self.config.openai_search_model or self.config.openai_search_model == "gpt-5-search-api":
            raw = self._chat_search(prompt)
        else:
            raw = self._responses_search(prompt, [domain])
        data = maybe_json_loads(raw)
        rows: list[dict[str, str]] = []
        if not isinstance(data, list):
            return rows
        seen_urls: set[str] = set()
        for item in data:
            url = normalize_url(str(item.get("url", "")).strip())
            if not url or url in seen_urls:
                continue
            host = urlparse(url).netloc.lower()
            if not same_root_domain(host, domain):
                continue
            seen_urls.add(url)
            rows.append(
                _build_discovery_row(
                    school,
                    institute,
                    f"openai-search::{domain}",
                    url,
                    str(item.get("title", "")).strip(),
                    str(item.get("snippet", "")).strip(),
                )
            )
            if len(rows) >= limit_per_school * 2:
                break
        return postprocess_discovery_rows(
            rows,
            search_hint=search_hint,
            keywords=keywords,
            limit=limit_per_school,
            config=self.config,
            verify_live_urls=True,
        )


class BigModelSearchClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.bigmodel_search_api_key}",
            "Content-Type": "application/json",
        }

    def search_faculty_urls_for_domain(
        self,
        school: str,
        institute: str,
        domain: str,
        search_hint: str,
        keywords: list[str],
        limit_per_school: int,
    ) -> list[dict[str, str]]:
        interest_keywords = "、".join(keywords[:8]) if keywords else "未设置，不限定学科"
        prompt = f"""
请根据联网搜索结果，返回 {school}{institute} 中与目标方向相关的导师主页、教师详情页、实验室成员页或师资页。

要求：
1. 只返回 host 属于 {domain} 的页面
2. 优先返回导师主页、教师详情页、实验室成员页、师资页
3. 排除新闻、公告、招生通知、百科、普通首页、无关栏目页
4. 只能返回搜索结果里真实出现过的 URL，禁止编造链接
5. 页面标题或摘要里最好能体现"导师 / 教授 / 教师 / 研究员 / 成员 / 实验室 / 师资"等线索
6. 关注方向：{search_hint or "未设置，不限定学科"}；兴趣关键词：{interest_keywords}
7. 严格输出 JSON 数组
8. 每项字段必须是 url, title, snippet
9. 最多返回 {limit_per_school * 2} 条
        """.strip()

        response = requests.post(
            f"{self.config.bigmodel_search_base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.config.bigmodel_search_model,
                "messages": [
                    {"role": "system", "content": "你是严谨的搜索助手。只输出合法 JSON，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                "tools": [
                    {
                        "type": "web_search",
                        "web_search": {
                            "enable": True,
                            "search_engine": self.config.bigmodel_search_engine,
                            "search_result": True,
                            "count": max(5, min(limit_per_school * 3, 15)),
                            "search_domain_filter": domain,
                            "search_recency_filter": "noLimit",
                            "content_size": "high",
                        },
                    }
                ],
                "tool_choice": "auto",
                "stream": False,
            },
            timeout=self.config.http_timeout_seconds * 6,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        data = maybe_json_loads(content)
        rows: list[dict[str, str]] = []
        if not isinstance(data, list):
            return rows
        seen_urls: set[str] = set()
        for item in data:
            url = normalize_url(str(item.get("url", "")).strip())
            if not url or url in seen_urls:
                continue
            host = urlparse(url).netloc.lower()
            if not same_root_domain(host, domain):
                continue
            seen_urls.add(url)
            rows.append(
                _build_discovery_row(
                    school,
                    institute,
                    f"bigmodel-search::{domain}",
                    url,
                    str(item.get("title", "")).strip(),
                    str(item.get("snippet", "")).strip(),
                )
            )
            if len(rows) >= limit_per_school * 2:
                break
        return postprocess_discovery_rows(
            rows,
            search_hint=search_hint,
            keywords=keywords,
            limit=limit_per_school,
            config=self.config,
            verify_live_urls=True,
        )


# ---------------------------------------------------------------------------
# Four discovery backends
# ---------------------------------------------------------------------------


def discover_urls_via_ddg(
    targets_path: str,
    interests_path: str,
    limit_per_school: int = 20,
) -> list[dict[str, str]]:
    targets = read_csv_rows(targets_path)
    keywords = load_interest_keywords(interests_path)
    seen_urls: set[str] = set()
    rows: list[dict[str, str]] = []
    with DDGS() as ddgs:
        for target in targets:
            school = target.get("school", "").strip()
            institute = target.get("institute", "").strip()
            search_hint = target.get("search_hint", "").strip()
            domains = parse_pipe_separated(target.get("domains"))
            if not domains:
                print(f"[SKIP] {school} missing official domains in targets CSV")
                continue
            for domain in domains:
                count = 0
                domain_rows: list[dict[str, str]] = []
                for query in _query_templates(school, institute, search_hint, keywords, domain):
                    for result in ddgs.text(query, max_results=max(limit_per_school * 3, 15)):
                        url = normalize_url(result.get("href", "").strip())
                        if not url or url in seen_urls:
                            continue
                        host = urlparse(url).netloc.lower()
                        if not same_root_domain(host, domain):
                            continue
                        seen_urls.add(url)
                        domain_rows.append(
                            _build_discovery_row(
                                school,
                                institute,
                                query,
                                url,
                                result.get("title", "").strip(),
                                result.get("body", "").strip(),
                            )
                        )
                        count += 1
                        if count >= max(limit_per_school * 3, 12):
                            break
                    if count >= max(limit_per_school * 3, 12):
                        break
                rows.extend(
                    postprocess_discovery_rows(
                        domain_rows,
                        search_hint=search_hint,
                        keywords=keywords,
                        limit=limit_per_school,
                        config=None,
                        verify_live_urls=False,
                    )
                )
    return _limit_rows_per_school(rows, limit_per_school)


def discover_urls_via_openai_search(
    config: AppConfig,
    targets_path: str,
    interests_path: str,
    limit_per_school: int = 20,
) -> list[dict[str, str]]:
    targets = read_csv_rows(targets_path)
    keywords = load_interest_keywords(interests_path)
    client = OpenAISearchClient(config)
    all_rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for target in targets:
        school = target.get("school", "").strip()
        institute = target.get("institute", "").strip()
        search_hint = target.get("search_hint", "").strip()
        domains = parse_pipe_separated(target.get("domains"))
        if not domains:
            print(f"[SKIP] {school} missing official domains in targets CSV")
            continue
        count = 0
        for domain in domains:
            try:
                rows = client.search_faculty_urls_for_domain(
                    school=school,
                    institute=institute,
                    domain=domain,
                    search_hint=search_hint,
                    keywords=keywords,
                    limit_per_school=limit_per_school,
                )
            except Exception as exc:
                print(f"[WARN] OpenAI search failed for {school} {domain}: {exc}")
                continue
            for row in rows:
                if row["url"] in seen_urls:
                    continue
                seen_urls.add(row["url"])
                all_rows.append(row)
                count += 1
                if count >= limit_per_school:
                    break
            if count >= limit_per_school:
                break
    return _limit_rows_per_school(all_rows, limit_per_school)


def discover_urls_via_bigmodel_search(
    config: AppConfig,
    targets_path: str,
    interests_path: str,
    limit_per_school: int = 20,
) -> list[dict[str, str]]:
    targets = read_csv_rows(targets_path)
    keywords = load_interest_keywords(interests_path)
    client = BigModelSearchClient(config)
    all_rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for target in targets:
        school = target.get("school", "").strip()
        institute = target.get("institute", "").strip()
        search_hint = target.get("search_hint", "").strip()
        domains = parse_pipe_separated(target.get("domains"))
        if not domains:
            print(f"[SKIP] {school} missing official domains in targets CSV")
            continue
        count = 0
        for domain in domains:
            try:
                rows = client.search_faculty_urls_for_domain(
                    school=school,
                    institute=institute,
                    domain=domain,
                    search_hint=search_hint,
                    keywords=keywords,
                    limit_per_school=limit_per_school,
                )
            except Exception as exc:
                print(f"[WARN] BigModel search failed for {school} {domain}: {exc}")
                continue
            for row in rows:
                if row["url"] in seen_urls:
                    continue
                seen_urls.add(row["url"])
                all_rows.append(row)
                count += 1
                if count >= limit_per_school:
                    break
            if count >= limit_per_school:
                break
    return _limit_rows_per_school(all_rows, limit_per_school)


def discover_urls_via_directory_crawl(
    config: AppConfig,
    targets_path: str,
    interests_path: str = "data/interests.txt",
    limit_per_school: int = 20,
    max_pages_per_domain: int = 24,
    max_depth: int = 2,
) -> list[dict[str, str]]:
    targets = read_csv_rows(targets_path)
    keywords = load_interest_keywords(interests_path)
    all_rows: list[dict[str, str]] = []
    global_seen_urls: set[str] = set()
    for target in targets:
        school = target.get("school", "").strip()
        institute = target.get("institute", "").strip()
        search_hint = target.get("search_hint", "").strip()
        domains = parse_pipe_separated(target.get("domains"))
        entry_urls = parse_pipe_separated(target.get("entry_urls"))
        if not domains:
            print(f"[SKIP] {school} missing official domains in targets CSV")
            continue
        per_school_count = 0
        raw_candidate_limit = max(limit_per_school * 6, 18)
        for domain in domains:
            queue: deque[tuple[str, int]] = deque()
            visited: set[str] = set()
            queued: set[str] = set()
            domain_rows: list[dict[str, str]] = []
            candidate_urls: set[str] = set()

            if domain == "person.zju.edu.cn" and config.zju_person_enabled:
                try:
                    domain_rows = fetch_zju_person_directory_rows(
                        config,
                        school=school,
                        institute=institute,
                        limit=raw_candidate_limit,
                    )
                except Exception as exc:
                    print(f"[WARN] ZJU person API discovery failed for {school} {domain}: {exc}")
                    domain_rows = []
                filtered_rows = postprocess_discovery_rows(
                    domain_rows,
                    search_hint=search_hint,
                    keywords=keywords,
                    limit=limit_per_school,
                    config=None,
                    verify_live_urls=False,
                )
                for row in filtered_rows:
                    if row["url"] in global_seen_urls:
                        continue
                    global_seen_urls.add(row["url"])
                    all_rows.append(row)
                    per_school_count += 1
                    if per_school_count >= limit_per_school:
                        break
                if per_school_count >= limit_per_school:
                    break
                # An unavailable optional API falls back to the normal HTML crawl.

            seed_urls = [url for url in entry_urls if same_root_domain(urlparse(url).netloc.lower(), domain)]
            if not seed_urls:
                seed_urls = default_entry_urls([domain])

            for seed in seed_urls:
                normalized = normalize_url(seed)
                if normalized and normalized not in queued:
                    queue.append((normalized, 0))
                    queued.add(normalized)

            crawled_pages = 0
            while queue and crawled_pages < max_pages_per_domain and len(domain_rows) < raw_candidate_limit:
                current_url, depth = queue.popleft()
                if current_url in visited:
                    continue
                visited.add(current_url)
                try:
                    final_url, soup, title, text = fetch_html(current_url, config)
                except Exception:
                    continue
                crawled_pages += 1
                page_is_directory = looks_like_directory_page(final_url, title, text)
                if (
                    not page_is_directory
                    and not looks_like_negative_candidate(final_url, title, text[:400])
                    and (
                        contains_any_keyword(f"{title} {text[:500]}", PROFILE_KEYWORDS + ["个人主页", "教师主页", "导师主页", "研究员"])
                        or bool(re.search(r"[一-鿿]{2,4}\s*(?:教授|副教授|研究员)", title))
                    )
                    and discovery_candidate_score(
                        url=final_url,
                        title=title,
                        snippet=text[:600],
                        search_hint=search_hint,
                        keywords=keywords,
                    )
                    >= 8
                    and final_url not in candidate_urls
                ):
                    candidate_urls.add(final_url)
                    domain_rows.append(
                        _build_discovery_row(
                            school,
                            institute,
                            f"directory-crawl::{domain}",
                            final_url,
                            title or final_url,
                            safe_preview(text, 180),
                        )
                    )
                    if len(domain_rows) >= raw_candidate_limit:
                        break
                links = extract_same_domain_links(final_url, soup, domain)
                for href, anchor_text in links:
                    if looks_like_profile_link(anchor_text, href, page_is_directory, page_url=final_url) and href not in candidate_urls:
                        candidate_urls.add(href)
                        domain_rows.append(
                            _build_discovery_row(
                                school,
                                institute,
                                f"directory-crawl::{domain}",
                                href,
                                anchor_text or title,
                                safe_preview(f"Discovered from {title or final_url}", 180),
                            )
                        )
                        if len(domain_rows) >= raw_candidate_limit:
                            break
                    if (
                        depth < max_depth
                        and (
                            looks_like_directory_link(anchor_text, href, page_url=final_url)
                            or contains_any_keyword(href.lower(), DIRECTORY_URL_HINTS)
                            or looks_like_pagination_link(anchor_text, href)
                        )
                        and href not in queued
                    ):
                        queue.append((href, depth + 1))
                        queued.add(href)
                if len(domain_rows) >= raw_candidate_limit:
                    break

            filtered_rows = postprocess_discovery_rows(
                domain_rows,
                search_hint=search_hint,
                keywords=keywords,
                limit=limit_per_school,
                config=config if domain in {"lamda.nju.edu.cn", "cs.nju.edu.cn", "ai.nju.edu.cn"} else None,
                verify_live_urls=domain in {"lamda.nju.edu.cn", "cs.nju.edu.cn", "ai.nju.edu.cn"},
            )
            for row in filtered_rows:
                if row["url"] in global_seen_urls:
                    continue
                global_seen_urls.add(row["url"])
                all_rows.append(row)
                per_school_count += 1
                if per_school_count >= limit_per_school:
                    break
            if per_school_count >= limit_per_school:
                break
    return _limit_rows_per_school(all_rows, limit_per_school)
