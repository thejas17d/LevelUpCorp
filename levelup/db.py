"""SQLite store: every job seen, its score, every application attempt, every recruiter email.

The database file is data/levelup.db (git-ignored). Open it with any SQLite viewer
(e.g. "DB Browser for SQLite") if you want to look inside.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from levelup.config import DATA_DIR
from levelup.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    source TEXT, title TEXT, company TEXT, url TEXT, apply_url TEXT,
    location TEXT, remote INTEGER, description TEXT, salary_text TEXT,
    salary_min_lpa REAL, salary_max_lpa REAL, posted_at TEXT, ats TEXT,
    extra TEXT, first_seen TEXT,
    status TEXT DEFAULT 'new',          -- new | filtered | scored | rejected | queued | applied | needs_review | assisted | failed
    status_reason TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    key TEXT PRIMARY KEY,
    score INTEGER, verdict TEXT, reasons TEXT,
    est_min_lpa REAL, est_max_lpa REAL, seniority_fit TEXT, scored_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT, status TEXT, method TEXT, attempted_at TEXT,
    notes TEXT, cover_letter TEXT, answers TEXT, screenshot TEXT
);
CREATE TABLE IF NOT EXISTS emails (
    msg_id TEXT PRIMARY KEY,
    sender TEXT, subject TEXT, received_at TEXT,
    category TEXT, company TEXT, job_key TEXT, summary TEXT,
    action_needed TEXT, notified INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, finished_at TEXT, stats TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_apps_key ON applications(key);
CREATE INDEX IF NOT EXISTS idx_apps_time ON applications(attempted_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DATA_DIR / "levelup.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- jobs ----------
    def upsert_jobs(self, jobs: Iterable[Job]) -> int:
        """Insert jobs we have not seen before. Returns how many were new."""
        new = 0
        for j in jobs:
            cur = self.conn.execute("SELECT 1 FROM jobs WHERE key=? OR url=?", (j.key, j.url))
            if cur.fetchone():
                continue
            self.conn.execute(
                """INSERT INTO jobs (key, source, title, company, url, apply_url, location, remote,
                   description, salary_text, salary_min_lpa, salary_max_lpa, posted_at, ats, extra, first_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (j.key, j.source, j.title, j.company, j.url, j.apply_url or j.url, j.location,
                 int(j.remote), j.description, j.salary_text, j.salary_min_lpa, j.salary_max_lpa,
                 j.posted_at, j.ats, json.dumps(j.extra), now_iso()),
            )
            new += 1
        self.conn.commit()
        return new

    def jobs_with_status(self, status: str, limit: int = 1000) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY first_seen DESC LIMIT ?", (status, limit)
        ).fetchall()

    def set_status(self, key: str, status: str, reason: str = "", commit: bool = True) -> None:
        self.conn.execute("UPDATE jobs SET status=?, status_reason=? WHERE key=?", (status, reason[:500], key))
        if commit:
            self.conn.commit()

    def get_job(self, key: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()

    # ---------- scores ----------
    def save_score(self, key: str, score: int, verdict: str, reasons: str,
                   est_min: Optional[float], est_max: Optional[float], seniority_fit: str) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO scores (key, score, verdict, reasons, est_min_lpa, est_max_lpa, seniority_fit, scored_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (key, score, verdict, reasons, est_min, est_max, seniority_fit, now_iso()),
        )
        self.conn.commit()

    def queued_jobs(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT j.*, s.score, s.reasons, s.est_min_lpa, s.est_max_lpa FROM jobs j
               JOIN scores s ON s.key=j.key WHERE j.status='queued'
               ORDER BY s.score DESC LIMIT ?""", (limit,)
        ).fetchall()

    # ---------- applications ----------
    def log_application(self, key: str, status: str, method: str, notes: str = "",
                        cover_letter: str = "", answers: Optional[dict] = None, screenshot: str = "") -> None:
        self.conn.execute(
            """INSERT INTO applications (key, status, method, attempted_at, notes, cover_letter, answers, screenshot)
               VALUES (?,?,?,?,?,?,?,?)""",
            (key, status, method, now_iso(), notes[:2000], cover_letter, json.dumps(answers or {}), screenshot),
        )
        self.conn.commit()

    def applications_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status='submitted' AND substr(attempted_at,1,10)=?", (today,)
        ).fetchone()
        return int(row[0])

    def applied_companies(self) -> list[str]:
        rows = self.conn.execute(
            """SELECT DISTINCT j.company FROM applications a JOIN jobs j ON j.key=a.key
               WHERE a.status IN ('submitted','dry_run')"""
        ).fetchall()
        return [r[0] for r in rows if r[0]]

    def company_application_count(self, company: str, days: int = 30) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) FROM applications a JOIN jobs j ON j.key=a.key
               WHERE a.status='submitted' AND lower(j.company)=lower(?)
               AND a.attempted_at >= datetime('now', ?)""", (company, f"-{days} days")
        ).fetchone()
        return int(row[0])

    # ---------- emails ----------
    def email_seen(self, msg_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM emails WHERE msg_id=?", (msg_id,)).fetchone() is not None

    def save_email(self, msg_id: str, sender: str, subject: str, received_at: str, category: str,
                   company: str, job_key: str, summary: str, action_needed: str) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO emails (msg_id, sender, subject, received_at, category, company, job_key, summary, action_needed)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (msg_id, sender, subject, received_at, category, company, job_key, summary, action_needed),
        )
        self.conn.commit()

    def unnotified_emails(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM emails WHERE notified=0 AND category IN ('interview','assessment','offer','recruiter_reply')"
        ).fetchall()

    def mark_notified(self, msg_ids: list[str]) -> None:
        self.conn.executemany("UPDATE emails SET notified=1 WHERE msg_id=?", [(m,) for m in msg_ids])
        self.conn.commit()

    # ---------- runs ----------
    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict) -> None:
        self.conn.execute("UPDATE runs SET finished_at=?, stats=? WHERE id=?", (now_iso(), json.dumps(stats), run_id))
        self.conn.commit()

    def counts(self) -> dict:
        rows = self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
        out = {r[0]: r[1] for r in rows}
        rows = self.conn.execute("SELECT status, COUNT(*) FROM applications GROUP BY status").fetchall()
        out["applications"] = {r[0]: r[1] for r in rows}
        rows = self.conn.execute("SELECT category, COUNT(*) FROM emails GROUP BY category").fetchall()
        out["emails"] = {r[0]: r[1] for r in rows}
        return out
