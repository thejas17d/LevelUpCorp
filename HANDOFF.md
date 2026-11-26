# LevelUpCorp handoff

Read this first, whether you're setting the tool up or picking up the code. Part A is a click-by-click setup. Part B is for whoever maintains the code next.

**Status on 26 Nov 2026: v0.2 is LIVE.** First real day: 11,788 jobs found, 3 applications auto-submitted (GitLab, HighRadius, Celonis; all confirmed by "thanks for applying" emails), 74 apply-yourself links sent to Telegram. It now runs on the free Groq tier, sends Telegram alerts, and runs continuously via `scripts\run_loop.ps1`. See "What was tested (26 Nov 2026)" and "Lessons from the first live day" in Part B.

---

## Part A: Setup, step by step (about 30–45 minutes)

### Step 0: What you need
- A Windows PC with **Python 3.10 or newer**. Check by opening PowerShell and typing `python --version`.
- Your resume as a **PDF** (or DOCX).
- A **Gmail** account, the same one you put on applications.
- An LLM key: a **free Groq key** (recommended, Step 2) or about **$10 of Claude API credit** (see Costs in README.md).
- Optional: **Telegram** on your phone, for alerts (Step 4b).

### Step 1: Get the code and install (5–10 minutes)
1. Open **PowerShell**.
2. Go to the folder where you want the project, for example `cd $HOME\Desktop`.
3. Download it:
   ```powershell
   git clone https://github.com/thejas17d/LevelUpCorp.git
   cd LevelUpCorp
   ```
   No git? On the GitHub page click **Code → Download ZIP**, unzip it, and `cd` into the folder.
4. Run the installer:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
   ```
   It creates a private Python environment (`.venv`), installs the packages and the browser, and creates `.env` and `config.yaml` from the templates. It's safe to run again.

### Step 2: LLM key (5 minutes)
**Free option (recommended): Groq.**
1. Go to https://console.groq.com/, sign in, open **API Keys → Create API Key**, copy it (starts with `gsk_`).
2. In `.env` add `GROQ_API_KEY=` followed by the key. In `config.yaml` keep `llm.provider: groq` and the small `llm.*` sizes from `config.example.yaml` comments (free tier = 8,000 tokens per minute per model).

**Paid option: Claude.**
1. Go to https://console.anthropic.com/ and sign in.
2. Open **Plans & Billing** and add credit. Setting a monthly spend limit is a good idea.
3. Open **API Keys → Create Key**, name it `LevelUpCorp`, and copy it. It starts with `sk-ant-`.
4. Open `.env` in Notepad (`notepad .env`) and paste the key after `ANTHROPIC_API_KEY=`. Save.

### Step 3: Your standard answers (5 minutes)
1. Open the settings: `notepad config.yaml`.
2. Under `applicant:`, fill in:
   - `current_ctc_lpa`, `expected_ctc_lpa`, `notice_period`, `date_available`
   - check `preferred_locations`, `willing_to_relocate` and `work_authorization`.
3. Under `search:`:
   - check `min_salary_lpa: 8`,
   - optionally list preferred `cities` (empty means anywhere in India),
   - add your current employer to `company_blocklist`.
4. Leave `apply.dry_run: true` for now.

### Step 4: Gmail App Password, for interview alerts (5 minutes)
1. Go to https://myaccount.google.com/security and turn on **2-Step Verification** if it's off.
2. Go to https://myaccount.google.com/apppasswords, create one named `LevelUpCorp`, and copy the 16-letter code.
3. In Gmail → **Settings → See all settings → Forwarding and POP/IMAP**, make sure **IMAP is enabled**.
4. In `.env`, set `EMAIL_ADDRESS=you@gmail.com` and `EMAIL_APP_PASSWORD=` followed by the code (spaces don't matter).

Is this safe? The app password lets LevelUpCorp **read** your inbox (read-only) and **send** alert emails to you. You can revoke it at any time from the same Google page.

"App passwords not available for your account"? 2-Step Verification is off, or it uses only passkeys/security keys. Turn it on with a phone number or authenticator app, then retry.

### Step 4b: Telegram alerts (optional, 2 minutes)
1. In Telegram open **@BotFather**, send `/newbot`, pick a name. Copy the **token** it gives you.
2. Open your new bot and send it any message ("hi") so it can reply to you.
3. In `.env` set `TELEGRAM_BOT_TOKEN=` (the token). For `TELEGRAM_CHAT_ID`, open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}`.
4. You'll get pings for: CAPTCHAs waiting (solve in the laptop browser, or via Chrome Remote Desktop), forms that need you, new apply-yourself jobs, run summaries and interview/test replies.

### Step 5: Read your resume (2 minutes)
```powershell
.\.venv\Scripts\python -m levelup setup --resume "C:\Users\<you>\Documents\Resume.pdf"
```
Then open `data\profile.json` and check it. **Every application is built from this file.** Fix wrong details, and edit `target_titles` (the roles it will search for) if you like.

### Step 6: Check everything (1 minute)
```powershell
.\.venv\Scripts\python -m levelup doctor
```
Everything should say `[OK]`. JobSpy is optional.

### Step 7: First run, in dry-run mode (10–20 minutes)
```powershell
.\.venv\Scripts\python -m levelup run --once
```
A browser window opens and fills a few application forms **without submitting**. When it finishes:
- `.\.venv\Scripts\python -m levelup status` opens the report.
- Look at the screenshots in `data\screenshots\`. Are the answers right? If not, fix `data\profile.json` or `config.yaml` and run again.

### Step 8: Go live
1. In `config.yaml`, set `apply.dry_run: false`.
2. **Continuous (recommended):**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\run_loop.ps1 -Minutes 15
   ```
   One full cycle, a 15-minute pause, repeat, until you close that window (its PID is in `data\loop.pid`). Keep the laptop awake (Settings → System → Power → sleep: Never when plugged in).
3. **Or** a slower loop in this window: `.\.venv\Scripts\python -m levelup run` (every `schedule.every_hours`); Ctrl+C stops it.
4. **Or** schedule it so you don't need a window open:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\schedule_task.ps1          # every 4 hours
   powershell -ExecutionPolicy Bypass -File scripts\schedule_task.ps1 -Remove  # to undo
   ```

### Daily routine (5 minutes)
- Read the **"LevelUp daily"** email.
- Apply to the top jobs on the **apply-yourself list** (LinkedIn, Naukri and so on) using the links.
- If anything is waiting for review, run `.\.venv\Scripts\python -m levelup review` and finish those forms.
- When an **interview alert** arrives, reply to the recruiter from Gmail as usual.

### Optional extras
- **More Indian jobs:** get free keys from https://developer.adzuna.com/signup (Adzuna) and https://in.jooble.org/api/about (Jooble; use the India site) and put them in `.env`.
- **LinkedIn / Indeed / Naukri discovery:** run `.\.venv\Scripts\pip install python-jobspy` and set `sources.jobspy.enabled: true`. Those jobs go to your apply-yourself list.
- **Add companies:** edit `companies.yaml` (instructions at the top of the file).
- **Lower cost:** set `llm.per_task_model: {score: claude-haiku-5-5}` in `config.yaml`.

---

## Part B: Maintainer notes

### How it works (one cycle, `levelup/pipeline.py`)
1. **Discover** (`sources/`):
   - Company career pages through public ATS JSON feeds (`ats.py`), using `companies.yaml`.
   - Job board APIs (`boards.py`).
   - Optional JobSpy (`jobspy_source.py`).
   - They run in parallel threads, and a failing source is logged and skipped. Per-source minimum intervals are in `sources/__init__.py: MIN_HOURS`; for example, Remotive allows 4 calls a day.
2. **Store** (`db.py`): SQLite `data/levelup.db`. Jobs are de-duplicated by `Job.key` (company + title + location) and by URL. Job status moves through: `new` → `filtered` / `rejected` / `queued` → `applied` / `dry_run` / `needs_review` / `assisted` / `failed` → `interview` / `assessment` / `offer` / `rejected_by_company`.
3. **Match** (`matcher.py`):
   - `rule_filter()` does title, seniority, location, freshness, salary floor and company limits.
   - `score_jobs()` sends batches of 8 to Claude with a JSON schema: score, verdict, reasons, salary estimate, seniority fit, knockouts.
4. **Apply** (`apply/`):
   - `router.plan()` picks how to apply:
     - `recruitee_api` (public candidate endpoint),
     - `browser` (Greenhouse, Lever, Ashby, Workable or SmartRecruiters hosted forms; aggregator links are followed to find these), or
     - `assisted` (LinkedIn, Naukri, Workday and other sites that forbid bots or need an account).
   - `browser.py`:
     - Persistent Playwright Chromium; `EXTRACT_JS` reads fields with labels, kinds, options and required flags.
     - `answer_fields()` asks Claude for answers; it may only answer from the profile and config answers, and may return `unknown` / `not_needed`.
     - `_fix_file_fields()` handles uploads deterministically.
     - `_fill()` fills each field type (text, select, react-select combobox with exact-option matching, radio, checkbox, file).
     - `_submit_and_confirm()` clicks submit, detects the success text/URL, detects CAPTCHA iframes and waits for a human.
5. **Inbox** (`inbox.py`): IMAP read-only with `BODY.PEEK`. It pre-filters by ATS sender domains, keywords and applied company names, then sends batches of 10 to Claude for classification and links each email to an application by company.
6. **Notify** (`notify.py`): SMTP instant alerts for interview / assessment / offer / recruiter reply, plus one digest a day (a marker file in `data/`).
7. **Report** (`report.py`): static `data/report.html`.

### Claude usage (`llm.py`)
- Every call goes through `LLM.json()`, which uses structured outputs (`output_config.format` JSON schema). The system prompt carries the profile and has `cache_control` set, so repeated calls in a task hit the prompt cache.
- Default model: `claude-opus-5-5`; overrides per task go in `llm.per_task_model` (tasks: `resume`, `score`, `answer`, `inbox`). Effort: `low` for scoring and inbox, `medium` for answers and resume.
- For models that support it, the server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) is on.
- Token usage per run is saved in the `runs.stats` JSON.

### Design decisions, and why
- **No automation on LinkedIn, Naukri, Indeed, Glassdoor or Wellfound.** Their terms ban it and they restrict accounts (LinkedIn's help pages say so outright, and Wellfound uses DataDome). Discovery is logged-out only, through JobSpy; those jobs become `assisted`.
- **Human in the loop for CAPTCHAs.** Greenhouse (reCAPTCHA, sometimes an emailed code), Lever (hCaptcha) and Ashby (configurable spam checks) can challenge at submit. Fully automatic submission isn't reliable there, so the tool pauses and waits for you, or queues the job for `review`. No solving services are used.
- **Recruitee** is the only ATS with an open submit endpoint. It becomes token-only after **10 Feb 2027**; after that, switch those jobs to `browser`.
- **Dry run by default**, and **"unknown" answers block submission.** Getting answers right matters more than volume.
- **IMAP + app password instead of the Gmail API**, so the user doesn't need to create a Google Cloud project. Swapping in the Gmail API (`gmail.readonly` + `gmail.send`) would be a contained change in `inbox.py` / `notify.py`.

### What was tested (24 Nov 2026)
- `tests/test_core.py` passes: salary parsing, routing and the rule filter.
- Live feeds: every board, and each ATS type in `companies.yaml`. Workday returned HTTP 429 during testing, which looks like rate-limiting; its jobs are discovery-only anyway.
- Form extraction on real live forms: Greenhouse (Razorpay), Lever (CRED), Ashby (Sarvam AI), Workable (Apna). Resume upload, React-select dropdowns ("India +91" chosen correctly) and text fields were filled. **Nothing was submitted.**
- A full pipeline cycle with a **mocked** Claude:
  - 9,742 jobs discovered, 9,456 new, rule filter left ~160.
  - 3 real forms filled in dry run, 1 sent to review ("no form found" for a company-site embed).
  - Discover + match took 38 seconds.
- **Not yet tested:**
  - real Claude calls (no API key on the build machine),
  - a real resume,
  - real submissions and the CAPTCHA wait,
  - IMAP and SMTP with a real Gmail account,
  - JobSpy.

  Do these during Step 7 (dry run) before going live.

### What was tested (26 Nov 2026, first live day)
- Groq provider end to end: resume parsing, scoring 300+ jobs with model failover on 429s, form answers.
- Live submissions on Greenhouse (GitLab, HighRadius, Celonis) with confirmation emails received within a minute.
- Telegram alerts, Gmail IMAP (read-only), automatic push of the daily log, the continuous loop.
- Not yet seen live: a CAPTCHA wait, an emailed Greenhouse security code (code path written, untested), Lever and Ashby submits.

### Lessons from the first live day
- **Always dry-run a new form type and read the answers before going live.** Groq invented "Yes" to visa sponsorship and blanked consent boxes; `_apply_fixed_rules()` in `browser.py` now overrides those questions. Add a rule there whenever a model gets a standard question wrong.
- **LLM fit scores miss experience requirements.** `matcher.required_years()` now filters "N+ years" postings before scoring.
- **"Remote - US" was read as worldwide remote.** `REMOTE_TIED` in `matcher.py` fixes it.
- **Volume:** for a <1 year profile, genuine auto-submittable matches are a handful per day; most fresher roles live on LinkedIn/Naukri (apply-yourself list). Don't loosen filters to chase a number.
- **SmartRecruiters** "I'm interested" flow is not supported (Bosch, ServiceNow, Grab, Wise land in review).
- **Greenhouse education fields** with long school lists may lack "Other" (Celonis); those go to review.

### Known gaps and next steps
1. ~~First real dry run~~ done 26 Nov 2026. Keep tuning `ANSWER_SYSTEM` and the fixed rules from real forms.
2. ~~Greenhouse company-site embeds~~ fixed 26 Nov: `router.to_form_url()` opens `job-boards.greenhouse.io/embed/job_app?for=<token>&token=<id>`.
3. **SmartRecruiters apply flow:** support the oneclick-ui form, or keep routing to review.
4. **Greenhouse questions API:** `sources/ats.py: greenhouse_questions()` already fetches exact field names and options. Wire it into `browser.py` to give the combobox options to Claude (today comboboxes are answered free-text, then the closest option is matched).
5. **Ashby duplicate check:** Ashby merges candidates by email. The per-company 30-day limit covers most cases.
6. **Workday:** add a proper fetcher with descriptions and backoff, or leave it as is.
7. **Job-alert emails as a source:** parse Naukri and LinkedIn alert emails already arriving in the inbox. That's allowed by their terms and is a good extra source.
8. **Cloud deployment** so it runs while the PC is off: a small VM plus Xvfb for the headed browser. CAPTCHAs would then need a notification asking you to finish in `review`.
9. **Answer memory UI:** today it's `data/answer_memory.json`; a small editor page would help.

### Files that must never be committed
`.env`, `config.yaml`, `data/` (profile, database, screenshots, cover letters, browser profile), and any resume file. All of these are in `.gitignore`. **The GitHub repo is public.**
