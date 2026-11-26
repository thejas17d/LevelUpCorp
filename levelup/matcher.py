"""Decides which discovered jobs are worth applying to.

Two stages:
  1. Rules (free, instant): title, seniority, location, freshness, salary floor, company limits.
  2. Claude scoring (only for jobs that pass the rules): fit score 0-100, reasons,
     salary estimate when the posting has none, and knock-out flags.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta

from levelup.config import Config
from levelup.db import DB
from levelup.llm import LLM, LLMError
from levelup.resume import profile_brief
from levelup.salary import meets_floor

log = logging.getLogger(__name__)

INDIA_WORDS = r"india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|gurgaon|gurugram|noida|kolkata|ahmedabad|kochi|trivandrum|thiruvananthapuram|coimbatore|jaipur|indore|chandigarh|mysuru|mysore|vizag|visakhapatnam|bhubaneswar"
GLOBAL_REMOTE = r"worldwide|anywhere|global|remote\s*$|^remote|apac|asia|emea and apac|international"
FOREIGN_ONLY = r"\b(us only|usa only|united states only|us-based|us based|must be located in the us|canada only|uk only|europe only|eu only|latam|americas only|u\.s\.)"
REMOTE_TIED = (r"remote\s*[-–:(,/]\s*(?!india|apac|asia|global|worldwide|anywhere|international)[a-z]"
               r"|[a-z]+\s*[-–]\s*remote")
SENIOR = r"\b(senior|sr\.?|lead|staff|principal|architect|head|director|manager|vp|chief)\b"
JUNIOR = r"\b(intern|internship|trainee|apprentice)\b"


def _word(keyword: str, text: str) -> bool:
    """Whole-word match (plural / -ing allowed): 'ml' matches 'ML Engineer' but not 'HTML';
    'engineer' matches 'Engineering'."""
    return bool(keyword) and re.search(
        r"(?<![a-z0-9])" + re.escape(keyword) + r"(?:s|ing)?(?![a-z0-9])", text) is not None


_YEARS_RE = re.compile(
    r"(?:minimum(?: of)?|at least|min\.?)?\s*(\d{1,2})(?:\.\d)?\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?"
    r"(?:years?|yrs?)\b(?:\s+of)?", re.I)


def required_years(desc: str) -> float | None:
    """Smallest 'N+ years ... experience' requirement stated in a job description, or None.
    Only counts numbers that sit near the word 'experience' (so '10 years of history' is ignored)."""
    text = re.sub(r"<[^>]+>", " ", desc or "")
    found = []
    for m in _YEARS_RE.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 80].lower()
        if "experience" in window and not re.search(r"\bpreferred\b|\bbonus\b|\bnice to have\b", window):
            n = float(m.group(1))
            if 0 < n <= 20:
                found.append(n)
    return min(found) if found else None


def _years(profile: dict) -> float:
    try:
        return float(profile.get("total_experience_years") or 0)
    except (TypeError, ValueError):
        return 0.0


def rule_filter(job, cfg: Config, profile: dict, db: DB) -> str:
    """Return '' if the job passes, otherwise a short reason it was filtered out."""
    title = (job["title"] or "").lower()
    loc = (job["location"] or "").lower()
    desc = (job["description"] or "").lower()[:3000]

    include = [k.lower().strip() for k in (cfg.get("search.title_must_include") or [])]
    if include and not any(_word(k, title) for k in include):
        return "title not a target role"
    exclude = [k.lower().strip() for k in (cfg.get("search.title_exclude") or [])]
    if any(_word(k, title) for k in exclude):
        return "title excluded"

    yrs = _years(profile)
    if yrs < float(cfg.get("search.senior_titles_from_years", 4)) and re.search(SENIOR, title):
        return "too senior for current experience"
    need = required_years((job["description"] or "")[:12000])
    if need is not None and need >= float(cfg.get("search.max_required_years", 3)):
        return f"posting asks for {need:g}+ years of experience"
    if yrs >= 1 and re.search(JUNIOR, title) and not cfg.get("search.include_internships", False):
        return "internship"

    india = re.search(INDIA_WORDS, loc) is not None
    remote_ok = cfg.get("search.remote_ok", True)
    is_remote = bool(job["remote"]) or "remote" in loc
    if not india:
        if not (remote_ok and is_remote):
            return "location outside India"
        if re.search(FOREIGN_ONLY, loc + " " + desc[:1500]):
            return "remote but restricted to another country"
        # "Remote - US", "Remote (Mexico)", "US-Remote", "Chicago, US-Remote", "GB-United Kingdom-Remote"
        if re.search(REMOTE_TIED, loc):
            return f"remote limited to {job['location'][:40]}"
        if loc and not re.search(GLOBAL_REMOTE + "|" + INDIA_WORDS, loc) and not cfg.get("search.accept_any_remote", False):
            return f"remote limited to {job['location'][:40]}"
    elif cfg.get("search.cities"):
        cities = [c.lower() for c in cfg.get("search.cities")]
        if not any(c in loc for c in cities) and not is_remote:
            return "city not in preferred list"

    max_age = int(cfg.get("search.max_age_days", 14))
    if job["posted_at"]:
        try:
            posted = datetime.fromisoformat(job["posted_at"][:10]).date()
            if posted < date.today() - timedelta(days=max_age):
                return "posting too old"
        except ValueError:
            pass

    ok = meets_floor(job["salary_min_lpa"], job["salary_max_lpa"], cfg.min_lpa)
    if ok is False:
        return f"salary below {cfg.min_lpa} LPA"

    blocked = [c.lower() for c in (cfg.get("search.company_blocklist") or [])]
    if (job["company"] or "").lower() in blocked:
        return "company blocklisted"
    per_company = int(cfg.get("apply.max_per_company_per_30_days", 2))
    if job["company"] and db.company_application_count(job["company"], 30) >= per_company:
        return "already applied to this company recently"
    return ""


SCORE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "score", "verdict", "reasons", "est_min_lpa", "est_max_lpa", "seniority_fit", "knockouts"],
        "properties": {
            "id": {"type": "string"},
            "score": {"type": "integer", "description": "0-100 fit of candidate to this job"},
            "verdict": {"type": "string", "enum": ["apply", "maybe", "skip"]},
            "reasons": {"type": "string", "description": "One or two short sentences"},
            "est_min_lpa": {"type": ["number", "null"]},
            "est_max_lpa": {"type": ["number", "null"]},
            "seniority_fit": {"type": "string", "enum": ["under", "match", "over"]},
            "knockouts": {"type": "array", "items": {"type": "string"},
                          "description": "Hard requirements the candidate clearly fails (degree, years, clearance, language, location, visa)"},
        }}}},
}


def _system(cfg: Config, profile: dict) -> str:
    return (
        "You screen job postings for one candidate and score how well each fits.\n"
        "Scoring guide: 85-100 strong match (core stack and level match); 70-84 good match with small gaps; "
        "50-69 stretch; below 50 poor fit. Be honest - a wasted application costs the candidate credibility.\n"
        f"Candidate wants roles paying at least {cfg.min_lpa} LPA (INR lakhs per annum), "
        f"locations: India or remote-from-India. "
        "If a posting shows no salary, estimate the realistic India-market annual CTC range in LPA for that "
        "role, level and company (for foreign remote roles convert to INR). If salary is given, echo it in LPA. "
        "List knockouts only for explicit hard requirements the candidate fails.\n\n"
        f"CANDIDATE PROFILE\n{profile_brief(profile)}"
    )


def score_jobs(rows, cfg: Config, profile: dict, llm: LLM, db: DB, batch_size: int = 0) -> int:
    """Score rows with the LLM; set status to queued/rejected. Returns number queued."""
    system = _system(cfg, profile)
    batch_size = batch_size or int(cfg.get("llm.score_batch_size", 8))
    desc_chars = int(cfg.get("llm.score_description_chars", 2500))
    queued = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        payload = [{
            "id": r["key"], "title": r["title"], "company": r["company"], "location": r["location"],
            "remote": bool(r["remote"]), "salary": r["salary_text"] or "not stated",
            "description": (r["description"] or "")[:desc_chars],
        } for r in batch]
        try:
            res = llm.json(task="score", system=system, user=json.dumps(payload, ensure_ascii=False),
                           schema=SCORE_SCHEMA, effort=cfg.get("llm.effort.score", "low"), max_tokens=int(cfg.get("llm.score_max_tokens", 8000)))
        except LLMError as e:
            log.warning("scoring batch failed: %s", e)
            continue
        by_id = {x["id"]: x for x in res.get("results", [])}
        for r in batch:
            s = by_id.get(r["key"])
            if not s:
                continue
            db.save_score(r["key"], s["score"], s["verdict"], s["reasons"], s["est_min_lpa"],
                          s["est_max_lpa"], s["seniority_fit"])
            salary_ok = meets_floor(r["salary_min_lpa"], r["salary_max_lpa"], cfg.min_lpa)
            if salary_ok is None:
                salary_ok = meets_floor(s["est_min_lpa"], s["est_max_lpa"], cfg.min_lpa)
                if salary_ok is None:
                    salary_ok = bool(cfg.get("match.allow_unknown_salary", True))
            if s["knockouts"]:
                db.set_status(r["key"], "rejected", "knockout: " + "; ".join(s["knockouts"])[:300])
            elif not salary_ok:
                db.set_status(r["key"], "rejected", f"estimated pay below {cfg.min_lpa} LPA")
            elif s["score"] >= cfg.min_score and s["verdict"] != "skip":
                db.set_status(r["key"], "queued", f"score {s['score']}: {s['reasons']}")
                queued += 1
            else:
                db.set_status(r["key"], "rejected", f"score {s['score']}: {s['reasons']}")
    return queued


def run_matching(cfg: Config, profile: dict, llm: LLM, db: DB) -> dict:
    new_rows = db.jobs_with_status("new", limit=50000)
    passed = []
    filtered = 0
    for r in new_rows:
        reason = rule_filter(r, cfg, profile, db)
        if reason:
            db.set_status(r["key"], "filtered", reason, commit=False)
            filtered += 1
        else:
            passed.append(r)
    db.conn.commit()
    cap = int(cfg.get("match.max_llm_scores_per_run", 150))
    to_score, later = passed[:cap], passed[cap:]
    queued = score_jobs(to_score, cfg, profile, llm, db)
    return {"new": len(new_rows), "filtered_by_rules": filtered, "scored": len(to_score),
            "left_for_next_run": len(later), "queued": queued}
