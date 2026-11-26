"""Shared data types."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Job:
    source: str                 # e.g. "greenhouse:razorpay", "remotive", "jobspy:naukri"
    title: str
    company: str
    url: str                    # job detail page
    apply_url: str = ""         # where the application form lives (may equal url)
    location: str = ""
    remote: bool = False
    description: str = ""       # plain text, truncated
    salary_text: str = ""       # raw salary string, if the source gave one
    salary_min_lpa: Optional[float] = None
    salary_max_lpa: Optional[float] = None
    posted_at: str = ""         # ISO date if known
    ats: str = ""               # greenhouse | lever | ashby | workable | smartrecruiters | recruitee | other
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable de-duplication key: same company + normalised title + location = same job."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
        basis = f"{norm(self.company)}|{norm(self.title)}|{norm(self.location)[:40]}"
        return hashlib.sha1(basis.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


def html_to_text(html: str, limit: int = 6000) -> str:
    """Cheap HTML -> text for job descriptions (no external dependency)."""
    import html as _html

    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit]
