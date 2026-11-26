"""Write a one-page HTML summary of one day's applications.

Usage:  .venv\\Scripts\\python scripts\\daily_summary.py [YYYY-MM-DD] [output.html]
Defaults: today (local date) and "applications on <date>.html" in the current folder.
Reads data/levelup.db only. No answers, cover letters or contact details go into the page.
"""
from __future__ import annotations

import html
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "levelup.db"
IST = timezone(timedelta(hours=5, minutes=30))

day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"applications on {day}.html")

con = sqlite3.connect(DB)
try:
    import json as _json
    import yaml as _yaml
    _prof = _json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    _cfg = _yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
except Exception:
    _prof, _cfg = {}, {}
WHO = _prof.get("full_name", "")
TARGET = ((_cfg.get("applicant") or {}).get("expected_ctc_lpa") or "").split("(")[0].strip()
SCOPE = "Bengaluru + remote" if (_cfg.get("search") or {}).get("cities") else "India + remote, any company size"
con.row_factory = sqlite3.Row


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(IST)


apps = [r for r in con.execute(
    """SELECT a.*, j.title, j.company, j.location, j.url, j.apply_url, j.ats, s.score, s.reasons,
              s.est_min_lpa, s.est_max_lpa, j.salary_text
       FROM applications a JOIN jobs j ON j.key = a.key LEFT JOIN scores s ON s.key = a.key
       ORDER BY a.attempted_at""").fetchall()
       if local(r["attempted_at"]).date().isoformat() == day]

# Latest outcome per job for the day
latest: dict[str, sqlite3.Row] = {}
for r in apps:
    latest[r["key"]] = r
submitted = [r for r in latest.values() if r["status"] == "submitted"]
review = [r for r in latest.values() if r["status"] == "needs_review"]
failed = [r for r in latest.values() if r["status"] == "failed"]
assisted = con.execute(
    """SELECT j.title, j.company, j.location, j.status_reason AS link, s.score, s.reasons
       FROM jobs j JOIN scores s ON s.key = j.key WHERE j.status = 'assisted'
       ORDER BY s.score DESC LIMIT 100""").fetchall()

e = lambda s: html.escape(str(s or ""))


def pay(r) -> str:
    if r["salary_text"]:
        return e(r["salary_text"])
    if r["est_min_lpa"] and r["est_max_lpa"]:
        return f"~{r['est_min_lpa']:.0f}&ndash;{r['est_max_lpa']:.0f} LPA (est.)"
    return "&mdash;"


def rows(items, with_time=True) -> str:
    out_rows = []
    for i, r in enumerate(items, 1):
        link = r["apply_url"] or r["url"]
        t = local(r["attempted_at"]).strftime("%I:%M %p").lstrip("0") if with_time else ""
        out_rows.append(
            f"<tr><td class='n'>{i}</td><td><b>{e(r['company'])}</b></td>"
            f"<td><a href='{e(link)}'>{e(r['title'])}</a></td><td>{e(r['location'])}</td>"
            f"<td class='n'>{e(r['score'])}</td><td>{pay(r)}</td><td>{e(r['ats'])}</td><td class='n'>{t}</td></tr>")
    return "".join(out_rows)


companies = sorted({r["company"] for r in submitted})
by_company = {}
for r in submitted:
    by_company[r["company"]] = by_company.get(r["company"], 0) + 1

head = "<tr><th>#</th><th>Company</th><th>Role</th><th>Location</th><th>Fit</th><th>Pay</th><th>Via</th><th>Time (IST)</th></tr>"
review_rows = "".join(
    f"<li><b>{e(r['company'])}</b> &ndash; <a href='{e(r['apply_url'] or r['url'])}'>{e(r['title'])}</a>"
    f"<br><span class='muted'>{e((r['notes'] or '')[:220])}</span></li>" for r in review) or "<li>None</li>"
assisted_rows = "".join(
    f"<li><b>{e(r['company'])}</b> &ndash; <a href='{e(r['link'])}'>{e(r['title'])}</a> "
    f"<span class='muted'>({e(r['location'])}, fit {e(r['score'])})</span></li>" for r in assisted) or "<li>None</li>"

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Applications on {day}</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#16181b;--muted:#5f6670;--line:#e3e1da;--accent:#c79a00;--ok:#1f7a4d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181b;--card:#1e2124;--ink:#f0eee9;--muted:#a9aeb4;--line:#30343a;--accent:#ffd400;--ok:#5fc58f}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:28px 16px 60px}}h1{{margin:0 0 4px;font-size:28px}}h2{{margin:34px 0 10px;font-size:19px}}
.muted{{color:var(--muted)}}.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}.tile b{{display:block;font-size:28px}}
.tile.ok b{{color:var(--ok)}}.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}}
table{{border-collapse:collapse;width:100%;min-width:760px}}th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}td.n{{text-align:right;white-space:nowrap}}
a{{color:inherit;text-decoration-color:var(--accent);text-underline-offset:3px}}ul{{padding-left:20px}}li{{margin:6px 0}}
.box{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:12px 18px}}
</style></head><body><main>
<h1>Applications on {day}</h1>
<p class="muted">{html.escape(WHO)} &middot; {SCOPE} &middot; target {html.escape(TARGET)} &middot; sent with LevelUpCorp</p>
<div class="tiles">
<div class="tile ok"><b>{len(submitted)}</b>applications submitted</div>
<div class="tile"><b>{len(companies)}</b>companies</div>
<div class="tile"><b>{len(review)}</b>need your action</div>
<div class="tile"><b>{len(assisted)}</b>apply-yourself links</div>
</div>
<h2>Submitted ({len(submitted)})</h2>
<div class="wrap"><table>{head}{rows(submitted) or "<tr><td colspan=8>None yet</td></tr>"}</table></div>
<h2>When to expect emails</h2>
<div class="box"><ul>
<li><b>Within minutes:</b> an automatic &ldquo;thanks for applying&rdquo; email from most companies (Greenhouse, Lever and Ashby send these).</li>
<li><b>3&ndash;14 days:</b> real replies such as a recruiter call, screening questions or an assessment link. Most arrive in the first week; startups are often faster.</li>
<li><b>2&ndash;4 weeks:</b> rejections, if any. Many companies never send one, so no reply after 3 weeks usually means no.</li>
</ul></div>
<h2>Need your action ({len(review)})</h2>
<p class="muted">The form had a CAPTCHA nobody solved, or a required question with no truthful answer in your profile. Finish with <code>python -m levelup review</code>, or open the link.</p>
<ul>{review_rows}</ul>
<h2>Apply yourself (LinkedIn, Naukri, Workday &hellip;)</h2>
<p class="muted">These sites forbid bots, so the tool never submits there. Top matches by fit score:</p>
<ul>{assisted_rows}</ul>
<p class="muted">Failed attempts today: {len(failed)}. Generated {datetime.now(IST):%d %b %Y, %I:%M %p} IST.</p>
</main></body></html>"""
out.write_text(page, encoding="utf-8")
print(f"wrote {out}  submitted={len(submitted)} companies={len(companies)} review={len(review)} assisted={len(assisted)}")
