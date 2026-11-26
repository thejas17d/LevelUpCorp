"""LinkedIn / Indeed / Naukri / Glassdoor discovery through python-jobspy (optional).

DISCOVERY ONLY. These platforms forbid automated applying in their terms and ban
accounts that do it, so LevelUpCorp never logs in to them and never submits there.
If a listing links out to a company ATS (job_url_direct), the tool applies on the
company's own form instead; otherwise the job goes to your "apply yourself" list.

Install with:  pip install python-jobspy   (see HANDOFF.md, optional step)
"""
from __future__ import annotations

import logging
import math
import time

from levelup.config import Config
from levelup.models import Job

log = logging.getLogger(__name__)


def _clean(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        pass
    return v


def fetch(cfg: Config, terms: list[str]) -> list[Job]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.warning("python-jobspy not installed; skipping LinkedIn/Indeed/Naukri discovery")
        return []

    sites = cfg.get("sources.jobspy.sites", ["indeed", "linkedin", "naukri", "glassdoor"])
    location = cfg.get("sources.jobspy.location", "India")
    hours_old = int(cfg.get("search.max_age_days", 14)) * 24
    per_term = int(cfg.get("sources.jobspy.results_per_term", 40))
    out: list[Job] = []
    for term in terms[:5]:
        try:
            df = scrape_jobs(site_name=sites, search_term=term, location=location, results_wanted=per_term,
                             hours_old=hours_old, country_indeed="India", linkedin_fetch_description=False)
        except Exception as e:
            log.warning("jobspy '%s' failed: %s", term, e)
            continue
        for row in df.to_dict("records"):
            lo, hi = _clean(row.get("min_amount")), _clean(row.get("max_amount"))
            interval = (_clean(row.get("interval")) or "yearly").lower()
            cur = (_clean(row.get("currency")) or "INR").upper()
            mult = {"yearly": 1, "monthly": 12, "weekly": 52, "daily": 260, "hourly": 2000}.get(interval, 1)
            rate = float(cfg.get("search.usd_inr", 84)) if cur == "USD" else 1.0
            smin = round(lo * mult * rate / 100_000, 1) if lo else None
            smax = round(hi * mult * rate / 100_000, 1) if hi else None
            direct = _clean(row.get("job_url_direct")) or ""
            out.append(Job(
                source=f"jobspy:{row.get('site')}", title=str(row.get("title") or ""),
                company=str(_clean(row.get("company")) or ""), url=str(row.get("job_url") or ""),
                apply_url=str(direct), location=str(_clean(row.get("location")) or ""),
                remote=bool(_clean(row.get("is_remote"))), description=str(_clean(row.get("description")) or "")[:6000],
                salary_text=f"{cur} {lo}-{hi} {interval}" if lo else "", salary_min_lpa=smin, salary_max_lpa=smax,
                posted_at=str(_clean(row.get("date_posted")) or "")[:10],
            ))
        time.sleep(5)  # be gentle; LinkedIn rate-limits bursts
    return out
