from __future__ import annotations

import csv
import json
import posixpath
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .atomic_io import atomic_write_csv_rows
from .config import AppConfig
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


DISCOVERY_FIELDS = ["school", "institute", "query", "url", "title", "snippet"]
DIRECTORY_KEYWORDS = [
    "师资",
    "导师",
    "教师",
    "教授",
    "研究员",
    "博导",
    "faculty",
    "people",
    "staff",
    "member",
    "members",
    "team",
]
PROFILE_KEYWORDS = [
    "教授",
    "副教授",
    "助理教授",
    "研究员",
    "副研究员",
    "导师",
    "博导",
    "faculty",
    "professor",
    "researcher",
]
CANDIDATE_DIRECTORY_PATH_TOKENS = ["teacher", "teachers", "faculty", "people", "staff", "member", "members"]
GENERIC_ANCHOR_KEYWORDS = ["关于", "概况", "新闻", "通知", "公告", "常见问题", "招生", "报名", "活动", "走进", "首页", "登录", "英文版", "查看详情", "查看更多", "更多"]
GENERIC_URL_TOKENS = ["news", "notice", "exam", "faq", "xygk", "overview", "about", "article"]
ORG_NAME_STOPWORDS = ["大学", "学院", "研究院", "研究所", "实验室", "中心", "学校"]
NEGATIVE_DISCOVERY_KEYWORDS = [
    "新闻",
    "通知",
    "公告",
    "招生",
    "学生",
    "研究生招生",
    "就业",
    "党群",
    "党建",
    "活动",
    "院士",
    "热门",
    "获奖",
    "百科",
    "院况简介",
    "教育简介",
    "学院简介",
    "团队主页",
    "实验室主页",
    "国内合作",
    "强基计划",
    "news",
    "notice",
    "student",
    "admissions",
    "admission",
    "zsxx",
    "yjszs",
    "admission",
    "event",
    "article",
    "cooperation",
    "program",
]
PROFILE_URL_HINTS = [
    "teacher",
    "teachers",
    "faculty",
    "people",
    "member",
    "members",
    "staff",
    "detail",
    "profile",
    "homepage",
    "home",
    "show",
    "mentor",
    "supervisor",
    "leader_detail",
    "info/",
    "profileid",
    "teacherid",
    "jsnr",
]
DIRECTORY_URL_HINTS = [
    "faculty",
    "teacher",
    "teachers",
    "people",
    "staff",
    "members",
    "team",
    "mentor",
    "supervisor",
    "szdw",
    "jsml",
    "yjtd",
    "pyjslb",
    "xyjslb",
    "collegeteacherlist",
    "pinyinteacherlist",
]
COMMON_CHINESE_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程"
    "嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧"
    "隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶"
    "幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴鬱胥能苍双闻"
    "莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温"
    "别庄晏柴瞿阎充慕连茹习艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国"
    "文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾沙"
    "乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
PAGINATION_KEYWORDS = ["下一页", "上一页", "尾页", "首页", "next", "prev", "page", "pagenum", "totalpage"]
COMMON_DIRECTORY_PATHS = [
    "/",
    "/people",
    "/people/",
    "/people/list.htm",
    "/faculty",
    "/faculty/",
    "/faculty/list.htm",
    "/teachers",
    "/teachers/",
    "/teachers/list.htm",
    "/teacher",
    "/teacher/",
    "/teacher/list.htm",
    "/staff",
    "/members",
    "/team",
    "/mentor",
    "/supervisor",
    "/szdw",
    "/szdw/",
    "/szdw/list.htm",
    "/jsml",
    "/jsml/",
    "/jsml/list.htm",
]
ASSET_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
}
DIRECTORY_PAGE_NEGATIVE_HINTS = ["招生", "admission", "notice", "通知", "公告"]
PROFILE_TEXT_HINTS = ["个人主页", "主页", "简介", "导师主页", "教师主页", "教授"]
GENERIC_DETAIL_ANCHORS = {"查看详情", "查看更多", "更多"}
RICH_TEACHER_CARD_PATTERN = re.compile(
    r"(教授|副教授|助理教授|研究员|副研究员|导师|博导|邮箱|email|研究方向)",
    re.I,
)
TSINGHUA_CS_PROFILE_PATH_RE = re.compile(r"^/info/111\d/\d+\.htm$")
PKU_CS_PROFILE_PATH_RE = re.compile(r"^/info/1012/\d+\.htm$")
USTC_FACULTY_PROFILE_PATH_RE = re.compile(r"^/[A-Za-z0-9._-]+/(?:zh_CN|en)/index\.htm$")
NJU_SHORT_PROFILE_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+/?$")
ZJU_PERSON_SERVER_URL = "https://person.zju.edu.cn/server"
ZJU_PERSON_REFERER = "https://person.zju.edu.cn/index/"


def load_interest_keywords(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def read_csv_rows(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: str, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    atomic_write_csv_rows(path, fieldnames, rows)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def maybe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def safe_preview(text: str, limit: int = 240) -> str:
    return normalize_whitespace(text)[:limit]


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    haystack = text.lower()
    return any(keyword.lower() in haystack for keyword in keywords if keyword)


def count_keyword_hits(text: str, keywords: list[str]) -> int:
    haystack = text.lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in haystack)


def is_probable_person_name(text: str) -> bool:
    candidate = normalize_whitespace(text)
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", candidate):
        return False
    if any(token in candidate for token in ORG_NAME_STOPWORDS + GENERIC_ANCHOR_KEYWORDS):
        return False
    if candidate[0] not in COMMON_CHINESE_SURNAMES:
        return False
    return True


def parse_pipe_separated(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split("|") if item.strip()]


def root_domain(host: str) -> str:
    labels = [part for part in host.lower().split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    if labels[-1] == "cn" and labels[-2] in {"edu", "ac", "org", "com", "gov"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_root_domain(host: str, domain: str) -> bool:
    return bool(host and domain and root_domain(host) == root_domain(domain))


def host_matches(host: str, *domains: str) -> bool:
    host = host.lower().strip()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains if domain)


def school_specific_directory_page_score(url: str, title: str, text: str) -> int:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    title_text = normalize_whitespace(f"{title} {text[:1200]}")
    score = 0

    if host_matches(host, "cs.tsinghua.edu.cn") and re.search(r"/szzk/(jzgml|jcrc|jxms|xnjzjs|myxx)\.htm$", path):
        score += 10
    if host_matches(host, "air.tsinghua.edu.cn") and (
        "/airtd/" in path
        or "wbtreeid=1028" in query
        or any(token in title_text for token in ["教职员工", "研究团队", "AIR团队"])
    ):
        score += 9
    if host_matches(host, "cs.pku.edu.cn") and (
        "/szdw/" in path or any(token in title_text for token in ["师资队伍", "研究系列", "教研系列", "院士"])
    ):
        score += 9
    if host_matches(host, "ai.zju.edu.cn", "cs.zju.edu.cn"):
        if any(token in title_text for token in ["师资", "教师", "导师", "研究团队"]):
            score += 8
        if path.endswith("/list.htm") and any(token in title_text for token in ["学院简介", "组织架构", "领导班子", "通知公告"]):
            score -= 8
    if host_matches(host, "lamda.nju.edu.cn") and (
        "ch.people.ashx" in path or "教师成员" in title_text or "people" in title_text.lower()
    ):
        score += 10
    if host_matches(host, "ai.nju.edu.cn") and path in {"/people/list.htm", "/18540/list.htm"}:
        score += 12
    if host_matches(host, "cs.nju.edu.cn") and path in {"/1651/list.htm", "/2639/list.htm", "/2640/list.htm", "/2641/list.htm", "/zzp/list.htm", "/kxkbd/list.htm"}:
        score += 12
    if host_matches(host, "cs.nju.edu.cn", "ai.nju.edu.cn") and any(token in title_text for token in ["师资", "教师", "导师", "教授"]):
        score += 6
    if host_matches(host, "faculty.ustc.edu.cn") and (
        any(token in path for token in ["xyjslb.jsp", "pyjslb.jsp", "xylbx.jsp"])
        or any(token in title_text for token in ["教师列表", "院系单位"])
    ):
        score += 11
    if host_matches(host, "hr.ustc.edu.cn") and "shizi.aspx" in path:
        score -= 8

    return score


def email_matches_source_domain(email_address: str, source_domain: str) -> bool:
    if not email_address or not source_domain or "@" not in email_address:
        return False
    email_domain = email_address.split("@", 1)[1].lower()
    return same_root_domain(email_domain, source_domain)


def normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    normalized_path = posixpath.normpath(parsed.path or "/")
    if parsed.path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    normalized = parsed._replace(path=normalized_path, fragment="")
    return urlunparse(normalized)


def is_probably_asset(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in ASSET_SUFFIXES


def response_text_with_best_effort_encoding(response: requests.Response) -> str:
    encoding = (response.encoding or "").lower()
    if not encoding or encoding == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def decode_text_from_bytes_best_effort(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="ignore")


def should_use_curl_fallback(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host_matches(host, "ai.nju.edu.cn", "cs.nju.edu.cn", "lamda.nju.edu.cn")


def fetch_text_via_curl(url: str, config: AppConfig) -> tuple[str, str, str]:
    curl_bin = shutil.which("curl.exe") or shutil.which("curl")
    if not curl_bin:
        raise RuntimeError("curl is not available for fallback fetching")

    marker = b"\n__AOTOSOCIAL_CURL_META__"
    command = [
        curl_bin,
        "-k",
        "-L",
        "-sS",
        "-A",
        config.user_agent,
        "--connect-timeout",
        str(config.http_timeout_seconds),
        "--max-time",
        str(max(config.http_timeout_seconds * 3, 30)),
        "-o",
        "-",
        "-w",
        marker.decode("ascii") + "%{content_type}||%{url_effective}",
        url,
    ]
    completed = subprocess.run(command, capture_output=True, check=True)
    stdout = completed.stdout
    marker_index = stdout.rfind(marker)
    if marker_index == -1:
        return url, "", decode_text_from_bytes_best_effort(stdout)

    body = stdout[:marker_index]
    meta = stdout[marker_index + len(marker) :].decode("utf-8", errors="ignore")
    content_type, _, final_url = meta.partition("||")
    return final_url.strip() or url, content_type.strip(), decode_text_from_bytes_best_effort(body)


def fetch_text_with_fallback(url: str, config: AppConfig) -> tuple[str, str, str]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": config.user_agent},
            timeout=config.http_timeout_seconds,
        )
        response.raise_for_status()
        return str(response.url), response.headers.get("Content-Type", ""), response_text_with_best_effort_encoding(response)
    except requests.RequestException:
        if not should_use_curl_fallback(url):
            raise
        return fetch_text_via_curl(url, config)


def fetch_page_content(url: str, config: AppConfig) -> dict[str, str]:
    final_url, _, html = fetch_text_with_fallback(url, config)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = " | ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2"])[:5])
    text = normalize_whitespace(soup.get_text(" ", strip=True))
    return {
        "url": final_url,
        "title": title,
        "headings": headings,
        "text": text,
    }


def fetch_html(url: str, config: AppConfig) -> tuple[str, BeautifulSoup, str, str]:
    final_url, content_type, html = fetch_text_with_fallback(url, config)
    if content_type and "html" not in content_type.lower() and "<html" not in html.lower():
        raise ValueError(f"non-html content: {content_type}")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = normalize_whitespace(soup.get_text(" ", strip=True))
    return final_url, soup, title, text


def looks_like_multi_person_page(url: str, title: str, text: str) -> bool:
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
    title_hits = re.findall(r"(教授|副教授|助理教授|研究员|副研究员|博导|导师)", text)
    return looks_like_directory_page(url, title, text) and (len(emails) >= 2 or len(title_hits) >= 4)


class LLMClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        payload = {
            "model": self.config.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if self.config.llm_provider.lower() == "openai" and (
            "search-preview" in self.config.llm_model or self.config.llm_model == "gpt-5-search-api"
        ):
            payload["web_search_options"] = {}
        response = requests.post(
            f"{self.config.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.config.http_timeout_seconds * 3,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def extract_professor(
        self,
        content: dict[str, str],
        school: str,
        institute: str,
        keywords: list[str],
    ) -> dict[str, Any]:
        prompt = f"""
You extract professor information from an official faculty webpage.
Return strict JSON with keys:
name, email, title, lab, research_summary, matched_topics, evidence_json

Rules:
1. Use only the provided page content
2. If unknown, use null
3. matched_topics must be chosen only from this list: {keywords}
4. evidence_json must be an array of objects with field and snippet
5. Do not invent a name or email address
6. Keep research_summary under 120 Chinese characters when possible
7. If the page is a faculty directory / member list with multiple people and you cannot confidently map one specific professor, set name, email, title, lab, research_summary to null instead of guessing

URL: {content["url"]}
Title: {content["title"]}
Headings: {content["headings"]}
Body:
{content["text"][:6000]}
        """.strip()
        raw = self._chat(
            [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ]
        )
        data = maybe_json_loads(raw)
        return {
            "school": school,
            "institute": institute or None,
            "name": data.get("name"),
            "email": data.get("email"),
            "title": data.get("title"),
            "lab": data.get("lab"),
            "profile_url": content["url"],
            "source_domain": urlparse(content["url"]).netloc.lower(),
            "research_summary": data.get("research_summary"),
            "matched_topics": data.get("matched_topics") or [],
            "verification_status": "needs_review",
            "evidence_json": data.get("evidence_json") or [],
        }

    def generate_draft(
        self,
        professor: dict[str, Any],
        student_profile: str,
        template: str,
        sender_email: str,
    ) -> dict[str, str]:
        placeholders = _build_email_placeholders(professor, student_profile, sender_email)
        subject_template, body_template = _split_subject_body_template(template)
        prompt = f"""
Write a Chinese outreach email for a doctoral application.

Requirements:
1. Strictly follow the student's existing email style: concise, sincere, formal, no flattery
2. Keep the same paragraph order and format as the provided template
3. Do not use markdown, bullets, emoji, or extra headings
4. Only mention professor interests that are actually present in the provided data
5. Do not get the professor name, school, title, or research direction wrong
6. Keep subject and body ready to send as plain text
7. Return strict JSON with keys: subject, body

Professor:
name: {professor.get("name")}
school: {professor.get("school")}
institute: {professor.get("institute")}
title: {professor.get("title")}
email: {professor.get("email")}
research_summary: {professor.get("research_summary")}
matched_topics: {professor.get("matched_topics")}

Student profile:
{student_profile}

Structured placeholders:
{json.dumps(placeholders, ensure_ascii=False, indent=2)}

Subject template:
{subject_template}

Body template:
{body_template}

Sender email:
{sender_email}
        """.strip()
        raw = self._chat(
            [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return maybe_json_loads(raw)

    def generate_thinking_paragraph(
        self,
        professor: dict[str, Any],
        student_profile: str,
        sender_email: str,
        thinking_mode: str = "conservative",
    ) -> str:
        placeholders = _build_email_placeholders(
            professor,
            student_profile,
            sender_email,
            thinking_mode=thinking_mode,
        )
        mode_label = "主动版" if thinking_mode == "proactive" else "稳妥版"
        mode_requirements = (
            "语气更像你提前认真想过一个小问题。第二句话尽量提出一个更具体的研究切口，最好出现“是否可以从……切入”或“例如是否可以……”这类表达，但仍然要克制，不要写成夸张的科研计划。"
            if thinking_mode == "proactive"
            else "语气非常克制，适合第一次联系导师，更多体现关注点和一个保守的小思考，不要显得冒进。第二句话尽量保持宽一点，不要把问题说得过细。"
        )
        prompt = f"""
请只生成一小段中文套磁邮件正文，用来体现学生对导师方向的真实思考。

要求：
1. 只输出这一小段，不要输出称呼、署名、主题或解释
2. 严格 2 句话，语气真诚、克制、像真实学生，不要夸张
3. 必须围绕导师已知方向来写，不能编造导师论文、项目、招生信息
4. 可以结合学生画像中的课程、研究兴趣、思考素材，但不能编造学生经历
5. 不要空泛夸赞，不要写成“我非常崇拜您”
6. 最终文字要能直接放进邮件正文，长度尽量控制在 60 到 120 字
7. 如果信息不足，就保守地围绕 {placeholders["topic_hint"]} 方向提出一个小问题或想法
8. 当前生成模式是：{mode_label}。{mode_requirements}
9. 不得根据导师方向推断学生兴趣、课程或经历；没有学生思考素材时，只咨询已知研究问题，不声称学生已有相关经历或长期兴趣

导师信息：
name: {professor.get("name")}
school: {professor.get("school")}
institute: {professor.get("institute")}
title: {professor.get("title")}
research_summary: {professor.get("research_summary")}
matched_topics: {professor.get("matched_topics")}

学生画像：
{student_profile}

建议围绕的主题词：
{placeholders["topic_hint"]}

当前保底版本：
{placeholders["professor_thinking_paragraph"]}
        """.strip()
        raw = self._chat(
            [
                {"role": "system", "content": "你是谨慎的中文邮件写作助手。只输出可直接发送的正文段落，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
        )
        text = normalize_whitespace(raw)
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        return text

    def score_priority_notes(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact_items = [
            {
                "id": int(item.get("id") or 0),
                "name": str(item.get("name") or ""),
                "school": str(item.get("school") or ""),
                "contact_stage": str(item.get("contact_stage") or ""),
                "notes": str(item.get("notes") or "")[:900],
            }
            for item in items
            if str(item.get("notes") or "").strip()
        ]
        if not compact_items:
            return []
        prompt = f"""
你是导师联系工作台的优先级判断器。请只根据用户备注判断“这个导师现在是否应该更靠前处理”。

评分规则：
1. note_priority_score 范围必须是 -30 到 30 的整数。
2. 正分表示应提前处理，例如：明确优先、很匹配、已回复、约了沟通、需要尽快跟进、有名额、导师积极。
3. 负分表示应后置处理，例如：不匹配、已拒绝、没名额、暂不联系、方向偏离、用户明显想排除。
4. 备注只是辅助信号，不要因为客套话给高分。
5. reason 用 20 个中文字以内解释最关键依据。
6. 返回严格 JSON：{{"items":[{{"id":1,"note_priority_score":0,"note_priority_reason":"..."}}]}}

待评分导师：
{json.dumps(compact_items, ensure_ascii=False, indent=2)}
        """.strip()
        raw = self._chat(
            [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        data = maybe_json_loads(raw)
        rows = data.get("items") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                score = int(float(row.get("note_priority_score", 0)))
            except (TypeError, ValueError):
                score = 0
            output.append(
                {
                    "id": int(row.get("id") or 0),
                    "note_priority_score": max(-30, min(30, score)),
                    "note_priority_reason": str(row.get("note_priority_reason") or "AI 备注评分").strip()[:80],
                }
            )
        return output


def looks_like_directory_page(url: str, title: str, text: str) -> bool:
    haystack = f"{url} {title} {text[:1500]}".lower()
    positive_hits = count_keyword_hits(haystack, DIRECTORY_KEYWORDS)
    negative_hits = count_keyword_hits(haystack, DIRECTORY_PAGE_NEGATIVE_HINTS)
    specific_score = school_specific_directory_page_score(url, title, text)
    if specific_score >= 8:
        return True
    if specific_score <= -6:
        return False
    return positive_hits >= 1 and not (positive_hits == 1 and negative_hits >= 1)


def heuristic_extract_professor(content: dict[str, str], school: str, institute: str, keywords: list[str]) -> dict[str, Any]:
    text = content["text"]
    if looks_like_multi_person_page(content["url"], content["title"], text):
        matched_topics = [keyword for keyword in keywords if keyword.lower() in text.lower()]
        return {
            "school": school,
            "institute": institute or None,
            "name": None,
            "email": None,
            "title": None,
            "lab": None,
            "profile_url": content["url"],
            "source_domain": urlparse(content["url"]).netloc.lower(),
            "research_summary": None,
            "matched_topics": matched_topics,
            "verification_status": "needs_review",
            "evidence_json": [
                {"field": "page_type", "snippet": "多成员目录页，避免误将目录页强行抽成单个导师"},
                {"field": "title", "snippet": safe_preview(content["title"], 120)},
                {"field": "headings", "snippet": safe_preview(content["headings"], 120)},
            ],
        }
    title_match = re.search(r"(教授|副教授|助理教授|研究员|副研究员|特聘研究员|导师|博导)", text)
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    name = ""
    for candidate in [content["headings"], content["title"], text[:300]]:
        match = re.search(r"([\u4e00-\u9fff]{2,4})(?:老师|教授|副教授|研究员)?", candidate)
        if match:
            name = match.group(1)
            break
    summary_match = re.search(
        r"(研究方向|Research Interests|Areas of Interest)[:：]?(.*?)(教育背景|个人简介|代表论文|招生|联系方式|Email|邮箱)",
        text,
        re.I,
    )
    research_summary = normalize_whitespace(summary_match.group(2))[:300] if summary_match else safe_preview(text, 300)
    matched_topics = [keyword for keyword in keywords if keyword.lower() in text.lower()]
    evidence = [
        {"field": "title", "snippet": safe_preview(content["title"], 120)},
        {"field": "headings", "snippet": safe_preview(content["headings"], 120)},
        {"field": "research", "snippet": safe_preview(research_summary, 160)},
    ]
    return {
        "school": school,
        "institute": institute or None,
        "name": name or None,
        "email": email_match.group(0) if email_match else None,
        "title": title_match.group(1) if title_match else None,
        "lab": None,
        "profile_url": content["url"],
        "source_domain": urlparse(content["url"]).netloc.lower(),
        "research_summary": research_summary or None,
        "matched_topics": matched_topics,
        "verification_status": "needs_review",
        "evidence_json": evidence,
    }


def _extract_student_profile_fields(student_profile: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    meta: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current_section = ""
    for raw_line in student_profile.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_section = re.sub(r"^#+\s*", "", line).strip()
            sections.setdefault(current_section, [])
            continue
        if "：" in line and not line.startswith("-"):
            key, value = line.split("：", 1)
            meta[key.strip()] = value.strip()
            if current_section:
                sections.setdefault(current_section, []).append(line)
            continue
        clean = line[1:].strip() if line.startswith("-") else line
        if "：" in clean:
            key, value = clean.split("：", 1)
            meta[key.strip()] = value.strip()
        if current_section:
            sections.setdefault(current_section, []).append(clean)
    return meta, sections


def _find_first_section_text(sections: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = sections.get(name) or []
        for value in values:
            text = str(value).strip()
            if text and "：" not in text:
                return text
    return ""


def _find_section_items(sections: dict[str, list[str]], *names: str) -> list[str]:
    for name in names:
        values = [str(item).strip() for item in sections.get(name) or [] if str(item).strip() and "：" not in str(item)]
        if values:
            return values
    return []


def _normalize_major_grade(major: str, grade: str) -> str:
    major = major.strip()
    grade = grade.strip().replace(" ", "")
    if major and grade:
        return f"{major}{grade}"
    if major:
        return major
    return grade


def _build_professor_salutation(professor: dict[str, Any]) -> str:
    name = str(professor.get("name") or "").strip()
    title = str(professor.get("title") or "").strip()
    if not name:
        return "老师"
    for keyword in ["副教授", "助理教授", "副研究员", "教授", "研究员"]:
        if keyword in title:
            return f"{name}{keyword}"
    return f"{name}老师"


def _normalize_topic_hint(value: str) -> str:
    topic = normalize_whitespace(str(value or ""))
    topic = re.sub(r"https?://\S+", "", topic)
    topic = re.sub(r"^(主要)?(研究)?(兴趣|方向|领域|内容|课题)\s*[:：为是包括]*\s*", "", topic)
    topic = re.sub(r"^(主要)?(从事|围绕|聚焦|关注|包括|开展)\s*", "", topic)
    topic = topic.strip(" \t\r\n,，;；:：。.!！?？、/\\|-")
    topic = re.sub(r"(等)?(相关)?(研究|课题|方向|领域)$", "", topic).strip()
    topic = topic.strip(" \t\r\n,，;；:：。.!！?？、/\\|-")
    return topic


def _topic_candidates_from_summary(research_summary: str) -> list[str]:
    text = normalize_whitespace(research_summary)
    if not text:
        return []

    candidates: list[str] = []

    cleaned = re.sub(r"^(.*?)(研究方向|Research Interests|Areas of Interest)\s*[:：]?", "", text, count=1)
    for part in re.split(r"[。；;，,、/|｜\n\r]+", cleaned):
        candidate = _normalize_topic_hint(part)
        if not candidate:
            continue
        candidate = re.sub(r"^(与|和|及|以及|面向|关于)\s*", "", candidate).strip()
        if 2 <= len(candidate) <= 18:
            candidates.append(candidate)

    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_topic_hint(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _build_topic_hint(professor: dict[str, Any], sections: dict[str, list[str]] | None = None) -> str:
    matched_topics = [
        _normalize_topic_hint(str(item))
        for item in professor.get("matched_topics") or []
        if _normalize_topic_hint(str(item))
    ]
    student_interests = _find_section_items(sections or {}, "研究兴趣")
    student_interest_text = " ".join(student_interests)

    for topic in matched_topics:
        if topic and topic in student_interest_text:
            return topic
    for topic in matched_topics:
        if topic:
            return topic
    if matched_topics:
        return matched_topics[0]
    research_summary = str(professor.get("research_summary") or "").strip()
    if research_summary:
        for keyword in student_interests:
            keyword = _normalize_topic_hint(keyword)
            if keyword and keyword in research_summary:
                return keyword
        candidates = _topic_candidates_from_summary(research_summary)
        if candidates:
            return candidates[0]
    return "您的研究"


def _build_student_summary(meta: dict[str, str], sections: dict[str, list[str]]) -> str:
    parts: list[str] = []
    gpa = meta.get("GPA", "").strip().replace(" / ", "/")
    ranking = meta.get("排名", "").strip().replace("前 ", "前")
    if gpa or ranking:
        lead = []
        if gpa:
            lead.append(f"GPA为{gpa}")
        if ranking:
            lead.append(f"成绩排名{ranking}")
        parts.append("目前" + "，".join(lead) + "。")

    awards = _find_section_items(sections, "奖项与竞赛", "奖项", "竞赛")
    if awards:
        scholarships = [item for item in awards if "奖学金" in item or "国家奖学金" in item]
        competitions = [item for item in awards if item not in scholarships]
        if scholarships and competitions:
            competition_text = competitions[0].strip()
            if competition_text.startswith("在"):
                parts.append(f"我曾获{'、'.join(scholarships[:3])}，并{competition_text}。")
            else:
                parts.append(f"我曾获{'、'.join(scholarships[:3])}，并在{competition_text}。")
        else:
            parts.append(f"我曾获{'、'.join(awards[:3])}。")

    research_text = _find_first_section_text(sections, "科研与项目经历", "科研经历", "项目经历")
    if research_text:
        if research_text.startswith(("目前", "正在", "现", "我")):
            parts.append(research_text.rstrip("。") + "。")
        else:
            parts.append("我目前" + research_text.rstrip("。") + "。")

    return "".join(parts)


def _build_thinking_anchor(sections: dict[str, list[str]], topic_hint: str, research_summary: str) -> str:
    """Use only ideas explicitly supplied by the applicant."""
    idea_items = _find_section_items(sections, "思考素材", "相关课程与思考", "课程基础")
    return "；".join(item.rstrip("。") for item in idea_items[:2]).strip("；")


def _build_professor_thinking_paragraph(
    professor: dict[str, Any],
    sections: dict[str, list[str]],
    topic_hint: str,
    thinking_mode: str = "conservative",
) -> str:
    research_summary = str(professor.get("research_summary") or "").strip()
    anchor = _build_thinking_anchor(sections, topic_hint, research_summary)
    if anchor:
        return f"关于{topic_hint}，想结合以下思考向您请教：{anchor}。"
    if research_summary or professor.get("matched_topics"):
        text = (
            "希望进一步了解您当前关注的问题与研究计划。"
            if topic_hint == "您的研究"
            else f"希望进一步了解您在{topic_hint}方向当前关注的问题与研究计划。"
        )
        if thinking_mode == "proactive":
            text += "如有适合申请者阅读的资料，也希望能得到您的建议。"
        return text
    return ""


def _build_reply_request_sentence() -> str:
    return "如果您认为我目前的背景与课题组需求暂不匹配，也恳请您能简单回复我一下，我会非常感谢。"


def _build_email_placeholders(
    professor: dict[str, Any],
    student_profile: str,
    sender_email: str,
    overrides: dict[str, str] | None = None,
    thinking_mode: str = "conservative",
) -> dict[str, str]:
    meta, sections = _extract_student_profile_fields(student_profile)
    now = datetime.now()
    target_year_full = str(now.year + 1)
    target_year_short = str((now.year + 1) % 100)
    student_name = meta.get("姓名", "").strip() or "同学"
    student_school = meta.get("学校", "").strip() or "所在学校"
    student_major = meta.get("专业", "").strip()
    student_grade = meta.get("年级", "").strip()
    student_major_grade = _normalize_major_grade(student_major, student_grade)
    student_contact = meta.get("联系方式", "").strip() or sender_email
    student_homepage = meta.get("个人主页", "").strip() or "未填写个人主页"
    student_rank_label = meta.get("排名", "").strip().replace("前 ", "前") or "待补充"
    promotion_status = _find_first_section_text(sections, "学业情况")
    if "推免" in promotion_status or "保研" in promotion_status:
        promotion_status_sentence = promotion_status.rstrip("。") + "，"
    else:
        promotion_status_sentence = ""
    topic_hint = _build_topic_hint(professor, sections)
    professor_thinking_paragraph = _build_professor_thinking_paragraph(
        professor,
        sections,
        topic_hint,
        thinking_mode=thinking_mode,
    )

    placeholders = {
        "student_name": student_name,
        "student_school": student_school,
        "student_major": student_major,
        "student_grade": student_grade,
        "student_major_grade": student_major_grade,
        "student_contact": student_contact,
        "student_homepage": student_homepage,
        "student_rank_label": student_rank_label,
        "student_summary_paragraph": _build_student_summary(meta, sections),
        "professor_thinking_paragraph": professor_thinking_paragraph,
        "reply_request_sentence": _build_reply_request_sentence(),
        "promotion_status_sentence": promotion_status_sentence,
        "professor_name": str(professor.get("name") or "老师").strip() or "老师",
        "professor_salutation": _build_professor_salutation(professor),
        "school": str(professor.get("school") or "").strip(),
        "topic_hint": topic_hint,
        "research_summary": str(professor.get("research_summary") or "相关研究").strip() or "相关研究",
        "matched_topics": "、".join(str(item).strip() for item in professor.get("matched_topics") or [] if str(item).strip()) or topic_hint,
        "student_interest_summary": topic_hint,
        "student_profile": student_profile.strip(),
        "sender_email": sender_email,
        "current_date_cn": f"{now.year}年{now.month}月{now.day}日",
        "target_year_full": target_year_full,
        "target_year_short": target_year_short,
    }
    if overrides:
        placeholders.update({key: str(value) for key, value in overrides.items()})
    return placeholders


def _split_subject_body_template(template: str) -> tuple[str, str]:
    normalized = template.replace("\r\n", "\n").strip()
    lines = normalized.split("\n")
    if lines and re.match(r"^subject\s*:", lines[0], re.IGNORECASE):
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body
    if lines and lines[0].startswith("邮件主题建议："):
        subject = lines[0].split("：", 1)[1].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body
    if lines and lines[0].startswith("邮件主题："):
        subject = lines[0].split("：", 1)[1].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body
    return "", normalized


def _apply_placeholders(template: str, placeholders: dict[str, str]) -> str:
    output = template
    for key, value in placeholders.items():
        output = output.replace(f"{{{{{key}}}}}", str(value or ""))
    return output


def render_template(
    template: str,
    professor: dict[str, Any],
    student_profile: str,
    sender_email: str,
    overrides: dict[str, str] | None = None,
    thinking_mode: str = "conservative",
) -> dict[str, str]:
    placeholders = _build_email_placeholders(
        professor,
        student_profile,
        sender_email,
        overrides=overrides,
        thinking_mode=thinking_mode,
    )
    subject_template, body_template = _split_subject_body_template(template)
    subject = _apply_placeholders(subject_template, placeholders).strip()
    body = _apply_placeholders(body_template, placeholders).strip()
    if not subject:
        subject = f"博士申请咨询 - {placeholders['student_name']} - {placeholders['student_school']}"
    return {"subject": subject, "body": body}


def generate_locked_draft(
    config: AppConfig,
    professor: dict[str, Any],
    student_profile: str,
    template: str,
    sender_email: str,
    thinking_mode: str = "conservative",
) -> tuple[dict[str, str], str]:
    overrides: dict[str, str] = {}
    generator = f"template_locked_{thinking_mode}"
    if config.llm_enabled:
        try:
            llm = LLMClient(config)
            thinking = normalize_whitespace(
                llm.generate_thinking_paragraph(
                    professor,
                    student_profile,
                    sender_email,
                    thinking_mode=thinking_mode,
                )
            )
            if thinking:
                overrides["professor_thinking_paragraph"] = thinking
                generator = f"template_locked_{thinking_mode}+{config.llm_provider}_thinking"
        except Exception:
            generator = f"template_locked_{thinking_mode}_fallback"
    draft = render_template(
        template,
        professor,
        student_profile,
        sender_email,
        overrides=overrides or None,
        thinking_mode=thinking_mode,
    )
    return draft, generator
