"""Offline tests: salary parsing, apply routing, rule filter. Run:  python -m pytest -q  (or python tests/test_core.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from levelup.apply.router import detect_ats, plan, to_form_url
from levelup.config import Config
from levelup.matcher import rule_filter
from levelup.salary import meets_floor, parse_salary


def test_salary_formats():
    assert parse_salary("₹8,00,000 - ₹12,00,000 a year") == (8.0, 12.0)
    assert parse_salary("8-12 LPA") == (8.0, 12.0)
    assert parse_salary("12-18 Lacs P.A.") == (12.0, 18.0)
    assert parse_salary("INR 15L - 25L") == (15.0, 25.0)
    assert parse_salary("₹60,000 - ₹90,000 a month") == (7.2, 10.8)
    lo, hi = parse_salary("$80k - $120k", usd_inr=84)
    assert (lo, hi) == (67.2, 100.8)
    assert parse_salary("Not disclosed") == (None, None)
    assert parse_salary("") == (None, None)


def test_floor():
    assert meets_floor(6, 10, 8) is True        # top of range reaches the floor
    assert meets_floor(4, 6, 8) is False
    assert meets_floor(None, None, 8) is None


def test_router():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/cred/abc") == "lever"
    assert detect_ats("https://www.linkedin.com/jobs/view/1") == ""
    assert to_form_url("https://jobs.lever.co/cred/abc", "lever").endswith("/apply")
    assert to_form_url("https://jobs.ashbyhq.com/sarvam/x", "ashby").endswith("/application")
    job = {"apply_url": "https://www.naukri.com/job-listings-x", "url": "", "ats": "", "extra": {}}
    assert plan(job)[0] == "assisted"
    job = {"apply_url": "https://acme.wd1.myworkdayjobs.com/careers/job/x", "url": "", "ats": "workday", "extra": {}}
    assert plan(job)[0] == "assisted"
    job = {"apply_url": "https://job-boards.greenhouse.io/acme/jobs/1", "url": "", "ats": "greenhouse", "extra": {}}
    assert plan(job) == ("browser", "https://job-boards.greenhouse.io/acme/jobs/1")


class _FakeDB:
    def company_application_count(self, company, days):
        return 0


def _job(**kw):
    base = {"title": "Python Developer", "location": "Bengaluru, India", "description": "", "remote": 0,
            "posted_at": "", "salary_min_lpa": None, "salary_max_lpa": None, "company": "Acme"}
    base.update(kw)
    return base


def test_rule_filter():
    cfg = Config(raw={"search": {"min_salary_lpa": 8, "title_must_include": ["developer", "engineer", "ml", "ai"],
                                 "title_exclude": ["manager"], "remote_ok": True}})
    prof = {"total_experience_years": 2}
    db = _FakeDB()
    assert rule_filter(_job(), cfg, prof, db) == ""
    assert rule_filter(_job(title="HTML Content Writer"), cfg, prof, db) == "title not a target role"  # 'ml' is whole-word
    assert rule_filter(_job(title="ML Engineer"), cfg, prof, db) == ""
    assert rule_filter(_job(title="Engineering Manager"), cfg, prof, db) == "title excluded"
    assert rule_filter(_job(title="Senior Software Engineer"), cfg, prof, db) == "too senior for current experience"
    assert rule_filter(_job(location="Berlin, Germany"), cfg, prof, db) == "location outside India"
    assert rule_filter(_job(location="Remote - US only", remote=1), cfg, prof, db).startswith("remote but restricted")
    assert rule_filter(_job(location="Remote (Worldwide)", remote=1), cfg, prof, db) == ""
    assert rule_filter(_job(salary_min_lpa=4, salary_max_lpa=6), cfg, prof, db) == "salary below 8.0 LPA"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
