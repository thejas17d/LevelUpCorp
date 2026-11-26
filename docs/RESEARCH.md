# Research behind LevelUpCorp (24 Nov 2026)

These are the findings that shaped the design. Two research passes were run while building v0.1: one on existing open-source auto-apply projects, and one on job sources for India. Endpoints marked "verified" returned live data on 24 Nov 2026.

## 1. Existing open-source projects

| Project | Approach | What we took | What we avoided |
|---|---|---|---|
| [career-ops](https://github.com/career-ops-hq/career-ops) (≈84k stars, MIT) | Claude + Playwright. Scans Greenhouse, Ashby and Lever APIs, scores fit 1–5, tailors the CV, **never submits** | Its autofill notes: Lever triggers hCaptcha on programmatic radio and checkbox clicks; Workable is a single-page app; Greenhouse, Ashby and Lever dropdowns need typing. Also: check answers against the real CV, and pre-scan for knockouts | n/a |
| [AIHawk / Jobs_Applier_AI_Agent](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk) (≈33k, MIT) | Now uses public sources; fills each company's own form in a real browser | Fit scoring, screenshot audit log, a check that the posting is still open | Paid LLM router; original LinkedIn bot (account restrictions were reported) |
| [JobSpy](https://github.com/speedyapply/JobSpy) (≈4.8k, MIT) | Scrapes LinkedIn, Indeed, Glassdoor, Naukri... | Optional discovery layer (`sources/jobspy_source.py`) | Logged-in scraping |
| [GodsScion/Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn) (≈3k) | Selenium + undetected-chromedriver on LinkedIn Easy Apply | Dry-run ("stop before submit") and a structured answer bank | LinkedIn automation |
| [ApplyPilot](https://github.com/ibarrajo/ApplyPilot) (AGPL) | 7-stage pipeline, Claude Code + Playwright MCP, Gmail tracking | Answer memory, company-aware pacing, failure categories | Plain-text credentials in prompts; `--bypassPermissions` |
| Gmail trackers (JappTracker, TagDig, ApplyTrail) | Gmail plus rules or an LLM | Categories, including "not applicable" for recruiter spam | n/a |

**Main finding:** none of the hosted ATS forms can be reliably auto-submitted without a CAPTCHA or bot check. The official submit APIs need the *employer's* key, except Recruitee, until Feb 2027. So LevelUpCorp fills and submits, and pauses for you when a CAPTCHA shows up.

## 2. ATS behaviour

| ATS | Public job list | Form questions exposed | Bot protection at submit |
|---|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Yes: `/jobs/{id}?questions=true` (field names like `first_name`, `question_{id}`, plus types and options) | reCAPTCHA (visible fallback), sometimes an emailed security code |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | No (hosted page only) | hCaptcha |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true` | No | Spam protection level set by the employer |
| Workable | `POST apply.workable.com/api/v3/accounts/{sub}/jobs` | No | Not verified |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings?country=in` | No (needs a key) | Not verified |
| Recruitee | `{co}.recruitee.com/api/offers/` | Yes: `open_questions` | Optional CAPTCHA. **Public submit endpoint** `POST /api/offers/{id}/candidates`, token required from 10 Feb 2027 |
| Workday | `POST {tenant}.wdN.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (undocumented) | No | Account per company; rate-limits |
| Darwinbox, Zoho Recruit | No public feed | n/a | n/a |
| Keka | Unofficial `{co}.keka.com/careers/api/jobs/default/active` | Unknown | n/a |

Workable and SmartRecruiters return HTTP 200 for any account name, so check a token by its job count, not the status code.

## 3. Job boards and APIs

| Source | Endpoint | Auth | Limits and terms | Salary |
|---|---|---|---|---|
| Adzuna India | `api.adzuna.com/v1/api/jobs/in/search/{page}` | free app_id + app_key | personal use allowed, credit Adzuna | min/max, may be predicted |
| Jooble | `POST https://in.jooble.org/api/{key}` | free key, **per country site** | 100 requests/day | text "min - max" |
| Remotive | `remotive.com/api/remote-jobs?category=software-dev` | none | **max 4 calls/day**, 24h delay, link back | free text |
| RemoteOK | `remoteok.com/api` | User-Agent | link back | USD min/max |
| Himalayas | `himalayas.app/jobs/api/search?q=&country=India` | optional key | don't alter `applicationLink` | min/max + currency |
| Jobicy | `jobicy.com/api/v2/remote-jobs?geo=apac&industry=dev` (also `geo=anywhere`) | none | 1 req/s; **no `india` geo** | sometimes |
| HN Who is hiring | `hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring` | none | none | in text |
| Arbeitnow | `arbeitnow.com/api/job-board-api` | none | mostly EU | no |
| Google Jobs via SerpAPI | `serpapi.com/search?engine=google_jobs` | paid (250 free/month) | n/a | string |

## 4. Indian platforms and their terms

| Platform | Terms on automation | LevelUpCorp mode |
|---|---|---|
| Naukri | forbids automated crawling/scraping | discovery via JobSpy only; you apply |
| LinkedIn | bans bots and automation; restricts accounts | discovery (logged out) only; you apply |
| Indeed, Glassdoor | ban robots and scraping | discovery only |
| Wellfound | DataDome bot protection | not used |
| Instahyre, Cutshort, Hirist, iimjobs, Foundit | login required; terms not verified | you apply (use their email alerts) |
| Workday / Taleo / iCIMS portals | account per company | apply-yourself list |

## 5. Salary rules used
- Annual INR ÷ 1,00,000 = LPA. Monthly × 12. Hourly × 2,000. "L", "Lac", "Lakh" and "LPA" mean × 1,00,000; "Cr" means × 1,00,00,000.
- Foreign currency is converted with `search.usd_inr` (update it now and then).
- A role passes if the **top** of its range reaches the floor. Unknown salary becomes a Claude estimate for the role, level, company and location.
- Rough India bands used in prompts:
  - Product companies and GCCs pay SDE-1 / 1–3 years about **8–20 LPA**.
  - SDE-2 / 3–6 years is often **18–40 LPA**.
  - Fresher bands at IT services firms are usually **under 8 LPA**.
