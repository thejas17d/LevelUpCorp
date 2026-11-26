"""Salary parsing: turn whatever a job board says into a min/max in LPA (INR lakhs per annum).

Examples handled:
  "₹8,00,000 - ₹12,00,000 a year"   -> (8, 12)
  "8-12 LPA" / "8 - 12 Lacs P.A."   -> (8, 12)
  "INR 15L - 25L"                   -> (15, 25)
  "₹60,000 - ₹90,000 a month"       -> (7.2, 10.8)
  "$80k - $120k" (USD per year)     -> converted with usd_inr
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

USD_INR = 84.0   # rough; override in config.yaml -> search.usd_inr
EUR_INR = 90.0
GBP_INR = 106.0

Range = Tuple[Optional[float], Optional[float]]


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_salary(text: str, usd_inr: float = USD_INR) -> Range:
    if not text:
        return None, None
    t = text.lower().replace("–", "-").replace("—", "-").replace(" to ", " - ")
    monthly = bool(re.search(r"per month|/month|a month|monthly|/mo\b|pm\b|p\.m\.", t))
    hourly = bool(re.search(r"per hour|/hour|an hour|hourly|/hr\b", t))

    currency = "inr"
    if "$" in t or "usd" in t:
        currency = "usd"
    elif "€" in t or "eur" in t:
        currency = "eur"
    elif "£" in t or "gbp" in t:
        currency = "gbp"

    # Numbers with an optional unit suffix (k, l/lakh/lac/lpa, cr, m)
    pat = r"(\d+(?:[.,]\d+)*)\s*(k|lpa|lakhs?|lacs?|l\b|cr|crores?|m\b|mn)?"
    found = [(m.group(1), (m.group(2) or "").strip()) for m in re.finditer(pat, t)]
    vals: list[float] = []
    shared_unit = next((u for _, u in reversed(found) if u), "")
    for raw, unit in found:
        try:
            v = _num(raw)
        except ValueError:
            continue
        unit = unit or shared_unit
        if unit == "k":
            v *= 1_000
        elif unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
            v *= 100_000
        elif unit in ("cr", "crore", "crores"):
            v *= 10_000_000
        elif unit in ("m", "mn"):
            v *= 1_000_000
        if v < 1:          # stray decimals like "0.5"
            continue
        vals.append(v)
    vals = [v for v in vals if v >= 50]   # drop small numbers like years of experience
    if not vals:
        return None, None

    lo, hi = min(vals[:2]), max(vals[:2])
    rate = {"inr": 1.0, "usd": usd_inr, "eur": EUR_INR, "gbp": GBP_INR}[currency]
    if hourly:
        lo, hi = lo * 2000, hi * 2000
    elif monthly:
        lo, hi = lo * 12, hi * 12
    elif currency == "inr" and hi < 1_00_000 and "lpa" not in t:
        # e.g. "60,000 - 90,000" with no period given: almost always monthly in India
        lo, hi = lo * 12, hi * 12
    lo_lpa = round(lo * rate / 100_000, 1)
    hi_lpa = round(hi * rate / 100_000, 1)
    if hi_lpa > 500:      # nonsense (probably parsed a phone number / id)
        return None, None
    return lo_lpa, hi_lpa


def meets_floor(min_lpa: Optional[float], max_lpa: Optional[float], floor: float) -> Optional[bool]:
    """True/False if we know, None if salary is unknown.

    A role passes if its *top* of range reaches the floor (an 6-10 LPA role can still pay 8+).
    """
    if max_lpa is None and min_lpa is None:
        return None
    top = max_lpa if max_lpa is not None else min_lpa
    return top >= floor
