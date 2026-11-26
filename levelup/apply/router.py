"""Decides HOW to apply to a job: Recruitee API, browser form-fill, or 'apply yourself' (assisted)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from levelup.sources.http import get

# Hosted ATS application forms the browser filler knows how to handle.
ATS_PATTERNS = {
    "greenhouse": r"(job-boards|boards)(\.eu)?\.greenhouse\.io|[?&]gh_jid=",
    "lever": r"jobs(\.eu)?\.lever\.co",
    "ashby": r"jobs\.ashbyhq\.com",
    "workable": r"apply\.workable\.com",
    "smartrecruiters": r"jobs\.smartrecruiters\.com",
    "recruitee": r"\.recruitee\.com",
}
# Platforms whose terms forbid bots, or multi-page portals that need an account: never automated.
ASSISTED_ONLY = r"linkedin\.com|naukri\.com|indeed\.|glassdoor\.|foundit\.|instahyre\.|cutshort\.io|wellfound\.com|angel\.co|myworkdayjobs\.com|workday\.com|taleo\.net|successfactors|icims\.com|oraclecloud\.com|darwinbox|keka\.com|zohorecruit|iimjobs|hirist|internshala"

ATS_LINK_RE = re.compile(
    r"https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/[^\s\"'<>]+|https?://jobs(?:\.eu)?\.lever\.co/[^\s\"'<>]+"
    r"|https?://jobs\.ashbyhq\.com/[^\s\"'<>]+|https?://apply\.workable\.com/[^\s\"'<>]+"
    r"|https?://[a-z0-9-]+\.recruitee\.com/o/[^\s\"'<>]+|https?://jobs\.smartrecruiters\.com/[^\s\"'<>]+"
)


def detect_ats(url: str) -> str:
    for name, pat in ATS_PATTERNS.items():
        if re.search(pat, url or "", re.I):
            return name
    return ""


def resolve_apply_url(url: str) -> str:
    """Aggregator pages (Remotive, Himalayas, HN...) link out to the real form. Follow that link."""
    if not url or detect_ats(url):
        return url
    try:
        r = get(url, timeout=20, allow_redirects=True)
    except Exception:
        return url
    if detect_ats(r.url):
        return r.url
    m = ATS_LINK_RE.search(r.text or "")
    return m.group(0).rstrip(".,);") if m else r.url


def to_form_url(url: str, ats: str) -> str:
    """Normalise a job URL to its application-form URL."""
    if ats == "lever" and not url.rstrip("/").endswith("/apply"):
        return url.rstrip("/") + "/apply"
    if ats == "ashby" and "/application" not in url:
        return url.rstrip("/") + "/application"
    if ats == "workable" and "/apply" not in url:
        return url.rstrip("/") + "/apply/"
    if ats == "greenhouse":
        # Boards that redirect to a company site (Coinbase, Stripe...) hide the form in an iframe;
        # Greenhouse's embed URL always serves the plain application form.
        b = re.search(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
        if b and b.group(1) != "embed":
            return f"https://job-boards.greenhouse.io/embed/job_app?for={b.group(1)}&token={b.group(2)}"
        m = re.search(r"[?&]gh_jid=(\d+)", url)
        host = urlparse(url).netloc
        if m and "greenhouse.io" not in host:
            return url  # embedded on the company site; the filler handles the iframe
    return url


def plan(job) -> tuple[str, str]:
    """Return (method, form_url). method: recruitee_api | browser | assisted."""
    extra = job["extra"] if isinstance(job["extra"], dict) else {}
    url = job["apply_url"] or job["url"]
    if re.search(ASSISTED_ONLY, url or "", re.I):
        return "assisted", url
    if job["ats"] == "recruitee" and extra.get("offer_id"):
        return "recruitee_api", url
    if not detect_ats(url):
        url = resolve_apply_url(url)
    ats = detect_ats(url)
    if re.search(ASSISTED_ONLY, url or "", re.I) or not ats:
        return "assisted", url
    return "browser", to_form_url(url, ats)
