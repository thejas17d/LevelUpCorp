"""Write "Overall Jobs (<date>).html": every job LevelUpCorp has scored, with full details, search and filters.

Usage:  .venv\\Scripts\\python scripts\\jobs_catalog.py [YYYY-MM-DD] [output.html]
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from levelup.matcher import required_years  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"Overall Jobs ({day}).html")

con = sqlite3.connect(ROOT / "data" / "levelup.db")
con.row_factory = sqlite3.Row

STATUS_LABEL = {
    "applied": "Applied", "assisted": "Apply yourself", "needs_review": "Needs you", "review_hold": "Needs you",
    "queued": "Queued", "dry_run": "Queued", "rejected": "Not a fit", "filtered": "Filtered", "failed": "Failed",
}


def clean(s: str) -> str:
    s = (s or "").replace("&amp;", "&").replace("&nbsp;", " ").replace("&#xa0;", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


rows = con.execute("""
    SELECT j.*, s.score, s.verdict, s.reasons, s.est_min_lpa, s.est_max_lpa, s.seniority_fit,
           (SELECT MAX(attempted_at) FROM applications a WHERE a.key = j.key AND a.status = 'submitted') AS applied_at
    FROM jobs j JOIN scores s ON s.key = j.key
""").fetchall()

jobs = []
for r in rows:
    desc = clean(r["description"])
    try:
        score = int(r["score"])
    except (TypeError, ValueError):
        score = None
    status = "applied" if r["applied_at"] else r["status"]
    if r["est_min_lpa"] and r["est_max_lpa"]:
        pay = f"~{r['est_min_lpa']:.0f}-{r['est_max_lpa']:.0f} LPA (est.)"
    else:
        pay = ""
    yrs = required_years(r["description"] or "")
    src = (r["source"] or "").split(":")[0]
    jobs.append({
        "status": STATUS_LABEL.get(status, status or ""),
        "company": r["company"] or "", "title": r["title"] or "", "location": r["location"] or "",
        "score": score, "verdict": r["verdict"] or "", "reasons": r["reasons"] or "",
        "why_not": (r["status_reason"] or "") if status in ("rejected", "filtered", "failed") else "",
        "pay": r["salary_text"] or pay, "years": f"{yrs:g}+ yrs" if yrs else "",
        "source": src, "ats": r["ats"] or "", "posted": (r["posted_at"] or "")[:10],
        "applied": datetime.fromisoformat(r["applied_at"]).astimezone(IST).strftime("%d %b %I:%M %p") if r["applied_at"] else "",
        "link": r["apply_url"] or r["url"] or "",
        "desc": desc[:1800],
    })

order = {"Applied": 0, "Needs you": 1, "Apply yourself": 2, "Queued": 3, "Not a fit": 4, "Filtered": 5, "Failed": 6}
jobs.sort(key=lambda j: (order.get(j["status"], 9), -(j["score"] or 0)))
counts = Counter(j["status"] for j in jobs)
total_seen = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
filtered_reasons = con.execute("""SELECT status_reason, COUNT(*) n FROM jobs WHERE status='filtered'
                                  GROUP BY status_reason ORDER BY n DESC LIMIT 8""").fetchall()

e = lambda s: html.escape(str(s or ""))
filt = "".join(f"<li>{e(r['status_reason'] or '(no reason)')}: <b>{r['n']:,}</b></li>" for r in filtered_reasons)
buttons = "".join(f'<button class="f" data-s="{e(k)}">{e(k)} <span>{v}</span></button>'
                  for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 9)))

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Overall Jobs ({day})</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#16181b;--muted:#5f6670;--line:#e3e1da;--accent:#b38900;--ok:#1f7a4d;--warn:#a3483d;--chip:#f0eee9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181b;--card:#1e2124;--ink:#f0eee9;--muted:#a9aeb4;--line:#30343a;--accent:#ffd400;--ok:#5fc58f;--warn:#e08a7f;--chip:#292d31}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:26px 16px 60px}}h1{{margin:0 0 4px;font-size:26px}}.muted{{color:var(--muted)}}
.bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:18px 0 12px}}
input{{flex:1 1 260px;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:inherit}}
button.f{{border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 11px;border-radius:999px;cursor:pointer;font:inherit}}
button.f span{{color:var(--muted)}}button.f.on{{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}}
.job{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:8px 0}}
.job summary{{list-style:none;cursor:pointer;padding:11px 14px;display:grid;grid-template-columns:110px 1fr auto;gap:12px;align-items:center}}
.job summary::-webkit-details-marker{{display:none}}
.st{{font-size:12px;padding:3px 8px;border-radius:999px;background:var(--chip);text-align:center}}
.st.Applied{{color:var(--ok);font-weight:600}}.st.Needs{{color:var(--warn);font-weight:600}}
.t b{{display:block}}.t small{{color:var(--muted)}}.sc{{font-weight:700;font-variant-numeric:tabular-nums}}
.body{{padding:0 14px 14px;border-top:1px solid var(--line)}}
.kv{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:6px 18px;margin:12px 0}}
.kv div small{{display:block;color:var(--muted);font-size:12px}}.desc{{color:var(--muted);font-size:13.5px}}
a{{color:inherit;text-decoration-color:var(--accent);text-underline-offset:3px}}
@media (max-width:640px){{.job summary{{grid-template-columns:1fr auto}}.st{{grid-column:1/-1;justify-self:start}}}}
</style></head><body><main>
<h1>Overall Jobs ({day})</h1>
<p class="muted">Every job LevelUpCorp scored for Thejas M ({len(jobs):,} of {total_seen:,} postings discovered; the rest were filtered out by role, seniority, location or years before scoring).
Click a job for details. Fit score = how well the posting matches the resume (0-100).</p>
<div class="bar"><input id="q" placeholder="Search company, role, location, skill..." autocomplete="off">
<button class="f on" data-s="">All <span>{len(jobs)}</span></button>{buttons}</div>
<div id="list"></div>
<details class="job" style="margin-top:22px"><summary><span class="st">Filtered</span><span class="t"><b>Why most postings were filtered before scoring</b><small>top reasons</small></span><span></span></summary>
<div class="body"><ul>{filt}</ul></div></details>
<p class="muted">Generated {datetime.now(IST):%d %b %Y, %I:%M %p} IST from LevelUpCorp's database.</p>
</main>
<script>
const JOBS = {json.dumps(jobs, ensure_ascii=False)};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);
let status = "", q = "";
function render() {{
  const ql = q.toLowerCase();
  const rows = JOBS.filter(j => (!status || j.status === status) &&
    (!ql || [j.company, j.title, j.location, j.reasons, j.desc].join(" ").toLowerCase().includes(ql)));
  document.getElementById("list").innerHTML = rows.slice(0, 600).map(j => `
  <details class="job"><summary>
    <span class="st ${{esc(j.status.split(" ")[0])}}">${{esc(j.status)}}</span>
    <span class="t"><b>${{esc(j.company)}} - ${{esc(j.title)}}</b><small>${{esc(j.location)}}${{j.applied ? " · applied " + esc(j.applied) : ""}}</small></span>
    <span class="sc">${{j.score ?? ""}}</span></summary>
    <div class="body"><div class="kv">
      <div><small>Why it fits / doesn't</small>${{esc(j.reasons) || "-"}}</div>
      ${{j.why_not ? `<div><small>Not applied because</small>${{esc(j.why_not)}}</div>` : ""}}
      <div><small>Pay</small>${{esc(j.pay) || "not stated"}}</div>
      <div><small>Experience asked</small>${{esc(j.years) || "not stated"}}</div>
      <div><small>Found via</small>${{esc(j.source)}}${{j.ats ? " (" + esc(j.ats) + ")" : ""}}</div>
      <div><small>Posted</small>${{esc(j.posted) || "-"}}</div>
      <div><small>Link</small>${{j.link ? `<a href="${{esc(j.link)}}" target="_blank" rel="noopener">open posting</a>` : "-"}}</div>
    </div><p class="desc">${{esc(j.desc) || "No description was available for this listing."}}</p></div>
  </details>`).join("") || "<p class='muted'>No jobs match.</p>";
}}
document.getElementById("q").addEventListener("input", ev => {{ q = ev.target.value; render(); }});
document.querySelectorAll("button.f").forEach(b => b.addEventListener("click", () => {{
  document.querySelectorAll("button.f").forEach(x => x.classList.remove("on")); b.classList.add("on");
  status = b.dataset.s; render(); }}));
render();
</script></body></html>"""
out.write_text(page, encoding="utf-8")
print(f"wrote {out}  jobs={len(jobs)}  " + ", ".join(f"{k}={v}" for k, v in counts.items()))
