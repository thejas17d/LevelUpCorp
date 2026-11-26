"""Watches your mailbox for replies to applications and flags interview callbacks.

Uses plain IMAP with a Gmail *app password* (no Google Cloud project needed).
Read-only: it never deletes, moves or marks your emails.
"""
from __future__ import annotations

import email
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from levelup.config import DATA_DIR, Config
from levelup.db import DB
from levelup.llm import LLM, LLMError
from levelup.models import html_to_text

log = logging.getLogger(__name__)
STATE = DATA_DIR / "state.json"

ATS_SENDERS = r"greenhouse|lever\.co|ashbyhq|workable|smartrecruiters|recruitee|myworkday|icims|naukri|instahyre|cutshort|wellfound|hirist|linkedin\.com|keka|darwinbox|zoho"
KEYWORDS = r"interview|application|applied|assessment|assignment|coding (test|challenge)|hackerrank|codility|shortlist|next steps?|schedule|availability|offer|position|role|opportunity|candidate|recruit|hiring|thank you for (applying|your interest)|unfortunately|regret|moving forward"

CLASSIFY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["emails"],
    "properties": {"emails": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "category", "company", "role", "summary", "action_needed"],
        "properties": {
            "id": {"type": "string"},
            "category": {"type": "string", "enum": ["interview", "assessment", "offer", "recruiter_reply",
                                                     "acknowledgement", "rejection", "job_alert", "not_relevant"]},
            "company": {"type": "string"}, "role": {"type": "string"},
            "summary": {"type": "string", "description": "One sentence"},
            "action_needed": {"type": "string", "description": "What the candidate must do and by when; empty if nothing"},
        }}}},
}

SYSTEM = (
    "You sort a job seeker's emails. Categories: interview (invitation or scheduling of any interview/call), "
    "assessment (coding test, take-home, online assessment), offer, recruiter_reply (a human recruiter writing about "
    "a role, asking questions or for CV/availability), acknowledgement (automatic 'we received your application'), "
    "rejection, job_alert (newsletters, job recommendations), not_relevant (anything else). "
    "Be precise: only call it 'interview' if a conversation/interview is actually being proposed or scheduled."
)


def fetch_security_code(since: float, wait_seconds: int = 120) -> str:
    """Poll Gmail (read-only) for an ATS one-time security code sent after `since` (epoch seconds).
    Greenhouse: 'Copy and paste this code into the security code field on your application: XXXXXXXX'."""
    import time

    user, password = os.getenv("EMAIL_ADDRESS"), (os.getenv("EMAIL_APP_PASSWORD") or "").replace(" ", "")
    if not (user and password):
        return ""
    code_re = re.compile(r"(?:security code|verification code)[^:]{0,120}:\s*([A-Za-z0-9]{6,10})\b", re.I)
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com")
            m.login(user, password)
            m.select("INBOX", readonly=True)
            day = datetime.fromtimestamp(since, timezone.utc).strftime("%d-%b-%Y")
            typ, data = m.search(None, f'(SINCE "{day}" OR SUBJECT "security code" SUBJECT "verification code")')
            ids = (data[0].split() if data and data[0] else [])[-10:]
            for mid in reversed(ids):
                typ, msg_data = m.fetch(mid, "(BODY.PEEK[])")
                msg = email.message_from_bytes(msg_data[0][1])
                try:
                    sent = parsedate_to_datetime(msg.get("Date")).timestamp()
                except Exception:
                    sent = 0
                if sent and sent < since:
                    continue
                body = ""
                for part in msg.walk():
                    if part.get_content_type() in ("text/plain", "text/html"):
                        body += (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "ignore")
                found = code_re.search(html_to_text(body) if "<" in body else body)
                if found:
                    m.logout()
                    return found.group(1)
            m.logout()
        except Exception as e:  # noqa: BLE001
            log.info("  security-code check failed: %s", e)
        time.sleep(8)
    return ""


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _decode(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _body(msg) -> str:
    if msg.is_multipart():
        plain, html = "", ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not html:
                html = text
        return (plain or html_to_text(html))[:3000]
    payload = msg.get_payload(decode=True) or b""
    text = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
    return (html_to_text(text) if "<html" in text.lower() else text)[:3000]


def fetch_candidate_emails(cfg: Config, db: DB) -> list[dict]:
    user = os.getenv("EMAIL_ADDRESS") or cfg.get("notify.email")
    password = os.getenv("EMAIL_APP_PASSWORD")
    if not (user and password):
        log.info("  inbox: EMAIL_ADDRESS / EMAIL_APP_PASSWORD not set in .env - skipping")
        return []
    host = cfg.get("inbox.imap_host", "imap.gmail.com")
    state = _load_state()
    since = state.get("inbox_since") or (datetime.now(timezone.utc) - timedelta(days=int(cfg.get("inbox.first_scan_days", 14)))).strftime("%d-%b-%Y")
    companies = [c.lower() for c in db.applied_companies()]

    out = []
    with imaplib.IMAP4_SSL(host) as M:
        M.login(user, password)
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-400:]
        for num in ids:
            typ, msg_data = M.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            msg_id = msg.get("Message-ID") or f"{num.decode()}-{msg.get('Date')}"
            if db.email_seen(msg_id):
                continue
            sender = _decode(msg.get("From"))
            subject = _decode(msg.get("Subject"))
            addr = parseaddr(sender)[1].lower()
            if addr == user.lower():
                continue
            body = _body(msg)
            hay = f"{sender} {subject} {body[:1500]}".lower()
            relevant = re.search(ATS_SENDERS, addr) or re.search(KEYWORDS, subject.lower()) or \
                any(c and len(c) > 2 and c in hay for c in companies)
            if not relevant:
                continue
            try:
                received = parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:
                received = ""
            out.append({"id": msg_id, "from": sender, "subject": subject, "received": received, "body": body})
    state["inbox_since"] = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
    _save_state(state)
    return out


def scan_inbox(cfg: Config, llm: LLM, db: DB) -> dict:
    mails = fetch_candidate_emails(cfg, db)
    stats = {"checked": len(mails)}
    for i in range(0, len(mails), 10):
        batch = mails[i:i + 10]
        payload = [{"id": m["id"], "from": m["from"], "subject": m["subject"], "body": m["body"][:1800]} for m in batch]
        try:
            res = llm.json(task="inbox", system=SYSTEM, user=json.dumps(payload, ensure_ascii=False),
                           schema=CLASSIFY_SCHEMA, effort="low", max_tokens=6000)
        except LLMError as e:
            log.warning("inbox classification failed: %s", e)
            continue
        by_id = {e["id"]: e for e in res["emails"]}
        for m in batch:
            c = by_id.get(m["id"])
            if not c:
                continue
            job_key = ""
            if c["company"]:
                row = db.conn.execute(
                    """SELECT j.key FROM jobs j JOIN applications a ON a.key=j.key
                       WHERE lower(j.company)=lower(?) ORDER BY a.attempted_at DESC LIMIT 1""", (c["company"],)
                ).fetchone()
                job_key = row[0] if row else ""
            db.save_email(m["id"], m["from"], m["subject"], m["received"], c["category"], c["company"],
                          job_key, c["summary"], c["action_needed"])
            stats[c["category"]] = stats.get(c["category"], 0) + 1
            if job_key and c["category"] in ("interview", "assessment", "offer", "rejection"):
                db.set_status(job_key, {"rejection": "rejected_by_company"}.get(c["category"], c["category"]))
    return stats
