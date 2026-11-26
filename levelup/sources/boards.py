"""Job boards and aggregators with public APIs or feeds.

Free, no key:  Remotive, RemoteOK, Himalayas, Jobicy, Arbeitnow, Hacker News "Who is hiring".
Free key:      Adzuna (India), Jooble - set the keys in .env to enable them.

Every function takes (cfg, search_terms) and returns a list of Job. A failing board
never stops the run (the caller catches errors).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from levelup.config import Config
from levelup.models import Job, html_to_text
from levelup.salary import parse_salary
from levelup.sources.http import get, post


def _usd(cfg: Config) -> float:
    return float(cfg.get("search.usd_inr", 84))


def _fmt_range(lo, hi, cur="USD", period="year") -> str:
    if not lo and not hi:
        return ""
    return f"{cur} {lo or ''} - {hi or ''} per {period}"


def remotive(cfg: Config, terms: list[str]) -> list[Job]:
    r = get("https://remotive.com/api/remote-jobs", params={"category": "software-dev", "limit": 300})
    out = []
    for j in r.json().get("jobs", []):
        smin, smax = parse_salary(j.get("salary", ""), _usd(cfg))
        out.append(Job(
            source="remotive", title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
            location=j.get("candidate_required_location", ""), remote=True,
            description=html_to_text(j.get("description", "")), salary_text=j.get("salary", ""),
            salary_min_lpa=smin, salary_max_lpa=smax, posted_at=str(j.get("publication_date", ""))[:10],
        ))
    return out


def remoteok(cfg: Config, terms: list[str]) -> list[Job]:
    r = get("https://remoteok.com/api")
    out = []
    for j in r.json()[1:]:  # first element is a legal notice
        if not isinstance(j, dict) or not j.get("position"):
            continue
        stext = _fmt_range(j.get("salary_min"), j.get("salary_max"))
        smin, smax = parse_salary(stext, _usd(cfg)) if stext else (None, None)
        out.append(Job(
            source="remoteok", title=j.get("position", ""), company=j.get("company", ""),
            url=j.get("url", ""), apply_url=j.get("apply_url") or j.get("url", ""),
            location=j.get("location", "") or "Worldwide", remote=True,
            description=html_to_text(j.get("description", "")), salary_text=stext,
            salary_min_lpa=smin, salary_max_lpa=smax, posted_at=str(j.get("date", ""))[:10],
        ))
    return out


def himalayas(cfg: Config, terms: list[str]) -> list[Job]:
    """Himalayas search API, filtered to roles open to candidates in India."""
    out = []
    for term in terms[:5]:
        r = get("https://himalayas.app/jobs/api/search", params={"q": term, "country": "India", "sort": "recent", "page": 1})
        if r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            cur = j.get("currency") or "USD"
            stext = _fmt_range(j.get("minSalary"), j.get("maxSalary"), cur)
            smin, smax = parse_salary(stext, _usd(cfg)) if stext else (None, None)
            locs = j.get("locationRestrictions") or []
            out.append(Job(
                source="himalayas", title=j.get("title", ""), company=j.get("companyName", ""),
                url=j.get("applicationLink") or j.get("guid", ""), location=", ".join(locs) or "Worldwide",
                remote=True, description=html_to_text(j.get("description", "")), salary_text=stext,
                salary_min_lpa=smin, salary_max_lpa=smax,
                posted_at=datetime.fromtimestamp(j["pubDate"], tz=timezone.utc).date().isoformat()
                if isinstance(j.get("pubDate"), (int, float)) else str(j.get("pubDate", ""))[:10],
            ))
    return out


def jobicy(cfg: Config, terms: list[str]) -> list[Job]:
    out = []
    for geo in ("apac", "anywhere"):   # Jobicy has no 'india' geo (returns HTTP 400)
        params = {"count": 50, "industry": "dev", "geo": geo}
        r = get("https://jobicy.com/api/v2/remote-jobs", params=params)
        if r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            stext = _fmt_range(j.get("annualSalaryMin"), j.get("annualSalaryMax"), j.get("salaryCurrency") or "USD")
            smin, smax = parse_salary(stext, _usd(cfg)) if stext else (None, None)
            out.append(Job(
                source="jobicy", title=j.get("jobTitle", ""), company=j.get("companyName", ""), url=j.get("url", ""),
                location=j.get("jobGeo", ""), remote=True, description=html_to_text(j.get("jobDescription", "")),
                salary_text=stext, salary_min_lpa=smin, salary_max_lpa=smax, posted_at=str(j.get("pubDate", ""))[:10],
            ))
    return out


def arbeitnow(cfg: Config, terms: list[str]) -> list[Job]:
    r = get("https://www.arbeitnow.com/api/job-board-api")
    out = []
    for j in r.json().get("data", []):
        if not j.get("remote"):
            continue  # mostly EU on-site roles; only remote ones are relevant from India
        out.append(Job(
            source="arbeitnow", title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
            location=j.get("location", ""), remote=True, description=html_to_text(j.get("description", "")),
            posted_at=datetime.fromtimestamp(j.get("created_at", 0), tz=timezone.utc).date().isoformat(),
        ))
    return out


def hn_hiring(cfg: Config, terms: list[str]) -> list[Job]:
    """Latest 'Ask HN: Who is hiring?' thread; keeps posts mentioning India or worldwide remote."""
    s = get("https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 3}).json()
    hits = [h for h in s.get("hits", []) if "who is hiring" in h.get("title", "").lower()]
    if not hits:
        return []
    story = get(f"https://hn.algolia.com/api/v1/items/{hits[0]['objectID']}").json()
    out = []
    for c in story.get("children", []):
        text = html_to_text(c.get("text") or "", 4000)
        if not text or not re.search(r"\b(india|bangalore|bengaluru|hyderabad|pune|remote \(global|worldwide|anywhere)\b", text, re.I):
            continue
        first = text.split("\n")[0]
        parts = [p.strip() for p in first.split("|")]
        urls = re.findall(r"https?://[^\s)\"']+", text)
        out.append(Job(
            source="hn_hiring", title=parts[1] if len(parts) > 1 else first[:80], company=parts[0][:80],
            url=f"https://news.ycombinator.com/item?id={c.get('id')}", apply_url=urls[0] if urls else "",
            location=" | ".join(parts[2:4]), remote="remote" in first.lower(), description=text,
            posted_at=str(c.get("created_at", ""))[:10],
        ))
    return out


def adzuna(cfg: Config, terms: list[str]) -> list[Job]:
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    out = []
    floor_inr = int(cfg.min_lpa * 100_000)
    for term in terms[:5]:
        r = get("https://api.adzuna.com/v1/api/jobs/in/search/1", params={
            "app_id": app_id, "app_key": app_key, "what": term, "results_per_page": 50,
            "max_days_old": int(cfg.get("search.max_age_days", 14)), "content-type": "application/json",
        })
        if r.status_code != 200:
            continue
        for j in r.json().get("results", []):
            lo, hi = j.get("salary_min"), j.get("salary_max")
            predicted = str(j.get("salary_is_predicted", "0")) == "1"
            smin = round(lo / 100_000, 1) if lo else None
            smax = round(hi / 100_000, 1) if hi else None
            if hi and hi < floor_inr and not predicted:
                continue
            out.append(Job(
                source="adzuna", title=j.get("title", ""), company=(j.get("company") or {}).get("display_name", ""),
                url=j.get("redirect_url", ""), location=(j.get("location") or {}).get("display_name", ""),
                description=html_to_text(j.get("description", "")),
                salary_text=f"INR {lo}-{hi} per year{' (estimated by Adzuna)' if predicted else ''}" if lo else "",
                salary_min_lpa=None if predicted else smin, salary_max_lpa=None if predicted else smax,
                posted_at=str(j.get("created", ""))[:10],
            ))
    return out


def jooble(cfg: Config, terms: list[str]) -> list[Job]:
    key = os.getenv("JOOBLE_API_KEY")
    if not key:
        return []
    # Jooble keys are per country site; a key from jooble.org returns US jobs only.
    host = os.getenv("JOOBLE_HOST", "in.jooble.org")
    out = []
    for term in terms[:5]:   # free tier: 100 requests/day
        r = post(f"https://{host}/api/{key}", json={"keywords": term, "location": "India"})
        if r.status_code != 200:
            continue
        for j in r.json().get("jobs", []):
            smin, smax = parse_salary(j.get("salary", ""), _usd(cfg))
            out.append(Job(
                source="jooble", title=j.get("title", ""), company=j.get("company", ""), url=j.get("link", ""),
                location=j.get("location", ""), description=html_to_text(j.get("snippet", "")),
                salary_text=j.get("salary", ""), salary_min_lpa=smin, salary_max_lpa=smax,
                posted_at=str(j.get("updated", ""))[:10],
            ))
    return out


BOARD_FUNCS = {
    "remotive": remotive, "remoteok": remoteok, "himalayas": himalayas, "jobicy": jobicy,
    "arbeitnow": arbeitnow, "hn_hiring": hn_hiring, "adzuna": adzuna, "jooble": jooble,
}
