"""Shared HTTP session with a polite User-Agent, timeouts and simple retries."""
from __future__ import annotations

import time

import requests

UA = "LevelUpCorp/0.1 (personal job search tool)"
_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept": "application/json"})


def get(url: str, *, params: dict | None = None, timeout: int = 30, tries: int = 3, **kw) -> requests.Response:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=timeout, **kw)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    if last:
        raise last
    return r  # type: ignore[possibly-undefined]


def post(url: str, *, json: dict | None = None, timeout: int = 30, **kw) -> requests.Response:
    return _session.post(url, json=json, timeout=timeout, **kw)
