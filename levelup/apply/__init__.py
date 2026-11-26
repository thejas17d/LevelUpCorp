"""Works through the queue of matched jobs and applies, respecting the daily cap and pacing."""
from __future__ import annotations

import json
import logging
import random
import time

from levelup.apply.router import plan
from levelup.config import Config
from levelup.db import DB
from levelup.llm import LLM, LLMError

log = logging.getLogger(__name__)


def _row(job) -> dict:
    d = dict(job)
    try:
        d["extra"] = json.loads(d.get("extra") or "{}")
    except (TypeError, json.JSONDecodeError):
        d["extra"] = {}
    return d


def _apply_recruitee(job: dict, profile: dict, llm: LLM, cfg: Config) -> dict:
    """Recruitee's public candidate API: a real submission without a browser."""
    from levelup.apply.browser import answer_fields
    from levelup.sources.ats import recruitee_submit

    ex = job["extra"]
    qs = ex.get("open_questions") or []
    fields = []
    for q in qs:
        kind = {"single_choice": "radio", "multi_choice": "checkbox_group", "boolean": "checkbox",
                "text": "textarea"}.get(q.get("kind"), "text")
        if q.get("kind") == "file":
            continue
        opts = [{"label": o.get("body", ""), "fid": str(o.get("id"))} for o in q.get("open_question_options", [])]
        fields.append({"fid": str(q.get("id")), "kind": kind, "label": q.get("body", ""), "required": bool(q.get("required")),
                       **({"options": opts} if opts else {})})
    answers, _ = answer_fields(fields, job, profile, llm, cfg) if fields else ({}, "")
    missing = [f["label"] for f in fields if f["required"] and answers.get(f["fid"], {}).get("source") == "unknown"]
    if missing:
        return {"status": "needs_review", "notes": "no truthful answer for: " + "; ".join(missing)[:500], "answers": answers}
    data = {"candidate[name]": profile.get("full_name", ""), "candidate[email]": profile.get("email", ""),
            "candidate[phone]": profile.get("phone", "")}
    for i, f in enumerate(fields):
        a = answers.get(f["fid"], {}).get("value", "")
        base = f"candidate[open_question_answers_attributes][{i}]"
        data[f"{base}[open_question_id]"] = f["fid"]
        if f["kind"] == "checkbox":
            data[f"{base}[flag]"] = "true" if a.lower() == "true" else "false"
        elif f.get("options"):
            ids = [o["fid"] for o in f["options"] if o["label"].strip().lower() in [x.strip().lower() for x in a.split("||")]]
            data[f"{base}[multi_content][]"] = ids
        else:
            data[f"{base}[content]"] = a
    if cfg.dry_run:
        return {"status": "dry_run", "notes": "Recruitee API payload prepared; not sent (dry_run)", "answers": data}
    ok, msg = recruitee_submit(ex["recruitee_sub"], ex["offer_id"], data, profile.get("resume_path", ""))
    return {"status": "submitted" if ok else "failed", "notes": msg, "answers": data}


def apply_queue(cfg: Config, profile: dict, llm: LLM, db: DB) -> dict:
    stats = {"submitted": 0, "dry_run": 0, "needs_review": 0, "assisted": 0, "failed": 0}
    remaining = cfg.daily_cap - db.applications_today()
    if remaining <= 0:
        log.info("Daily cap of %s applications reached; applying again tomorrow.", cfg.daily_cap)
        return stats
    queue = [_row(j) for j in db.queued_jobs(limit=remaining * 3)]
    if not queue:
        return stats

    browser = None
    done = 0
    companies_today: set[str] = set()
    new_assisted: list = []
    try:
        for job in queue:
            if done >= remaining:
                break
            company = (job["company"] or "").lower()
            if company in companies_today:
                continue  # at most one application per company per run
            method, url = plan(job)
            log.info("  [%s] %s - %s  (score %s)", method, job["company"], job["title"], job.get("score"))
            if method == "assisted":
                db.set_status(job["key"], "assisted", url)
                stats["assisted"] += 1
                new_assisted.append((job, url))
                continue
            try:
                if method == "recruitee_api":
                    res = _apply_recruitee(job, profile, llm, cfg)
                else:
                    if browser is None:
                        from levelup.apply.browser import BrowserApplier
                        browser = BrowserApplier(cfg, profile, llm)
                    res = browser.apply(job, url)
            except LLMError as e:
                res = {"status": "failed", "notes": str(e)}
            status = res["status"]
            db.log_application(job["key"], status, method, res.get("notes", ""), res.get("cover_letter", ""),
                               res.get("answers"), res.get("screenshot", ""))
            job_status = {"submitted": "applied", "dry_run": "dry_run", "needs_review": "needs_review"}.get(status, "failed")
            db.set_status(job["key"], job_status, res.get("notes", ""))
            stats[status if status in stats else "failed"] += 1
            if status == "needs_review" and not cfg.dry_run:
                from levelup.notify import telegram
                telegram(f"Needs you - {job['company']}: {job['title']}\n{res.get('notes', '')[:300]}\n"
                         f"Apply yourself: {url}")
            log.info("     -> %s %s", status, ("(" + res.get("notes", "")[:120] + ")") if res.get("notes") else "")
            if status in ("submitted", "dry_run"):
                done += 1
                companies_today.add(company)
            lo, hi = cfg.get("apply.pause_between_seconds", [40, 120])
            time.sleep(random.uniform(float(lo), float(hi)) if status == "submitted" else 3)
    finally:
        if browser:
            browser.close()
        if any(stats.values()):
            from levelup.notify import telegram
            telegram("LevelUp run done - " + ", ".join(f"{k}: {v}" for k, v in stats.items() if v)
                     + (" (DRY RUN, nothing submitted)" if cfg.dry_run else ""))
            if new_assisted and not cfg.dry_run:
                top = sorted(new_assisted, key=lambda x: -(x[0].get("score") or 0))[:20]
                telegram(f"New apply-yourself jobs ({len(new_assisted)}):\n\n" + "\n\n".join(
                    f"{j['company']} - {j['title']} ({(j['location'] or '')[:25]}) · fit {j.get('score')}\n{u}" for j, u in top))
    return stats


def review_queue(cfg: Config, profile: dict, llm: LLM, db: DB, limit: int = 10) -> dict:
    """Open needs_review jobs one by one so the user can finish them in the browser."""
    from levelup.apply.browser import BrowserApplier

    rows = [_row(j) for j in db.jobs_with_status("needs_review", limit=limit)]
    stats = {"submitted": 0, "skipped": 0, "needs_review": 0}
    if not rows:
        return stats
    browser = BrowserApplier(cfg, profile, llm)
    try:
        for job in rows:
            method, url = plan(job)
            if method == "assisted":
                continue
            outcome = browser.review(job, url)
            db.log_application(job["key"], outcome, "manual_review")
            db.set_status(job["key"], {"submitted": "applied", "skipped": "skipped"}.get(outcome, "needs_review"))
            stats[outcome] = stats.get(outcome, 0) + 1
    finally:
        browser.close()
    return stats
