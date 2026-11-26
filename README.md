# LevelUpCorp

**Takes your resume, gets you a job. That simple.**

You give LevelUpCorp your resume once. After that it keeps doing the job hunt for you:

1. **Finds jobs.** It checks 55+ tech companies' career pages and several job boards, plus LinkedIn, Indeed, Naukri and Glassdoor if you turn that on.
2. **Keeps only the ones that fit.** Roles must match your resume, sit in your pay range (default **8 LPA and up**) and be in India or open to remote from India.
3. **Applies.** It opens each application form in a real browser, fills every field from *your* profile, attaches your resume, writes the "why this company?" answers and submits.
4. **Watches your inbox.** When a company replies with an interview, assessment, offer or recruiter message, it **emails you an alert** with what to do next.
5. **Repeats** every few hours, within a daily cap you set.

It is built in Python and uses Claude (the Anthropic API) for reading your resume, scoring jobs, answering form questions and sorting recruiter emails.

> **Setting it up for the first time?** Follow [HANDOFF.md](HANDOFF.md). It's a click-by-click guide that takes about 30–45 minutes.

---

## Contents

- [What it does, step by step](#what-it-does-step-by-step)
- [What is automatic and what still needs you](#what-is-automatic-and-what-still-needs-you)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Where jobs come from](#where-jobs-come-from)
- [How a job is chosen](#how-a-job-is-chosen)
- [How an application is filled](#how-an-application-is-filled)
- [Interview callback alerts](#interview-callback-alerts)
- [The report](#the-report)
- [Safety and honesty rules](#safety-and-honesty-rules)
- [Costs](#costs)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Credits and references](#credits-and-references)

---

## What it does, step by step

```
 resume.pdf ──► setup ──► data/profile.json   (your facts; you can edit it)
                               │
   every N hours ┌─────────────┴──────────────────────────────────────────────┐
                 │ 1. DISCOVER  company career pages (Greenhouse, Lever, Ashby, │
                 │              Workable, SmartRecruiters, Recruitee, Workday)  │
                 │              + job boards (Himalayas, RemoteOK, Jobicy, HN,  │
                 │              Remotive, Adzuna, Jooble) + optional JobSpy      │
                 │ 2. MATCH     rule filter (title, seniority, location, pay,    │
                 │              freshness) ──► Claude fit score 0-100            │
                 │ 3. APPLY     Recruitee API │ browser form-fill │ apply-yourself│
                 │ 4. INBOX     read new emails ──► Claude sorts them            │
                 │ 5. NOTIFY    instant alert for interviews + daily digest      │
                 │              + data/report.html                               │
                 └──────────────────────────────────────────────────────────────┘
```

Everything is stored locally in `data/levelup.db` (SQLite). Nothing about you leaves your computer except:
- what is sent to the Claude API to do the work above, and
- the applications themselves.

## What is automatic and what still needs you

Fully hands-off applying is not possible everywhere, so here is exactly how each kind of job is handled:

| Where the job lives | What LevelUpCorp does | Your part |
|---|---|---|
| **Greenhouse, Lever, Ashby, Workable, SmartRecruiters** hosted forms (most startups and global tech companies hiring in India) | Opens the form, fills every field, uploads the resume, clicks **Submit**, confirms the "thank you" page | Nothing, unless a **CAPTCHA** appears. Then the tool beeps and waits up to 3 minutes for you to solve it in the open browser window. If nobody solves it, the job goes to your review queue. |
| **Recruitee** | Submits through Recruitee's public application API (no browser) | Nothing |
| **LinkedIn, Naukri, Indeed, Glassdoor, Wellfound, Instahyre, Cutshort**, etc. | Finds and scores the job and puts it on your **"apply yourself" list** with a link and the reason it fits | Click the link and apply. These sites ban accounts that use bots, so the tool never logs in to them or submits there. |
| **Workday, Taleo, iCIMS, Darwinbox, Keka** (company portals that need an account) | Same as above: apply-yourself list | Apply manually |
| A form question the tool can't answer truthfully from your profile | Stops before submitting and puts the job in the **review queue** | Run `python -m levelup review`. The tool re-opens the form pre-filled; you answer the missing question and submit. |

You get a **daily email** listing everything that needs you, so nothing gets missed.

## Quick start

Windows (PowerShell), Python 3.10+:

```powershell
git clone https://github.com/thejas17d/LevelUpCorp.git
cd LevelUpCorp
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1     # venv + packages + browser + config files

# 1. put your keys in .env (ANTHROPIC_API_KEY, EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
# 2. edit config.yaml (expected CTC, notice period, cities...)

.\.venv\Scripts\python -m levelup setup --resume "C:\path\to\resume.pdf"
.\.venv\Scripts\python -m levelup doctor          # everything green?
.\.venv\Scripts\python -m levelup run --once      # first cycle (dry run: fills forms, does NOT submit)
.\.venv\Scripts\python -m levelup status          # opens the report
```

When the dry-run screenshots in `data/screenshots/` look right, set `apply.dry_run: false` in `config.yaml`. Then either:
- leave `python -m levelup run` running, or
- schedule it with `scripts\schedule_task.ps1`.

macOS / Linux: the same commands work with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m playwright install chromium`.

## Commands

All commands are `python -m levelup <command>`, run from the project folder with the virtual environment's Python.

| Command | What it does |
|---|---|
| `setup --resume FILE` | Reads your resume (PDF, DOCX or TXT) with Claude and writes `data/profile.json`. Run it again whenever your resume changes. |
| `run` | Runs forever: one full cycle every `schedule.every_hours` hours. Stop with Ctrl+C. |
| `run --once` | One full cycle, then exits. Use this with Windows Task Scheduler. |
| `run --once --no-apply` | Discover, match and check the inbox, but don't apply. |
| `discover` | Only find and score jobs (no applying, no inbox). |
| `review [--limit N]` | Opens the jobs that need you one by one, pre-filled, so you can finish and submit. |
| `inbox` | Checks email for callbacks right now and sends alerts. |
| `status [--no-open]` | Prints counts and opens `data/report.html`. |
| `doctor` | Checks the API key, profile, resume path, email settings and browser. |

Add `-v` for detailed logs. Every run is also logged to `data/levelup.log`.

## Configuration

Two files, both **git-ignored** so your personal data never reaches GitHub.

**`.env`** holds secrets (copy from `.env.example`):

| Key | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | Everything (resume, scoring, answers, email sorting) |
| `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` | Reading replies and sending you alerts (Gmail App Password, not your normal password) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Optional: Adzuna India jobs (free key) |
| `JOOBLE_API_KEY`, `JOOBLE_HOST` | Optional: Jooble (free key; the key must come from the India site, `in.jooble.org`) |

**`config.yaml`** holds your preferences (copy from `config.example.yaml`; every option is commented). The important ones:

| Setting | Default | Meaning |
|---|---|---|
| `search.min_salary_lpa` | `8` | Pay floor. A job passes if the top of its range reaches this. |
| `search.cities` | `[]` (all India) | Limit on-site roles to these cities |
| `search.remote_ok` | `true` | Accept remote roles open to India or worldwide |
| `search.keywords` | `[]` | Search terms. Empty means use the job titles Claude inferred from your resume. |
| `search.title_must_include` / `title_exclude` | tech titles / managers, sales... | Cheap whole-word title filter |
| `search.senior_titles_from_years` | `4` | Skip Senior/Lead/Staff titles below this much experience |
| `match.min_score` | `70` | Claude fit score needed to apply (0–100) |
| `apply.dry_run` | **`true`** | **Fills forms but never submits.** Turn off when you're happy. |
| `apply.max_applications_per_day` | `20` | Daily cap |
| `apply.max_per_company_per_30_days` | `2` | Don't spam one company |
| `apply.wait_for_captcha_seconds` | `180` | How long to wait for you to solve a CAPTCHA |
| `applicant.*` | | Your standard answers: current/expected CTC, notice period, relocation, work authorisation, EEO answers. **Claude copies these, never guesses them.** |
| `llm.model` | `claude-opus-5-5` | Model for every step; `llm.per_task_model` can override per step |
| `sources.*` | | Turn individual job sources on or off |
| `schedule.every_hours` | `4` | Cycle interval for `run` |

**`companies.yaml`** is the list of company career pages to watch. Add your dream companies: open the company's careers page, click a job, and copy the part of the URL after the ATS domain (for example `jobs.lever.co/`**`cred`**). See the comments in the file.

## Where jobs come from

| Source | Type | Notes |
|---|---|---|
| **55+ company career pages** (`companies.yaml`): Razorpay, Groww, CRED, Meesho, Paytm, Swiggy, Freshworks, Sarvam AI, Databricks, Stripe, MongoDB, Atlassian-style global companies with India offices... | Public ATS JSON feeds (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Workday) | Best quality; also the forms the tool can fill. Feeds verified 24 Nov 2026. |
| **Himalayas** | Search API filtered to India | Remote roles open to India, with salary when listed |
| **RemoteOK**, **Jobicy** (APAC + Anywhere), **Remotive** | Public APIs | Remote roles. Remotive allows at most 4 calls a day, so the tool calls it every 6 hours at most. |
| **Hacker News "Who is hiring"** | Algolia API | Monthly thread; keeps posts mentioning India or worldwide remote |
| **Adzuna India**, **Jooble** | Free API keys | Large Indian job databases |
| **LinkedIn, Indeed, Naukri, Glassdoor** | [JobSpy](https://github.com/speedyapply/JobSpy), optional | Discovery only, logged out. Jobs go to the apply-yourself list unless they link to a company form. |
| Arbeitnow | Public API | Off by default (mostly European on-site roles) |

Each source has a polite rate limit, and a source that fails never stops the run.

## How a job is chosen

1. **De-duplication.** The same company + title + location from several sources is stored once.
2. **Rule filter** (free and instant). Thousands of jobs are reduced to the few hundred worth reading:
   - **Title:** it must look like a tech role (whole-word match, so "ML" doesn't match "HTML"). Managers, sales and so on are excluded.
   - **Seniority:** Senior, Lead, Staff and Principal titles are skipped if your experience is below the threshold. Internships are skipped once you have experience.
   - **Location:** an Indian city, or remote that is open to India or worldwide. "US only" and similar restrictions are detected.
   - **Freshness:** postings older than `max_age_days` are skipped.
   - **Pay:** if a salary is listed and its top is below your floor, the job is dropped. Salaries in any format are converted to LPA ("12-18 Lacs P.A.", "₹60,000/month", "$80k–$120k"...).
   - **Company limits:** your blocklist, and how recently you applied to that company.
3. **Claude scoring.** Jobs go 8 per request, with your profile. Each one gets back:
   - a 0–100 fit score and the reason,
   - an India-market salary estimate when none is listed,
   - "knockouts": hard requirements you clearly don't meet, such as a degree, years of experience, a visa or a language.
4. A job is queued if:
   - the score is at least `min_score`,
   - there are no knockouts, and
   - the pay (listed or estimated) reaches your floor.

## How an application is filled

1. A real Chromium window opens, using a persistent browser profile in `data/browser-profile` (fewer CAPTCHAs).
2. The tool reads every visible field: label, type, options and whether it's required. This works on React dropdowns, radio groups, checkboxes, file uploads, and Greenhouse forms embedded on company sites.
3. Claude answers each field **only** from your profile, your `applicant` answers in `config.yaml`, and answers you used before (kept in `data/answer_memory.json`). Free-text questions ("Why do you want to work here?") get short, specific answers built from real facts in your resume and the job description.
4. Your resume goes into the resume field. A cover letter is written only when the form asks for one; it's saved in `data/cover_letters/`.
5. If any required field has no truthful answer, the tool **doesn't submit**. The job goes to the review queue with the reason.
6. Otherwise it submits (unless `dry_run` is on), waits for the confirmation page and takes a screenshot (`data/screenshots/`).
7. It pauses 40–120 seconds between applications and applies to at most one job per company per run.

## Interview callback alerts

The applications use your real email address, so recruiters reply to your inbox as usual. LevelUpCorp reads new mail over IMAP (read-only: it never deletes, moves or marks emails). It keeps messages that come from hiring systems, mention hiring words, or mention a company you applied to. Claude then sorts them into **interview**, **assessment**, **offer**, **recruiter reply**, **acknowledgement**, **rejection**, **job alert** or **not relevant**.

- **Interview, assessment, offer or recruiter reply:** you get an **instant email**, for example "LevelUp: 1 interview call(s)!", with the company, a one-line summary and what to do by when.
- **Daily digest:** applications submitted, what needs your review, and the top apply-yourself jobs.
- The application's status in the report updates automatically (interview, rejected, and so on).

## The report

`data/report.html` is rebuilt after every cycle (`python -m levelup status` opens it). It shows:
- callbacks and recruiter replies,
- the review queue with the reason each job stopped,
- the apply-yourself list with fit reasons and pay,
- the full application log with links,
- jobs queued for the next run.

## Safety and honesty rules

- **Dry run by default.** Nothing is submitted until you set `apply.dry_run: false`.
- **No invented facts.** Claude may only use your profile and your configured answers. Unknown required answers stop the application.
- **No bot logins** on LinkedIn, Naukri, Indeed, Glassdoor or Wellfound, whose terms forbid it.
- **No CAPTCHA solving services.** You solve it, or the job waits for you.
- **Daily cap, per-company limits and pauses** keep the volume reasonable for employers.
- **Secrets stay local.** `.env`, `config.yaml` and everything in `data/` (profile, resume copy, database, screenshots) are git-ignored. Don't commit your resume to a public repo.

## Costs

The tool itself is free. The Claude API is pay-as-you-go at [console.anthropic.com](https://console.anthropic.com/). With the default model (`claude-opus-5-5`, $4 / $20 per million input/output tokens):

| Step | Typical volume | Rough cost |
|---|---|---|
| Resume setup | once | a few cents |
| Scoring | 50–150 new matching jobs/day (8 per request) | ~$1–3/day |
| Form answers | up to 20 applications/day | ~$1/day |
| Email sorting | a few batches/day | cents |

That's roughly **$2–5 a day** at full volume. These are estimates, so check the usage page in the Anthropic console. To spend less, send the high-volume steps to a cheaper model in `config.yaml`:

```yaml
llm:
  per_task_model: {score: claude-haiku-5-5, inbox: claude-haiku-5-5}
```

Each run also logs its token usage in `data/levelup.db` (the `runs` table).

## Project layout

```
LevelUpCorp/
├── levelup/
│   ├── cli.py            # commands (setup, run, review, inbox, status, doctor)
│   ├── pipeline.py       # one cycle: discover -> match -> apply -> inbox -> notify -> report
│   ├── config.py         # config.yaml + .env loading
│   ├── db.py             # SQLite store (jobs, scores, applications, emails, runs)
│   ├── llm.py            # Claude wrapper: JSON-schema outputs, prompt caching, refusal fallback
│   ├── resume.py         # resume -> profile.json
│   ├── salary.py         # any salary text -> LPA range
│   ├── matcher.py        # rule filter + Claude scoring
│   ├── sources/          # ats.py (company career pages), boards.py (job APIs), jobspy_source.py
│   ├── apply/            # router.py (how to apply), browser.py (form filler), __init__.py (queue)
│   ├── inbox.py          # IMAP reader + Claude email classifier
│   ├── notify.py         # alert + digest emails (SMTP)
│   └── report.py         # data/report.html
├── companies.yaml        # career pages to watch
├── config.example.yaml   # all settings, commented
├── .env.example          # secrets template
├── scripts/              # setup.ps1, schedule_task.ps1, run_once.ps1
├── tests/test_core.py    # offline tests (salary, routing, filters)
├── docs/RESEARCH.md      # research behind the design: sources, ATS behaviour, other projects
└── HANDOFF.md            # step-by-step setup + maintainer notes
```

Run the tests with `python tests/test_core.py` (or `pytest -q`).

## Troubleshooting

| Problem | Fix |
|---|---|
| `Claude API key not found` | Put `ANTHROPIC_API_KEY=sk-ant-...` in `.env` (no quotes or spaces needed) |
| `No profile yet` | `python -m levelup setup --resume "path\to\resume.pdf"` |
| Inbox shows `skipping` | Set `EMAIL_ADDRESS` and `EMAIL_APP_PASSWORD`. Gmail needs 2-Step Verification on before you can create an App Password. |
| `[IMAP] AUTHENTICATIONFAILED` | Wrong app password, or IMAP is off. Turn it on in Gmail → Settings → Forwarding and POP/IMAP. |
| Many jobs in **needs_review** with "CAPTCHA" | Keep `headless: false` and stay near the PC during runs, or clear the queue with `python -m levelup review` once a day |
| "could not find an application form" | The company changed its careers page or wraps the form unusually. Apply manually from the report link. |
| Very few jobs queued | Lower `match.min_score`, add `search.extra_titles`, widen `search.cities`, add companies to `companies.yaml`, or enable JobSpy |
| Wrong roles queued | Fix `data/profile.json` (`target_titles`, `primary_stack`), raise `min_score`, or add words to `title_exclude` |
| A source keeps failing | See `data/levelup.log`. Turn it off under `sources.boards` if needed. Workday sites sometimes rate-limit (HTTP 429). |

## FAQ

**Will it apply to the same job twice?** No. Jobs are de-duplicated by company, title, location and URL, and every attempt is logged.

**Can it apply on LinkedIn or Naukri for me?** No, on purpose. Their terms ban automation and they restrict accounts that do it. The tool finds and ranks those jobs for you and lists them in the report and daily email.

**What if Claude writes something wrong in an answer?** Answers come only from `data/profile.json` and `config.yaml`, so keep those accurate. Dry-run mode plus the screenshots let you check the answers before going live. Answers you've used are reused from `data/answer_memory.json`, which you can edit.

**Can I run it while the laptop is off?** No, it runs on your PC. Schedule it with Task Scheduler for when the PC is on. A cloud deployment is listed as a next step in HANDOFF.md.

**Is my resume uploaded to GitHub?** No. `*.pdf`, `*.docx`, `resume*`, `data/`, `.env` and `config.yaml` are all git-ignored.

## Credits and references

Design ideas were borrowed (not code) from these open-source projects:
- [career-ops](https://github.com/career-ops-hq/career-ops): ATS autofill notes, fact-checking against the real CV
- [AIHawk / Jobs_Applier_AI_Agent](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk): fit scoring, screenshot audit trail
- [ApplyPilot](https://github.com/ibarrajo/ApplyPilot): answer memory, company-aware pacing, Gmail tracking
- [JobSpy](https://github.com/speedyapply/JobSpy): job-board discovery
- [Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn): dry-run-before-submit workflow

Details are in [docs/RESEARCH.md](docs/RESEARCH.md). For your own personal use only: respect each site's terms and every employer's time.
