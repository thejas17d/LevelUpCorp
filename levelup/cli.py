"""Command line entry point.

    python -m levelup setup --resume "C:\\path\\resume.pdf"   read resume -> data/profile.json
    python -m levelup run                                     keep going: a full cycle every N hours
    python -m levelup run --once                              one full cycle, then exit
    python -m levelup discover                                only find + score jobs (no applying)
    python -m levelup review                                  finish the jobs that need you (CAPTCHA, missing answers)
    python -m levelup inbox                                   only check email for callbacks
    python -m levelup status                                  counts + open the report
    python -m levelup doctor                                  check that everything is configured
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import webbrowser

from levelup.config import DATA_DIR, ROOT, load_config


def _setup_logging(verbose: bool) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(message)s", datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(DATA_DIR / "levelup.log", encoding="utf-8")],
    )
    for noisy in ("httpx", "httpx2", "urllib3", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_setup(args, cfg) -> None:
    from levelup.pipeline import make_llm
    from levelup.resume import PROFILE_PATH, build_profile

    profile = build_profile(args.resume, make_llm(cfg))
    print(f"\nProfile saved to {PROFILE_PATH}")
    print(f"  Name: {profile['full_name']} | {profile['total_experience_years']} yrs | {profile['seniority']}")
    print(f"  Stack: {', '.join(profile['primary_stack'])}")
    print(f"  Will search for: {', '.join(profile['target_titles'])}")
    print("\nOpen data/profile.json and fix anything wrong - every application is built from it.")


def cmd_run(args, cfg) -> None:
    from levelup.pipeline import run_cycle

    hours = float(cfg.get("schedule.every_hours", 4))
    while True:
        try:
            run_cycle(cfg, discover=not args.no_discover, apply=not args.no_apply)
        except SystemExit:
            raise
        except Exception as e:  # keep the loop alive; the error is in data/levelup.log
            logging.exception("Cycle failed: %s", e)
        if args.once:
            return
        logging.info("Sleeping %.1f hours until the next cycle (Ctrl+C to stop).", hours)
        time.sleep(hours * 3600)


def cmd_discover(args, cfg) -> None:
    from levelup.pipeline import run_cycle
    run_cycle(cfg, discover=True, apply=False, inbox=False)


def cmd_review(args, cfg) -> None:
    from levelup.apply import review_queue
    from levelup.db import DB
    from levelup.pipeline import make_llm
    from levelup.resume import load_profile

    print(review_queue(cfg, load_profile(cfg), make_llm(cfg), DB(), limit=args.limit))


def cmd_inbox(args, cfg) -> None:
    from levelup import inbox, notify
    from levelup.db import DB
    from levelup.pipeline import make_llm

    db = DB()
    print(inbox.scan_inbox(cfg, make_llm(cfg), db))
    print("alerts sent:", notify.send_callback_alerts(cfg, db))


def cmd_status(args, cfg) -> None:
    from levelup.db import DB
    from levelup.report import build_report

    db = DB()
    print(json.dumps(db.counts(), indent=2))
    path = build_report(db)
    print("Report:", path)
    if not args.no_open:
        webbrowser.open(f"file:///{path}")


def cmd_doctor(args, cfg) -> None:
    ok = True

    def check(label: str, good: bool, fix: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"  [{'OK' if good else '!!'}] {label}" + ("" if good else f"  ->  {fix}"))

    print("LevelUp doctor")
    check("config.yaml present", (ROOT / "config.yaml").exists(), "copy config.example.yaml to config.yaml")
    prov = cfg.get("llm.provider", "auto")
    if prov == "auto":
        prov = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "groq"
    key_env = {"anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY",
               "nvidia": "NVIDIA_API_KEY"}.get(prov, "ANTHROPIC_API_KEY")
    check(f"{key_env} set (llm provider: {prov})", bool(os.getenv(key_env)), "add it to .env")
    check("Telegram alerts set", bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
          "optional: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env for phone alerts")
    prof = DATA_DIR / "profile.json"
    check("profile built from resume", prof.exists(), "python -m levelup setup --resume <file>")
    if prof.exists():
        p = json.loads(prof.read_text(encoding="utf-8"))
        rp = cfg.get("applicant.resume_path") or p.get("resume_path", "")
        check(f"resume file exists ({rp})", bool(rp) and os.path.exists(rp), "fix applicant.resume_path in config.yaml")
    check("email address set", bool(os.getenv("EMAIL_ADDRESS")), "EMAIL_ADDRESS in .env (for callbacks)")
    check("email app password set", bool(os.getenv("EMAIL_APP_PASSWORD")), "EMAIL_APP_PASSWORD in .env (HANDOFF step 4)")
    try:
        import playwright  # noqa: F401
        check("playwright installed", True)
    except ImportError:
        check("playwright installed", False, "pip install playwright && python -m playwright install chromium")
    try:
        import jobspy  # noqa: F401
        check("python-jobspy installed (optional: LinkedIn/Naukri discovery)", True)
    except ImportError:
        print("  [--] python-jobspy not installed (optional)")
    print(f"  dry_run = {cfg.dry_run}  (set apply.dry_run: false in config.yaml to submit for real)")
    print("All good." if ok else "Fix the items marked !! above.")


def main() -> None:
    p = argparse.ArgumentParser(prog="levelup", description="Resume in, job applications out.")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="read your resume and build data/profile.json")
    s.add_argument("--resume", required=True)
    r = sub.add_parser("run", help="discover, match, apply and watch inbox on a loop")
    r.add_argument("--once", action="store_true")
    r.add_argument("--no-apply", action="store_true")
    r.add_argument("--no-discover", action="store_true")
    sub.add_parser("discover", help="find and score jobs only")
    rv = sub.add_parser("review", help="finish applications that need you")
    rv.add_argument("--limit", type=int, default=10)
    sub.add_parser("inbox", help="check email for callbacks now")
    st = sub.add_parser("status", help="show counts and open the report")
    st.add_argument("--no-open", action="store_true")
    sub.add_parser("doctor", help="check configuration")
    args = p.parse_args()

    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    {"setup": cmd_setup, "run": cmd_run, "discover": cmd_discover, "review": cmd_review,
     "inbox": cmd_inbox, "status": cmd_status, "doctor": cmd_doctor}[args.cmd](args, cfg)
