"""Writes data/report.html: one page showing applications, callbacks, review queue and apply-yourself list."""
from __future__ import annotations

import html
from datetime import datetime

from levelup.config import DATA_DIR
from levelup.db import DB

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;--good:#15803d;--warn:#b45309;--bad:#b91c1c}
@media (prefers-color-scheme: dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e5e7eb;--muted:#9ca3af;--line:#2a2f3a;--accent:#60a5fa;--good:#4ade80;--warn:#fbbf24;--bad:#f87171}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 60px}
h1{margin:0 0 4px;font-size:24px} h2{margin:28px 0 10px;font-size:17px}
.muted{color:var(--muted)} .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px} .tile b{display:block;font-size:22px}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%} th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em} tr:last-child td{border-bottom:0}
a{color:var(--accent)} .pill{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.good{color:var(--good)} .warn{color:var(--warn)} .bad{color:var(--bad)}
"""


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p class='muted'>Nothing here yet.</p>"
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<div class='tbl'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _link(url: str, text: str) -> str:
    return f"<a href='{html.escape(url or '')}' target='_blank' rel='noopener'>{html.escape(text or '')}</a>"


def build_report(db: DB) -> str:
    c = db.counts()
    apps = c.get("applications", {})
    emails = c.get("emails", {})
    q = db.conn.execute

    callbacks = q("""SELECT * FROM emails WHERE category IN ('interview','assessment','offer','recruiter_reply')
                     ORDER BY received_at DESC LIMIT 50""").fetchall()
    applied = q("""SELECT j.title, j.company, j.url, a.status, a.method, a.attempted_at, a.notes, s.score
                   FROM applications a JOIN jobs j ON j.key=a.key LEFT JOIN scores s ON s.key=j.key
                   ORDER BY a.attempted_at DESC LIMIT 200""").fetchall()
    review = q("""SELECT j.*, s.score FROM jobs j LEFT JOIN scores s ON s.key=j.key
                  WHERE j.status='needs_review' ORDER BY s.score DESC LIMIT 100""").fetchall()
    assisted = q("""SELECT j.*, s.score, s.reasons, s.est_min_lpa, s.est_max_lpa FROM jobs j JOIN scores s ON s.key=j.key
                    WHERE j.status='assisted' ORDER BY s.score DESC LIMIT 150""").fetchall()
    queued = q("""SELECT j.*, s.score, s.reasons FROM jobs j JOIN scores s ON s.key=j.key
                  WHERE j.status='queued' ORDER BY s.score DESC LIMIT 100""").fetchall()

    cls = {"submitted": "good", "dry_run": "warn", "needs_review": "warn", "failed": "bad"}
    tiles = [
        ("Applications submitted", apps.get("submitted", 0)),
        ("Interview invites", emails.get("interview", 0)),
        ("Assessments", emails.get("assessment", 0)),
        ("Waiting for your review", c.get("needs_review", 0)),
        ("Apply-yourself list", c.get("assisted", 0)),
        ("In the queue", c.get("queued", 0)),
        ("Jobs seen in total", sum(v for k, v in c.items() if isinstance(v, int))),
    ]
    sal = lambda r: (f"{r['salary_min_lpa'] or ''}-{r['salary_max_lpa'] or ''} LPA" if r["salary_max_lpa"]
                     else (f"~{r['est_min_lpa'] or '?'}-{r['est_max_lpa'] or '?'} LPA (est.)" if "est_max_lpa" in r.keys() and r["est_max_lpa"] else "?"))
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LevelUp Report</title><style>{CSS}</style></head><body><div class="wrap">
<h1>LevelUp job search</h1><p class="muted">Updated {datetime.now():%d %b %Y, %H:%M}</p>
<div class="tiles">{''.join(f"<div class='tile'><span class='muted'>{t}</span><b>{v}</b></div>" for t, v in tiles)}</div>
<h2>Callbacks and recruiter replies</h2>
{_table(["When", "Type", "Company", "Summary", "To do"], [[html.escape((r['received_at'] or '')[:16]), f"<span class='pill good'>{r['category']}</span>", html.escape(r['company'] or ''), html.escape(r['summary'] or ''), html.escape(r['action_needed'] or '')] for r in callbacks])}
<h2>Needs your review <span class="muted">(run: python -m levelup review)</span></h2>
{_table(["Score", "Job", "Company", "Why it stopped"], [[str(r['score'] or ''), _link(r['url'], r['title']), html.escape(r['company'] or ''), html.escape((r['status_reason'] or '')[:220])] for r in review])}
<h2>Apply yourself <span class="muted">(LinkedIn, Naukri, Workday and other sites the tool does not automate)</span></h2>
{_table(["Score", "Job", "Company", "Location", "Pay", "Why it fits"], [[str(r['score']), _link(r['status_reason'] or r['url'], r['title']), html.escape(r['company'] or ''), html.escape(r['location'] or ''), sal(r), html.escape((r['reasons'] or '')[:200])] for r in assisted])}
<h2>Application log</h2>
{_table(["When", "Status", "Job", "Company", "Score", "How", "Notes"], [[html.escape((r['attempted_at'] or '')[:16]), f"<span class='pill {cls.get(r['status'], '')}'>{r['status']}</span>", _link(r['url'], r['title']), html.escape(r['company'] or ''), str(r['score'] or ''), r['method'], html.escape((r['notes'] or '')[:160])] for r in applied])}
<h2>Queued for the next run</h2>
{_table(["Score", "Job", "Company", "Location", "Why"], [[str(r['score']), _link(r['url'], r['title']), html.escape(r['company'] or ''), html.escape(r['location'] or ''), html.escape((r['reasons'] or '')[:200])] for r in queued])}
</div></body></html>"""
    out = DATA_DIR / "report.html"
    out.write_text(page, encoding="utf-8")
    return str(out)
