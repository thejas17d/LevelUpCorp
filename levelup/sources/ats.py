"""Company career pages, read through the public JSON feeds of the ATS each company uses.

No scraping, no login: Greenhouse, Lever, Ashby, Workable, SmartRecruiters and Recruitee
all publish job lists as JSON. The companies to watch are listed in companies.yaml.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yaml

from levelup.config import ROOT, Config
from levelup.models import Job, html_to_text
from levelup.salary import parse_salary
from levelup.sources.http import get, post

log = logging.getLogger(__name__)


def _iso(ts) -> str:
    if ts in (None, ""):
        return ""
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return str(ts)[:10]


def greenhouse(name: str, token: str, cfg: Config) -> list[Job]:
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job(
            source=f"greenhouse:{token}", title=j.get("title", ""), company=name,
            url=j.get("absolute_url", ""),
            # Always apply on Greenhouse's own hosted page (company sites often iframe it).
            apply_url=f"https://job-boards.greenhouse.io/{token}/jobs/{j['id']}",
            location=loc, remote="remote" in loc.lower(),
            description=html_to_text(j.get("content", "")), posted_at=_iso(j.get("updated_at")),
            ats="greenhouse", extra={"gh_token": token, "gh_id": j["id"]},
        ))
    return out


def lever(name: str, site: str, cfg: Config) -> list[Job]:
    base = "https://api.eu.lever.co" if cfg.get(f"lever_eu.{site}") else "https://api.lever.co"
    r = get(f"{base}/v0/postings/{site}", params={"mode": "json"})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json():
        cat = j.get("categories") or {}
        loc = cat.get("location", "") or ", ".join(cat.get("allLocations", []) or [])
        sr = j.get("salaryRange") or {}
        smin = smax = None
        stext = ""
        if sr.get("min"):
            stext = f"{sr.get('currency','')} {sr.get('min')} - {sr.get('max')} {sr.get('interval','')}"
            smin, smax = parse_salary(stext, cfg.get("search.usd_inr", 84))
        out.append(Job(
            source=f"lever:{site}", title=j.get("text", ""), company=name, url=j.get("hostedUrl", ""),
            apply_url=j.get("applyUrl") or (j.get("hostedUrl", "") + "/apply"),
            location=loc, remote=(j.get("workplaceType") == "remote") or "remote" in loc.lower(),
            description=(j.get("descriptionPlain") or "")[:6000] + "\n" + " ".join(
                html_to_text(l.get("content", ""), 1500) for l in j.get("lists", [])),
            salary_text=stext, salary_min_lpa=smin, salary_max_lpa=smax,
            posted_at=_iso(j.get("createdAt")), ats="lever", extra={"lever_site": site, "lever_id": j.get("id")},
        ))
    return out


def ashby(name: str, org: str, cfg: Config) -> list[Job]:
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", params={"includeCompensation": "true"})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        smin, smax = parse_salary(comp, cfg.get("search.usd_inr", 84)) if comp else (None, None)
        loc = j.get("location", "") or ""
        out.append(Job(
            source=f"ashby:{org}", title=j.get("title", ""), company=name, url=j.get("jobUrl", ""),
            apply_url=j.get("applyUrl") or (j.get("jobUrl", "") + "/application"),
            location=loc, remote=bool(j.get("isRemote")),
            description=(j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")))[:6000],
            salary_text=comp, salary_min_lpa=smin, salary_max_lpa=smax,
            posted_at=_iso(j.get("publishedAt")), ats="ashby", extra={"ashby_org": org},
        ))
    return out


def workable(name: str, sub: str, cfg: Config) -> list[Job]:
    r = post(f"https://apply.workable.com/api/v3/accounts/{sub}/jobs", json={})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("results", []):
        loc_d = j.get("location") or {}
        loc = ", ".join(x for x in [loc_d.get("city"), loc_d.get("region"), loc_d.get("country")] if x)
        code = j.get("shortcode")
        url = f"https://apply.workable.com/{sub}/j/{code}/"
        out.append(Job(
            source=f"workable:{sub}", title=j.get("title", ""), company=name, url=url,
            apply_url=url + "apply/", location=loc, remote=bool(j.get("remote")) or j.get("workplace") == "remote",
            posted_at=_iso(j.get("published")), ats="workable", extra={"workable_sub": sub, "shortcode": code},
        ))
    return out


def workday(name: str, token: str, cfg: Config) -> list[Job]:
    """Workday career sites expose an (undocumented) JSON search. Discovery only - applying needs an account."""
    host, _, site = token.partition("/")
    tenant = host.split(".")[0]
    base = f"https://{host}.myworkdayjobs.com"
    out = []
    # Big global employers list thousands of jobs; search for India so the first pages are the relevant ones.
    search = cfg.get("sources.workday_search_text", "India")
    for offset in (0, 20, 40, 60, 80):
        r = post(f"{base}/wday/cxs/{tenant}/{site}/jobs", json={"limit": 20, "offset": offset, "searchText": search})
        if r.status_code != 200:
            break
        postings = r.json().get("jobPostings", [])
        for j in postings:
            path = j.get("externalPath", "")
            out.append(Job(
                source=f"workday:{tenant}", title=j.get("title", ""), company=name, url=f"{base}/{site}{path}",
                location=j.get("locationsText", ""), remote="remote" in (j.get("locationsText", "") or "").lower(),
                posted_at="", ats="workday",
            ))
        if len(postings) < 20:
            break
    return out


def smartrecruiters(name: str, company_id: str, cfg: Config) -> list[Job]:
    r = get(f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings", params={"limit": 100, "country": "in"})
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("content", []):
        loc_d = j.get("location") or {}
        loc = ", ".join(x for x in [loc_d.get("city"), loc_d.get("country")] if x)
        url = f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id')}"
        out.append(Job(
            source=f"smartrecruiters:{company_id}", title=j.get("name", ""), company=name, url=url, apply_url=url,
            location=loc, remote=bool(loc_d.get("remote")), posted_at=_iso(j.get("releasedDate")),
            ats="smartrecruiters", extra={"sr_id": j.get("id")},
        ))
    return out


def recruitee(name: str, sub: str, cfg: Config) -> list[Job]:
    r = get(f"https://{sub}.recruitee.com/api/offers/")
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("offers", []):
        sal = j.get("salary") or {}
        stext, smin, smax = "", None, None
        if sal.get("min"):
            stext = f"{sal.get('currency','')} {sal.get('min')} - {sal.get('max')} {sal.get('period','')}"
            smin, smax = parse_salary(stext, cfg.get("search.usd_inr", 84))
        out.append(Job(
            source=f"recruitee:{sub}", title=j.get("title", ""), company=name, url=j.get("careers_url", ""),
            apply_url=j.get("careers_apply_url") or j.get("careers_url", ""),
            location=j.get("location", "") or "", remote=bool(j.get("remote")),
            description=html_to_text((j.get("description") or "") + (j.get("requirements") or "")),
            salary_text=stext, salary_min_lpa=smin, salary_max_lpa=smax, posted_at=_iso(j.get("published_at")),
            ats="recruitee", extra={"recruitee_sub": sub, "offer_id": j.get("id"), "slug": j.get("slug"),
                                    "open_questions": j.get("open_questions", [])},
        ))
    return out


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable,
            "smartrecruiters": smartrecruiters, "recruitee": recruitee, "workday": workday}


def load_companies() -> list[dict]:
    path = ROOT / "companies.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [c for c in data.get("companies", []) if c.get("ats") in FETCHERS and c.get("token")]


def fetch_all_companies(cfg: Config) -> list[Job]:
    companies = load_companies()

    def one(c: dict) -> list[Job]:
        try:
            return FETCHERS[c["ats"]](c["name"], c["token"], cfg)
        except Exception as e:
            log.debug("career page %s (%s) failed: %s", c["name"], c["ats"], e)
            return []

    jobs: list[Job] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for got in pool.map(one, companies):
            jobs.extend(got)
    return jobs


def greenhouse_questions(token: str, job_id) -> list[dict]:
    """Exact application-form fields for a Greenhouse job (labels, field names, types, options)."""
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}", params={"questions": "true"})
    if r.status_code != 200:
        return []
    return r.json().get("questions", [])


def recruitee_submit(sub: str, offer_id, fields: dict, cv_path: str) -> tuple[bool, str]:
    """Recruitee's public candidate endpoint (no auth until Feb 2027). Returns (ok, message)."""
    import requests

    url = f"https://{sub}.recruitee.com/api/offers/{offer_id}/candidates"
    with open(cv_path, "rb") as fh:
        r = requests.post(url, data=fields, files={"candidate[cv]": fh}, timeout=60)
    return (r.status_code in (200, 201)), f"HTTP {r.status_code}: {r.text[:200]}"
