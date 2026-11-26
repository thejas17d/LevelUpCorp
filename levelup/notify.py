"""Emails you: an instant alert for every interview/assessment/recruiter reply, and a daily digest.

Sends through Gmail SMTP with the same app password used for reading the inbox.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from levelup.config import DATA_DIR, Config
from levelup.db import DB

log = logging.getLogger(__name__)


def telegram(text: str) -> bool:
    """Push a message to your phone via a Telegram bot (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env).
    Never raises: a failed alert must not stop an application run."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    try:
        import requests
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}, timeout=15)
        return r.ok
    except Exception as e:  # noqa: BLE001
        log.info("  telegram failed: %s", e)
        return False
LABEL = {"interview": "Interview", "assessment": "Assessment", "offer": "Offer", "recruiter_reply": "Recruiter reply"}


def _send(cfg: Config, subject: str, html_body: str) -> bool:
    user = os.getenv("EMAIL_ADDRESS") or cfg.get("notify.email")
    password = os.getenv("EMAIL_APP_PASSWORD")
    to = cfg.get("notify.send_to") or user
    if not (user and password and to):
        log.info("  notify: email not configured - would have sent: %s", subject)
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    host = cfg.get("notify.smtp_host", "smtp.gmail.com")
    with smtplib.SMTP(host, int(cfg.get("notify.smtp_port", 587)), timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(user, [to], msg.as_string())
    return True


def send_callback_alerts(cfg: Config, db: DB) -> int:
    rows = db.unnotified_emails()
    if not rows:
        return 0
    items = "".join(
        f"<li><b>{LABEL.get(r['category'], r['category'])}</b> - {html.escape(r['company'] or '?')}"
        f"<br>{html.escape(r['summary'] or '')}"
        + (f"<br><b>To do:</b> {html.escape(r['action_needed'])}" if r["action_needed"] else "")
        + f"<br><small>Subject: {html.escape(r['subject'] or '')} | From: {html.escape(r['sender'] or '')}</small></li>"
        for r in rows
    )
    n_int = sum(1 for r in rows if r["category"] == "interview")
    subject = f"LevelUp: {n_int} interview call(s)!" if n_int else f"LevelUp: {len(rows)} recruiter response(s)"
    body = f"<h2>New responses to your applications</h2><ul>{items}</ul><p>Reply from your inbox as usual.</p>"
    tg = "\n\n".join(f"{LABEL.get(r['category'], r['category'])}: {r['company'] or '?'}\n{r['summary'] or ''}"
                     + (f"\nTo do: {r['action_needed']}" if r["action_needed"] else "") for r in rows)
    sent_tg = telegram(f"LevelUp - {subject}\n\n{tg}")
    if _send(cfg, subject, body) or sent_tg:
        db.mark_notified([r["msg_id"] for r in rows])
    return len(rows)


def send_daily_digest(cfg: Config, db: DB) -> bool:
    marker = DATA_DIR / f".digest-{date.today().isoformat()}"
    if marker.exists() or not cfg.get("notify.daily_digest", True):
        return False
    c = db.counts()
    apps = c.get("applications", {})
    assisted = db.conn.execute(
        """SELECT j.title, j.company, j.status_reason AS link, s.score FROM jobs j JOIN scores s ON s.key=j.key
           WHERE j.status='assisted' ORDER BY s.score DESC LIMIT 15"""
    ).fetchall()
    review = db.jobs_with_status("needs_review", limit=15)
    rows = "".join(f"<li>{s['score']} - <a href='{html.escape(s['link'] or '')}'>{html.escape(s['title'])}</a> at {html.escape(s['company'])}</li>" for s in assisted)
    rev = "".join(f"<li>{html.escape(r['title'])} at {html.escape(r['company'])}: {html.escape((r['status_reason'] or '')[:140])}</li>" for r in review)
    body = (
        f"<h2>LevelUp daily summary - {date.today():%d %b %Y}</h2>"
        f"<p>Submitted so far: <b>{apps.get('submitted', 0)}</b> | dry runs: {apps.get('dry_run', 0)} | "
        f"waiting for your review: <b>{c.get('needs_review', 0)}</b> | apply-yourself list: {c.get('assisted', 0)}</p>"
        f"<h3>Top jobs to apply to yourself (LinkedIn / Naukri / Workday etc.)</h3><ul>{rows or '<li>none</li>'}</ul>"
        f"<h3>Need your help (run: python -m levelup review)</h3><ul>{rev or '<li>none</li>'}</ul>"
        f"<p>Open data/report.html for the full list.</p>"
    )
    ok = _send(cfg, f"LevelUp daily: {apps.get('submitted', 0)} applied, {c.get('needs_review', 0)} need review", body)
    if ok:
        marker.write_text("sent")
    return ok
