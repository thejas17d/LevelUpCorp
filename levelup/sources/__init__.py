"""Job discovery: pulls jobs from every enabled source in parallel."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable

from levelup.config import DATA_DIR, Config
from levelup.models import Job

log = logging.getLogger(__name__)


def search_terms(cfg: Config, profile: dict) -> list[str]:
    terms = cfg.get("search.keywords") or profile.get("target_titles", [])[:6]
    return [t for t in dict.fromkeys(terms) if t][:8]


# Minimum hours between calls, to respect each source's published limits
# (Remotive: max 4 calls/day; Jooble free key: 100 requests/day; LinkedIn rate-limits bursts).
MIN_HOURS = {"remotive": 6, "jooble": 6, "jobspy": 6, "hn_hiring": 12, "arbeitnow": 6}


def _due(name: str, state: dict) -> bool:
    last = state.get("source_last_run", {}).get(name)
    if not last:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=MIN_HOURS.get(name, 0))


def collect(cfg: Config, profile: dict) -> list[Job]:
    from levelup.sources import ats, boards, jobspy_source

    terms = search_terms(cfg, profile)
    state_path = DATA_DIR / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    tasks: list[tuple[str, Callable[[], list[Job]]]] = []

    if cfg.get("sources.company_career_pages", True):
        tasks.append(("company career pages", lambda: ats.fetch_all_companies(cfg)))
    enabled = cfg.get("sources.boards", {}) or {}
    for name, fn in boards.BOARD_FUNCS.items():
        if enabled.get(name, True) and _due(name, state):
            tasks.append((name, (lambda f=fn: f(cfg, terms))))
    if cfg.get("sources.jobspy.enabled", False) and _due("jobspy", state):
        tasks.append(("jobspy", lambda: jobspy_source.fetch(cfg, terms)))
    now = datetime.now(timezone.utc).isoformat()
    state.setdefault("source_last_run", {}).update({n: now for n, _ in tasks if n in MIN_HOURS})
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    jobs: list[Job] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                got = fut.result()
                log.info("  %-22s %4d jobs", name, len(got))
                jobs.extend(got)
            except Exception as e:  # one broken source must never stop the run
                log.warning("  %-22s failed: %s", name, e)
    return jobs
