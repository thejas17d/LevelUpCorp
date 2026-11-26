"""Browser form-filler for hosted ATS application pages (Greenhouse, Lever, Ashby, Workable, SmartRecruiters).

How one application works:
  1. Open the form in a real Chrome window (persistent profile in data/browser-profile).
  2. Read every visible field: its label, type, options and whether it is required.
  3. Ask Claude to answer each field ONLY from your profile + config answers. Anything it
     cannot answer truthfully comes back as "unknown".
  4. Fill the fields, attach the resume (and cover letter if asked).
  5. If dry_run is on: screenshot and stop. Otherwise click Submit and watch for the
     "thank you" page. If a CAPTCHA appears, the tool pauses so you can solve it in the
     window; if nobody solves it in time, the job goes to the review queue.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from levelup.config import DATA_DIR, Config
from levelup.llm import LLM
from levelup.resume import profile_brief

log = logging.getLogger(__name__)

SCREEN_DIR = DATA_DIR / "screenshots"
LETTER_DIR = DATA_DIR / "cover_letters"
ANSWER_MEMORY = DATA_DIR / "answer_memory.json"

TEXT_KINDS = {"text", "email", "tel", "url", "number", "date", "textarea", "month"}

# ---------------------------------------------------------------------------
# Field extraction (runs inside the page)
# ---------------------------------------------------------------------------
EXTRACT_JS = r"""
() => {
  const txt = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    if (el.type === 'file') return true;
    if (el.getAttribute('aria-hidden') === 'true' || /requiredInput/i.test(el.className || '')) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    if (el.type === 'radio' || el.type === 'checkbox') return r.width > 0 && r.height > 0 && s.visibility !== 'hidden';
    // react-select inputs are ~3px wide until you type; judge them by height
    if (el.getAttribute('role') === 'combobox') return r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none';
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const ownLabel = el => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = l.innerText; }
    if (!t && el.getAttribute('aria-labelledby'))
      t = el.getAttribute('aria-labelledby').split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    if (!t && el.getAttribute('aria-label')) t = el.getAttribute('aria-label');
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    return txt(t);
  };
  const containerLabel = el => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg.innerText); }
    const rg = el.closest('[role="radiogroup"],[role="group"]');
    if (rg && rg.getAttribute('aria-labelledby')) { const l = document.getElementById(rg.getAttribute('aria-labelledby')); if (l) return txt(l.innerText); }
    let p = el.parentElement;
    for (let i = 0; i < 6 && p; i++) {
      const lab = p.querySelector(':scope > label, :scope > legend, :scope > div > label, [class*="label"], [class*="question"], [class*="Label"], [class*="Question"]');
      if (lab && !lab.contains(el) && txt(lab.innerText).length > 2) return txt(lab.innerText);
      p = p.parentElement;
    }
    return '';
  };
  const fields = []; const groups = {}; let n = 0;
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const tag = el.tagName.toLowerCase();
    let kind = tag === 'input' ? (el.type || 'text').toLowerCase() : tag;
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search', 'password'].includes(kind)) continue;
    if (!visible(el) || el.disabled) continue;
    if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') kind = 'combobox';
    const fid = 'f' + (n++); el.setAttribute('data-lu', fid);
    let label = ownLabel(el);
    const required = el.required || el.getAttribute('aria-required') === 'true';
    if (kind === 'radio' || kind === 'checkbox') {
      const q = containerLabel(el);
      const gname = el.name || q || fid;
      if (kind === 'radio' || (el.name && document.querySelectorAll('input[type=checkbox][name="' + CSS.escape(el.name) + '"]').length > 1)) {
        const key = kind + '|' + gname;
        if (!groups[key]) { groups[key] = { fid, kind: kind === 'radio' ? 'radio' : 'checkbox_group', label: q || el.name, required, options: [] }; fields.push(groups[key]); }
        groups[key].options.push({ label: label || el.value, fid });
        if (required) groups[key].required = true;
        continue;
      }
      fields.push({ fid, kind: 'checkbox', label: (q && q !== label ? q + ' - ' : '') + label, required });
      continue;
    }
    if (!label) label = containerLabel(el) || el.placeholder || el.name || '';
    // React-select widgets render a combobox plus a shadow text input with the same label: keep one.
    const prev = fields[fields.length - 1];
    if (prev && prev.kind === 'combobox' && kind === 'text' && prev.label === txt(label).slice(0, 300)) continue;
    const f = { fid, kind, label: label.slice(0, 300), required: required || /[*✱]\s*$/.test(label), name: el.name || el.id || '' };
    if (kind === 'select') f.options = Array.from(el.options).map(o => txt(o.text)).filter(o => o && !/^select|^choose|^--/i.test(o)).slice(0, 80);
    if (kind === 'file') f.accept = el.accept || '';
    fields.push(f);
  }
  return fields;
}
"""

CAPTCHA_JS = r"""
() => {
  const frames = Array.from(document.querySelectorAll('iframe'));
  const vis = f => { const r = f.getBoundingClientRect(); return r.width > 60 && r.height > 60; };
  return frames.some(f => /recaptcha\/(api2|enterprise)\/bframe|hcaptcha\.com.*(challenge|frame=challenge)|challenges\.cloudflare\.com/i.test(f.src || '') && vis(f));
}
"""

SUCCESS_RE = re.compile(
    r"thank(s| you) for (applying|your application|your interest)|application (has been |was )?(received|submitted)"
    r"|we('ve| have) received your application|successfully (submitted|applied)|your application is (in|complete)",
    re.I,
)

# ---------------------------------------------------------------------------
# Claude: answer the form
# ---------------------------------------------------------------------------
ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answers", "cover_letter"],
    "properties": {
        "answers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["fid", "value", "source"],
            "properties": {
                "fid": {"type": "string"},
                "value": {"type": "string", "description": "Text to type; for select/radio the exact option label; for checkbox 'true'/'false'; for file 'resume', 'cover_letter' or ''"},
                "source": {"type": "string", "enum": ["profile", "applicant_answers", "memory", "generated",
                                                      "not_needed", "unknown"]},
            }}},
        "cover_letter": {"type": "string", "description": "Only if the form asks for a cover letter or motivation text; else empty"},
    },
}

ANSWER_SYSTEM = """You fill job application forms for one candidate. Rules:
- Use ONLY facts from the candidate profile, the standard application answers, and remembered answers. Never invent employers, dates, degrees, skills, numbers, links or achievements.
- If a field cannot be answered truthfully from that information, return value "" with source "unknown". This is always better than guessing.
- Helper inputs that are not real questions (a phone country-code search box, a duplicate of another field, "autofill from resume", optional fields with nothing truthful to put) get value "" with source "not_needed".
- Free-text questions (why this company, describe a project, motivation): write a concise, specific answer (60-150 words) built only from real profile facts and the job description; source "generated".
- select / radio / checkbox_group: value must be exactly one of the listed option labels (for checkbox_group you may join several with " || ").
- Consent / privacy / terms checkboxes: "true". Marketing / newsletter opt-ins: "false".
- Demographic / EEO / disability / veteran questions: use the standard answers if given, otherwise the option meaning "prefer not to say" / "decline to self-identify".
- Salary questions: use the standard answers (expected CTC); for numeric-only fields give just the number.
- File fields: "resume" for resume/CV, "cover_letter" for a cover letter upload, "" for anything else.
- Cover letter (when requested): 150-220 words, specific to this company and role, plain text, no placeholders. Never state experience as decimal years (no "0.8 years"); say "my first full-time role (since June 2026) plus two internships". Do not claim skills the job needs that the profile lacks.
- Visa/sponsorship questions about working in India: the candidate is an Indian citizen and needs NO sponsorship.
Return an answer for every field id you are given."""


def _load_memory() -> dict:
    try:
        return json.loads(ANSWER_MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_memory(fields: list[dict], answers: dict) -> None:
    mem = _load_memory()
    for f in fields:
        a = answers.get(f["fid"])
        if a and a["value"] and a["source"] in ("applicant_answers", "profile") and f["kind"] != "file":
            mem[_norm(f["label"])] = a["value"]
    ANSWER_MEMORY.write_text(json.dumps(mem, indent=1, ensure_ascii=False), encoding="utf-8")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (s or "").lower()).strip()[:120]



_STOP = {"of", "the", "and", "in", "a", "an", "for", "to", "degree", "s"}
_EDU_FIELD = re.compile(r"school|university|college|institut|degree|discipline|major|field of study|qualification", re.I)
_YESLIKE = re.compile(r"\b(i )?(confirm|agree|accept|consent|acknowledg\w*|yes|i have read|understand)\b", re.I)
_DECLINE = re.compile(r"decline|prefer not|not to (say|disclose|answer)|don.?t wish|do not wish|rather not", re.I)


def _best_option(v: str, labels: list[str], field_label: str = "") -> Optional[int]:
    """Index of the option that best matches answer v, or None. Handles near-misses open models make:
    'true' on a one-option consent question, 'Prefer not to say' vs 'Decline to self-identify',
    'Bachelor of Engineering' vs "Bachelor's Degree", a school missing from the list (-> 'Other')."""
    if not labels:
        return None
    nv = _norm(v)
    norms = [_norm(x) for x in labels]
    for i, x in enumerate(norms):
        if x == nv:
            return i
    for i, x in enumerate(norms):
        if nv and x and (nv in x or x in nv):
            return i
    if nv in ("true", "yes", "i agree", "i confirm") or _YESLIKE.search(v):
        for i, x in enumerate(labels):
            if _YESLIKE.search(x) and not re.search(r"\bno\b|\bnot\b|disagree|decline", x, re.I):
                return i
    if _DECLINE.search(v):
        for i, x in enumerate(labels):
            if _DECLINE.search(x):
                return i
    if re.search(r"bachelor|\bb\.?\s?e\b|\bb\.?\s?tech", v, re.I):
        for i, x in enumerate(labels):
            if re.search(r"bachelor", x, re.I):
                return i
    words = {w for w in nv.split() if len(w) > 2 and w not in _STOP}
    if words:
        best, score = None, 0.0
        for i, x in enumerate(norms):
            xs = {w for w in x.split() if len(w) > 2 and w not in _STOP}
            if xs:
                s = len(words & xs) / len(words | xs)
                if s > score:
                    best, score = i, s
        if score >= 0.5:
            return best
    if re.search(r"how did you (hear|find|learn)|source|where did you (hear|find|see)", field_label, re.I):
        for pat in (r"career|company (web)?site|website|company page", r"job board|online", r"^other"):
            for i, x in enumerate(labels):
                if re.search(pat, x, re.I):
                    return i
    if _EDU_FIELD.search(field_label):
        for i, x in enumerate(norms):
            if x == "other" or x.startswith("other"):
                return i
    return None


def _letter_file(job, name: str = "") -> Path:
    """Cover letter upload named like a person would name it (recruiters see the file name)."""
    company = re.sub(r"[^A-Za-z0-9 .&-]+", "", job["company"] or "Company").strip()[:40] or "Company"
    d = LETTER_DIR / job["key"]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{(name or 'Candidate').strip()} - Cover Letter - {company}.txt"

def _fix_file_fields(fields: list[dict], answers: dict) -> None:
    """Deterministic file uploads: resume goes only into resume/CV inputs, cover letter only into cover-letter inputs.
    (Ashby's 'autofill from resume' box and other stray file inputs are left alone.)"""
    files = [f for f in fields if f["kind"] == "file"]
    tag = lambda f: f"{f['label']} {f.get('name', '')}"
    resume_like = [f for f in files if re.search(r"resume|\bcv\b|curriculum", tag(f), re.I)]
    for f in files:
        a = answers.setdefault(f["fid"], {"fid": f["fid"], "value": "", "source": "not_needed"})
        if re.search(r"cover", tag(f), re.I):
            a["value"] = "cover_letter" if a["value"] == "cover_letter" else ""
        elif resume_like:
            a["value"] = "resume" if f in resume_like else ""
        elif f is files[0]:
            a["value"] = "resume"   # single unlabeled upload box: almost always the resume
        else:
            a["value"] = ""


def answer_fields(fields: list[dict], job, profile: dict, llm: LLM, cfg: Config) -> tuple[dict, str]:
    mem = _load_memory()
    relevant_mem = {k: v for k, v in mem.items() if any(_norm(f["label"]) == k for f in fields)}
    user = (
        f"JOB: {job['title']} at {job['company']} ({job['location']})\n"
        f"DESCRIPTION (excerpt):\n{(job['description'] or '')[:int(cfg.get('llm.answer_description_chars', 3000))]}\n\n"
        f"REMEMBERED ANSWERS (label -> answer): {json.dumps(relevant_mem, ensure_ascii=False)}\n\n"
        f"FORM FIELDS:\n{json.dumps(fields, ensure_ascii=False)}"
    )
    system = ANSWER_SYSTEM + "\n\nCANDIDATE PROFILE\n" + profile_brief(profile)
    res = llm.json(task="answer", system=system, user=user, schema=ANSWER_SCHEMA,
                   effort=cfg.get("llm.effort.answer", "medium"), max_tokens=int(cfg.get("llm.answer_max_tokens", 16000)))
    answers = {a["fid"]: a for a in res["answers"]}
    _apply_fixed_rules(fields, answers, job, cfg, profile)
    letter = _clean_text(res.get("cover_letter", ""))
    for a in answers.values():
        if a.get("source") == "generated":
            a["value"] = _clean_text(a.get("value", ""))
    return answers, letter


def _clean_text(s: str) -> str:
    """Normalise odd Unicode from open models (non-breaking hyphens etc.) and the decimal-years phrasing."""
    s = (s or "").replace("‑", "-").replace("‐", "-").replace(" ", " ").replace(" ", " ")
    s = re.sub(r"\b0\.\d+\s+years?\s+of\s+(hands-on\s+)?experience", "hands-on experience from my first full-time role and two internships", s)
    s = re.sub(r"\b0\.\d+\s+years?\b", "my first year", s)
    return s


# Questions with one true answer for this candidate (Indian citizen applying to jobs in India / remote-India).
# These override the LLM so a weak model can never get them wrong.
_FIXED = [
    (r"legally (authori[sz]ed|eligible|entitled)|authori[sz]ed to work|eligible to work|right to work in", "yes"),
    (r"(require|need)s?\b.{0,40}sponsor|sponsorship", "no"),
    (r"previously (worked|been employed|employed|consulted)|former employee|ever worked (at|for)|worked (at|for) .{0,40} before|ever been employed|been employed by", "no"),
    (r"located (in|on) (the )?(east|west) coast|located in the (united states|us|usa|uk|united kingdom|eu|europe|canada)|are you a u\.?s\.? (citizen|resident)", "no"),
    (r"opt[- ]?in|receive (marketing|news|updates|communications)|subscribe", "no"),
    (r"currently (based|located|living|reside) in (bangalore|bengaluru)", "yes"),
    (r"non-?compete|non-?solicit|post-employment restriction|employment agreements?", "no"),   # confirmed by candidate 26 Nov 2026
    (r"(open|willing) to (relocat|work from office|work in office|hybrid)", "yes"),
]
_CONSENT = re.compile(r"privacy|consent|acknowledg|i confirm|i agree|i accept|terms|i have read|accurate|true and complete|certify", re.I)
_MARKETING = re.compile(r"newsletter|marketing|future (job )?opportunit|talent (community|pool|network)|keep me (updated|informed)|job alerts?|sms|whatsapp updates", re.I)


def _pick_option(f: dict, want: str) -> str:
    opts = f.get("options") or []
    labels = [o["label"] if isinstance(o, dict) else str(o) for o in opts]
    if not labels:
        return want.capitalize()
    for lab in labels:
        if _norm(lab) == want or _norm(lab).startswith(want + " ") or _norm(lab).startswith(want):
            return lab
    return ""


def _profile_facts(profile: dict) -> list[tuple[str, str]]:
    """(label regex, value) pairs filled straight from profile.json when the model leaves them blank."""
    edu = (profile.get("education") or [{}])[0]
    exp = (profile.get("experience") or [{}])[0]
    year = re.findall(r"(?:19|20)\d\d", edu.get("year", ""))
    return [
        (r"^(school|university|college|institution)( name)?\*?$|name of (your )?(school|university|college|institution)", edu.get("institution", "")),
        (r"^degree\*?$|degree (type|level|obtained)|highest (level of )?(education|degree)", edu.get("degree", "")),
        (r"discipline|major|field of study|speciali[sz]ation", "Computer Science"),
        (r"graduation (year|date)|year of graduation|end date year", year[-1] if year else ""),
        (r"(most recent|current|latest) (employer|company)|^company( name)?\*?$|^employer\*?$", exp.get("company", "")),
        (r"(most recent|current|latest) (job )?title|^(job )?title\*?$", exp.get("title", "")),
    ]


def _apply_fixed_rules(fields: list[dict], answers: dict, job, cfg: Config, profile: Optional[dict] = None) -> None:
    for pat, val in (_profile_facts(profile) if profile else []):
        if not val:
            continue
        for f in fields:
            a = answers.setdefault(f["fid"], {"fid": f["fid"], "value": "", "source": "unknown"})
            if f["kind"] in ("file", "checkbox") or (a.get("value") and a.get("source") != "unknown"):
                continue
            if re.search(pat, (f.get("label") or "").strip(), re.I):
                labels = [o["label"] if isinstance(o, dict) else str(o) for o in (f.get("options") or [])]
                if labels:
                    i = _best_option(val, labels, f.get("label", ""))
                    if i is None:
                        continue
                    val_f = labels[i]
                else:
                    val_f = val
                a.update(value=val_f, source="profile")
    # Location questions always get the real current city, never the "preferred locations" sentence.
    here = ((profile or {}).get("applicant_answers") or {}).get("current_location") or "Bengaluru, Karnataka, India"
    for f in fields:
        lab = (f.get("label") or "").strip()
        if f["kind"] in ("text", "combobox") and re.search(
                r"^(current )?location( \(city\))?\*?$|^city\*?$|^current city\*?$|where are you (currently )?(based|located)", lab, re.I):
            answers.setdefault(f["fid"], {"fid": f["fid"]}).update(
                value=here.split(",")[0] if f["kind"] == "combobox" else here, source="applicant_answers")
    loc = f"{job['location'] or ''}".lower()
    india_job =bool(re.search(r"india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|gurgaon|gurugram|noida|remote", loc))
    for f in fields:
        label = f.get("label") or ""
        a = answers.setdefault(f["fid"], {"fid": f["fid"], "value": "", "source": "unknown"})
        if f["kind"] == "checkbox":
            if _MARKETING.search(label):
                a.update(value="false", source="applicant_answers")
            elif _CONSENT.search(label):
                a.update(value="true", source="applicant_answers")
            continue
        if f["kind"] in ("file", "textarea"):
            continue
        if (f["kind"] in ("radio", "checkbox_group", "select", "combobox") and _CONSENT.search(label) and not _MARKETING.search(label)
                and not re.search(r"interview|assessment|survey", label, re.I)):
            labels = [o["label"] if isinstance(o, dict) else str(o) for o in (f.get("options") or [])]
            i = _best_option("true", labels, label)
            if i is not None:
                a.update(value=labels[i], source="applicant_answers")
            elif not labels and f["kind"] == "combobox":
                a.update(value="I confirm", source="applicant_answers")   # options load on click; matcher picks the yes-like one
            continue
        for pat, want in _FIXED:
            if re.search(pat, label, re.I):
                if want == "yes" and "authori" in pat and not india_job:
                    break   # outside India the honest answer depends on the country - leave it to review
                val = _pick_option(f, want) if f["kind"] in ("select", "radio", "combobox") else want.capitalize()
                if val:
                    a.update(value=val, source="applicant_answers")
                break


# ---------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------
class BrowserApplier:
    def __init__(self, cfg: Config, profile: dict, llm: LLM):
        from playwright.sync_api import sync_playwright

        self.cfg, self.profile, self.llm = cfg, profile, llm
        SCREEN_DIR.mkdir(parents=True, exist_ok=True)
        LETTER_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(DATA_DIR / "browser-profile"),
            headless=bool(cfg.get("apply.headless", False)),
            channel=cfg.get("apply.browser_channel") or None,   # "chrome" uses installed Google Chrome
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.ctx.set_default_timeout(15000)

    def close(self) -> None:
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    # -- helpers --
    def _form_frame(self, page):
        """Greenhouse forms embedded on company sites live in an iframe."""
        for fr in page.frames:
            if re.search(r"greenhouse\.io/embed/job_app|job-boards\.greenhouse\.io", fr.url or ""):
                return fr
        return page.main_frame

    def _open_form(self, page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        frame = self._form_frame(page)
        if frame.locator("input[type=file]").count() == 0:
            # Job page without the form open yet: click the Apply button.
            btn = frame.get_by_role("button", name=re.compile(r"^\s*apply", re.I)).or_(
                frame.get_by_role("link", name=re.compile(r"^\s*apply( for this job| now)?\s*$", re.I)))
            if btn.count():
                btn.first.click()
                page.wait_for_timeout(2500)
                frame = self._form_frame(page)
        return frame

    def _fill(self, frame, f: dict, a: dict, resume: str, letter_path: str) -> Optional[str]:
        """Fill one field. Returns an error string or None."""
        v = (a.get("value") or "").strip()
        loc = frame.locator(f'[data-lu="{f["fid"]}"]')
        kind = f["kind"]
        try:
            if kind == "file":
                if v == "resume" and resume:
                    loc.set_input_files(resume)
                elif v == "cover_letter" and letter_path:
                    loc.set_input_files(letter_path)
            elif not v:
                return None
            elif kind in TEXT_KINDS:
                loc.fill(v)
            elif kind == "select":
                try:
                    loc.select_option(label=v)
                except Exception:
                    opts = [o["label"] if isinstance(o, dict) else str(o) for o in (f.get("options") or [])]
                    i = _best_option(v, opts, f.get("label", ""))
                    if i is None:
                        return f"option '{v}' not found"
                    loc.select_option(label=opts[i])
            elif kind == "combobox":
                loc.click()
                loc.fill(v)
                frame.page.wait_for_timeout(900)
                # Prefer the option whose text IS the answer ("India", not "British Indian Ocean Territory").
                exact = frame.get_by_role("option").filter(
                    has_text=re.compile(r"^\s*" + re.escape(v) + r"(?![a-z])", re.I))
                if exact.count():
                    exact.first.click()
                else:
                    if not self._pick_combobox_option(frame, loc, v, f.get("label", "")):
                        return f"option '{v}' not found"
            elif kind in ("radio", "checkbox_group"):
                wanted = [x.strip() for x in v.split("||")]
                opts = f.get("options", [])
                labels = [o["label"] for o in opts]
                hit = False
                for w in wanted:
                    i = _best_option(w, labels, f.get("label", ""))
                    if i is not None:
                        frame.locator(f'[data-lu="{opts[i]["fid"]}"]').check(force=True)
                        hit = True
                if not hit:
                    return f"option '{v}' not found"
            elif kind == "checkbox":
                if v.lower() == "true":
                    loc.check(force=True)
        except Exception as e:
            return f"{type(e).__name__}: {str(e)[:120]}"
        return None

    def _pick_combobox_option(self, frame, loc, v: str, field_label: str = "") -> bool:
        """React-select style dropdown with no exact match: open the full list and choose the closest
        option (e.g. 'Prefer not to say' -> 'Decline to self-identify')."""
        try:
            loc.fill("")
            frame.page.wait_for_timeout(600)
            opts = frame.get_by_role("option")
            texts = [x.strip() for x in opts.all_inner_texts()]
        except Exception:
            return False
        if not texts:
            return False
        pick = _best_option(v, texts, field_label)
        if pick is None and _EDU_FIELD.search(field_label):
            # long typeahead lists (schools): search for "Other" explicitly
            try:
                loc.fill("Other")
                frame.page.wait_for_timeout(900)
                opts = frame.get_by_role("option")
                texts = [x.strip() for x in opts.all_inner_texts()]
                pick = next((i for i, x in enumerate(texts) if _norm(x) == "other" or _norm(x).startswith("other")), None)
            except Exception:
                pick = None
        if pick is None:
            frame.page.keyboard.press("Escape")
            return False
        opts.nth(pick).click()
        return True

    def _submit_and_confirm(self, page, frame, wait_captcha: int) -> tuple[str, str]:
        btn = frame.get_by_role("button", name=re.compile(r"submit( application)?|send application|^apply$|apply now", re.I))
        if not btn.count():
            btn = frame.locator("button[type=submit], input[type=submit]")
        if not btn.count():
            return "needs_review", "submit button not found"
        clicked_at = time.time()
        btn.last.click()
        deadline = time.time() + 25
        captcha_announced = False
        code_tried = False
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            body = ""
            try:
                body = frame.locator("body").inner_text(timeout=3000)[:5000]
            except Exception:
                pass
            if SUCCESS_RE.search(body) or re.search(r"thank|confirmation|submitted|success", page.url, re.I):
                return "submitted", "confirmation page detected"
            if not code_tried and re.search(r"security code|verification code", body, re.I):
                code_tried = True
                if self._enter_emailed_code(page, frame, clicked_at):
                    deadline = time.time() + 30
                    continue
                return "needs_review", "security code emailed by the ATS could not be entered automatically"
            if frame.evaluate(CAPTCHA_JS) or page.evaluate(CAPTCHA_JS):
                if wait_captcha <= 0 or self.cfg.get("apply.headless", False):
                    return "needs_review", "CAPTCHA shown and nobody available to solve it"
                if not captcha_announced:
                    log.warning("  >>> CAPTCHA - please solve it in the browser window (waiting %ss)", wait_captcha)
                    from levelup.notify import telegram
                    job = getattr(self, "_current_job", None) or {}
                    telegram(f"CAPTCHA waiting - {job.get('company', '?')}: {job.get('title', '')}\n"
                             f"Solve it in the LevelUp browser window on your laptop within {wait_captcha // 60} min "
                             f"(Chrome Remote Desktop works from your phone).\n{page.url}")
                    print("\a", end="", flush=True)   # terminal beep
                    captcha_announced = True
                    deadline = time.time() + wait_captcha
            errs = frame.locator("[aria-invalid=true], .error:visible, .field-error:visible, [class*='error']:visible")
            if errs.count() and time.time() > deadline - 10 and not captcha_announced:
                return "needs_review", "form shows validation errors after submit"
        return "needs_review", "no confirmation detected"

    def _enter_emailed_code(self, page, frame, since: float) -> bool:
        """Greenhouse sometimes emails a one-time security code at submit. Read it from Gmail (IMAP,
        read-only), type it in and submit again. Returns True if a code was entered."""
        from levelup.inbox import fetch_security_code
        code = fetch_security_code(since=since - 60, wait_seconds=120)
        if not code:
            return False
        log.info("  security code received by email; entering it")
        boxes = frame.locator("input[id^='security-input'], input[name^='security-input'], input[aria-label*='security code' i]")
        single = frame.locator("input#security_code, input[name='security_code'], input[name*='security' i][maxlength='8'], "
                               "input[autocomplete='one-time-code']")
        try:
            if boxes.count() >= len(code):
                for i, ch in enumerate(code):
                    boxes.nth(i).fill(ch)
            elif single.count():
                single.first.fill(code)
            elif boxes.count() == 1:
                boxes.first.fill(code)
            else:
                return False
            page.wait_for_timeout(500)
            btn = frame.get_by_role("button", name=re.compile(r"submit( application)?|verify|continue", re.I))
            if btn.count():
                btn.last.click()
            return True
        except Exception as e:  # noqa: BLE001
            log.info("  could not type the security code: %s", e)
            return False

    # -- main entry --
    def apply(self, job, form_url: str) -> dict:
        page = self.ctx.new_page()
        self._current_job = job
        key = job["key"]
        shot = str(SCREEN_DIR / f"{key}.png")
        result = {"status": "failed", "notes": "", "answers": {}, "cover_letter": "", "screenshot": shot}
        try:
            frame = self._open_form(page, form_url)
            fields = frame.evaluate(EXTRACT_JS)
            if not fields or not any(f["kind"] == "file" or f["kind"] in TEXT_KINDS for f in fields):
                result.update(status="needs_review", notes="could not find an application form on the page")
                page.screenshot(path=shot, full_page=True)
                return result
            answers, letter = answer_fields(fields, job, self.profile, self.llm, self.cfg)
            letter_path = ""
            if letter:
                letter_path = str(_letter_file(job, self.profile.get('full_name', '')))
                Path(letter_path).write_text(letter, encoding="utf-8")
            resume = self.profile.get("resume_path", "")
            _fix_file_fields(fields, answers)
            problems = []
            for f in fields:
                a = answers.get(f["fid"], {"value": "", "source": "unknown"})
                if f["required"] and a["source"] == "unknown" and f["kind"] != "file":
                    problems.append(f"no truthful answer for required field: {f['label'][:80]}")
                err = self._fill(frame, f, a, resume, letter_path)
                if err and f["required"]:
                    problems.append(f"{f['label'][:60]}: {err}")
                page.wait_for_timeout(150)
            result["answers"] = {f["label"][:120]: answers.get(f["fid"], {}).get("value", "") for f in fields}
            result["cover_letter"] = letter
            page.screenshot(path=shot, full_page=True)

            if problems:
                result.update(status="needs_review", notes="; ".join(problems)[:1500])
                return result
            if self.cfg.dry_run:
                result.update(status="dry_run", notes="form filled; not submitted because apply.dry_run is true")
                return result
            status, note = self._submit_and_confirm(page, frame, int(self.cfg.get("apply.wait_for_captcha_seconds", 180)))
            page.screenshot(path=shot, full_page=True)
            result.update(status=status, notes=note)
            if status == "submitted":
                _save_memory(fields, answers)
            return result
        except Exception as e:
            result.update(status="failed", notes=f"{type(e).__name__}: {str(e)[:300]}")
            try:
                page.screenshot(path=shot, full_page=True)
            except Exception:
                pass
            return result
        finally:
            keep_open = result["status"] == "needs_review" and self.cfg.get("apply.keep_review_tabs_open", False)
            if not keep_open:
                page.close()

    def review(self, job, form_url: str, wait_seconds: int = 900) -> str:
        """Open a job for the user to finish by hand; pre-fills what it can, then waits for confirmation."""
        page = self.ctx.new_page()
        frame = self._open_form(page, form_url)
        try:
            fields = frame.evaluate(EXTRACT_JS)
            answers, letter = answer_fields(fields, job, self.profile, self.llm, self.cfg)
            _fix_file_fields(fields, answers)
            letter_path = ""
            if letter:
                letter_path = str(_letter_file(job, self.profile.get('full_name', '')))
                Path(letter_path).write_text(letter, encoding="utf-8")
            for f in fields:
                self._fill(frame, f, answers.get(f["fid"], {"value": ""}), self.profile.get("resume_path", ""), letter_path)
        except Exception as e:
            log.warning("prefill failed: %s", e)
        print(f"\n  Finish and submit the form in the browser ({job['company']} - {job['title']}).")
        print("  Waiting for the confirmation page... (close the tab to skip)")
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if page.is_closed():
                return "skipped"
            try:
                body = self._form_frame(page).locator("body").inner_text(timeout=3000)[:5000]
                if SUCCESS_RE.search(body):
                    page.close()
                    return "submitted"
            except Exception:
                pass
            time.sleep(2)
        return "needs_review"
