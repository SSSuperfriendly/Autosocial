"""SMTP / IMAP / MIME helpers — the network-level email layer.

Template rendering and placeholder logic lives in services.py;
this module only deals with wire-format email operations.
"""

from __future__ import annotations

import email as email_module
import imaplib
import mimetypes
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path

from .config import AppConfig


# ---------------------------------------------------------------------------
# MIME building
# ---------------------------------------------------------------------------


def build_mime_message(
    sender_name: str,
    sender_email: str,
    to_email: str,
    subject: str,
    body: str,
    attachment_paths: list[str] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    for raw_path in attachment_paths or []:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        with open(path, "rb") as handle:
            msg.add_attachment(
                handle.read(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )
    return msg


def attachment_paths_from_dir(attachment_dir: str) -> list[str]:
    if not attachment_dir:
        return []
    path = Path(attachment_dir)
    if not path.exists() or not path.is_dir():
        return []
    return sorted(str(item) for item in path.iterdir() if item.is_file())


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------


def send_via_smtp(
    config: AppConfig,
    to_email: str,
    subject: str,
    body: str,
    attachment_paths: list[str] | None = None,
) -> str:
    msg = build_mime_message(
        config.sender_name,
        config.sender_email,
        to_email,
        subject,
        body,
        attachment_paths=attachment_paths,
    )
    if config.smtp_use_ssl:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=ssl.create_default_context(), timeout=config.http_timeout_seconds) as server:
            server.login(config.smtp_username, config.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.http_timeout_seconds) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(config.smtp_username, config.smtp_password)
            server.send_message(msg)
    return msg.get("Message-ID", "")


def test_smtp_login(config: AppConfig) -> tuple[bool, str]:
    try:
        if config.smtp_use_ssl:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=ssl.create_default_context(), timeout=config.http_timeout_seconds) as server:
                server.login(config.smtp_username, config.smtp_password)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.http_timeout_seconds) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(config.smtp_username, config.smtp_password)
        return True, "SMTP login succeeded"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------


def test_imap_login(config: AppConfig) -> tuple[bool, str]:
    try:
        mailbox = imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=config.http_timeout_seconds)
        mailbox.login(config.imap_username, config.imap_password)
        mailbox.select(config.imap_folder)
        mailbox.close()
        mailbox.logout()
        return True, "IMAP login succeeded"
    except Exception as exc:
        return False, str(exc)


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def extract_plain_text(message: email_module.message.Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                if payload is not None:
                    return payload.decode(charset, errors="ignore")
    else:
        payload = message.get_payload(decode=True)
        charset = message.get_content_charset() or "utf-8"
        if payload is not None:
            return payload.decode(charset, errors="ignore")
    return ""


# ---------------------------------------------------------------------------
# Reply sync
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReplyRecord:
    message_id: str
    from_email: str
    subject: str
    body_preview: str
    received_at: str
    raw_headers: str


def sync_replies_for_sender(
    config: AppConfig,
    professor_email: str,
    since_days: int,
) -> list[ReplyRecord]:
    sender = parseaddr(professor_email)[1].strip().lower()
    if not sender or "@" not in sender or any(char in sender for char in '\r\n'):
        raise ValueError("导师邮箱格式无效，无法同步回信。")
    if not 1 <= since_days <= 3650:
        raise ValueError("回信同步范围必须在 1 到 3650 天之间。")
    since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    quoted_sender = '"' + sender.replace('\\', '\\\\').replace('"', '\\"') + '"'
    records: list[ReplyRecord] = []
    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port, timeout=config.http_timeout_seconds) as mailbox:
        mailbox.login(config.imap_username, config.imap_password)
        status, _ = mailbox.select(config.imap_folder, readonly=True)
        if status != "OK":
            raise RuntimeError("无法打开 IMAP 邮箱文件夹。")
        status, data = mailbox.uid("SEARCH", None, "FROM", quoted_sender, "SINCE", since_date)
        if status != "OK" or not data:
            raise RuntimeError("IMAP 搜索失败。")
        uids = (data[0] or b"").split()
        for uid in uids:
            # PEEK reads the complete message without marking it as read.
            fetch_status, fetch_data = mailbox.uid("FETCH", uid, "(BODY.PEEK[])")
            if fetch_status != "OK" or not fetch_data:
                continue
            raw = b"".join(
                part[1] for part in fetch_data
                if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes)
            )
            if not raw:
                continue
            msg = email_module.message_from_bytes(raw)
            from_header = decode_mime_header(msg.get("From", ""))
            if parseaddr(from_header)[1].strip().lower() != sender:
                continue
            message_id = str(msg.get("Message-ID", "")).strip()
            if not message_id:
                continue
            records.append(ReplyRecord(
                message_id=message_id,
                from_email=from_header,
                subject=decode_mime_header(msg.get("Subject", "")),
                body_preview=extract_plain_text(msg)[:240],
                received_at=msg.get("Date", ""),
                raw_headers=str(dict(msg.items())),
            ))
    return records
