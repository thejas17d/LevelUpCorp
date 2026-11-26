"""One full cycle: discover -> match -> apply -> check inbox -> notify -> report."""
from __future__ import annotations

import logging
import time

from levelup.config import Config
from levelup.db import DB
from levelup.llm import LLM

log = logging.getLogger(__name__)


def make_llm(cfg: Config) -> LLM:
    return LLM(model=cfg.get("llm.model", "claude-opus-5-5"), models=cfg.get("llm.per_task_model", {}) or {},
               provider=cfg.get("llm.provider", "auto"), chain=cfg.get("llm.chain") or None,
               max_output_tokens=int(cfg.get("llm.max_output_tokens", 16000)))


def run_cycle(cfg: Config, *, discover: bool = True, apply: bool = True, inbox: bool = True) -> dict:
    from levelup import inbox as inbox_mod
    from levelup import notify, report
    from levelup.apply import apply_queue
    from levelup.matcher import run_matching
    from levelup.resume import load_profile
    from levelup.sources import collect

    db = DB()
    llm = make_llm(cfg)
    profile = load_profile(cfg)
    run_id = db.start_run()
    stats: dict = {}
    t0 = time.time()

    if not cfg.dry_run:
        # Jobs that were only filled during dry runs get a real attempt now.
        db.conn.execute("UPDATE jobs SET status='queued' WHERE status='dry_run'")
        db.conn.commit()

    if discover:
        log.info("1/5 Discovering jobs...")
        jobs = collect(cfg, profile)
        stats["discovered"] = len(jobs)
        stats["new_jobs"] = db.upsert_jobs(jobs)
        log.info("    %s found, %s new", len(jobs), stats["new_jobs"])
        log.info("2/5 Matching against your profile...")
        stats["matching"] = run_matching(cfg, profile, llm, db)
        log.info("    %s", stats["matching"])
    if apply:
        mode = "DRY RUN (forms filled, not submitted)" if cfg.dry_run else "LIVE"
        log.info("3/5 Applying - %s ...", mode)
        stats["apply"] = apply_queue(cfg, profile, llm, db)
        log.info("    %s", stats["apply"])
    if inbox:
        log.info("4/5 Checking inbox for callbacks...")
        stats["inbox"] = inbox_mod.scan_inbox(cfg, llm, db)
        log.info("    %s", stats["inbox"])
    log.info("5/5 Notifications and report...")
    stats["alerts_sent"] = notify.send_callback_alerts(cfg, db)
    notify.send_daily_digest(cfg, db)
    stats["report"] = report.build_report(db)
    stats["llm_usage"] = llm.usage
    stats["minutes"] = round((time.time() - t0) / 60, 1)
    db.finish_run(run_id, stats)
    log.info("Done in %s min. Report: %s", stats["minutes"], stats["report"])
    return stats
