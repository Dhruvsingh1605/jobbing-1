"""Selenium application engine. One generic LLM-driven form filler + ATS-specific URL handling.
Hard rules: never invent facts; never solve/bypass CAPTCHAs (skip + log); unknown required facts -> skip + log."""
import json, os, random, re, time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import WebDriverException
from .core import ROOT, profile, log
from .sources import board_from_url
from . import llm, mailbox

def new_driver():
    o = Options()
    o.add_argument("--headless=new"); o.add_argument("--no-sandbox"); o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-gpu"); o.add_argument("--disable-extensions"); o.add_argument("--disable-background-networking"); o.add_argument("--mute-audio"); o.add_argument("--renderer-process-limit=1"); o.add_argument("--disable-features=Translate,BackForwardCache,MediaRouter"); o.add_argument("--window-size=1366,1800"); o.add_argument("--lang=en-US")
    o.add_argument("--blink-settings=imagesEnabled=false")
    o.add_argument("--js-flags=--max-old-space-size=384")
    o.page_load_strategy = "eager"
    d = webdriver.Chrome(options=o); d.set_page_load_timeout(60); d.implicitly_wait(0)
    return d

JS_FIELDS = r"""
const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return s.visibility!=='hidden' && s.display!=='none' && (r.width>0 || r.height>0); };
const clean = t => (t||'').replace(/\s+/g,' ').trim().slice(0,300);
function labelOf(el){
  let t='';
  if(el.id){ try{ const l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if(l) t=l.innerText; }catch(e){} }
  if(!t && el.getAttribute('aria-labelledby')) t=el.getAttribute('aria-labelledby').split(' ').map(i=>(document.getElementById(i)||{}).innerText||'').join(' ');
  if(!t) t=el.getAttribute('aria-label')||'';
  if(!t){ const l=el.closest('label'); if(l) t=l.innerText; }
  return clean(t);
}
function groupLabel(el){
  const fs=el.closest('fieldset'); if(fs){ const lg=fs.querySelector('legend'); if(lg) return clean(lg.innerText); }
  let w=el.parentElement;
  for(let i=0;i<5&&w;i++,w=w.parentElement){
    const l=w.querySelector(':scope > label, :scope > legend, :scope > .label, :scope > [class*=label], :scope > [class*=title], :scope > div > label');
    if(l && !l.contains(el)) return clean(l.innerText);
  }
  return '';
}
function wrapLabel(el){
  let w=el.parentElement;
  for(let i=0;i<4&&w;i++,w=w.parentElement){ const l=w.querySelector('label, legend'); if(l && !l.querySelector('input,select,textarea')) return clean(l.innerText); }
  return '';
}
const out=[]; const groups={}; let n=0;
document.querySelectorAll('input,select,textarea').forEach(el=>{
  const type=(el.type||el.tagName).toLowerCase();
  if(['hidden','submit','button','image','reset','search'].includes(type)) return;
  if(el.disabled || el.getAttribute('aria-hidden')==='true' && type!=='file') return;
  if(type!=='file' && !vis(el)) return;
  if(el.closest('[class*=recaptcha], .g-recaptcha, .h-captcha')) return;
  el.setAttribute('data-ja', String(n)); const id=n++;
  const req = el.required || el.getAttribute('aria-required')==='true' || /\*|required/i.test(labelOf(el)) ;
  if(type==='radio' || type==='checkbox'){
    const key=type+':'+(el.name||groupLabel(el));
    const own=labelOf(el) || clean(el.parentElement.innerText) || el.value;
    if(!groups[key]){ groups[key]={id:id, kind:type, label:groupLabel(el)||wrapLabel(el)||own, required:req, options:[]}; out.push(groups[key]); }
    groups[key].options.push({text:own, ja:id}); groups[key].required = groups[key].required || req;
    return;
  }
  const f={id:id, kind:(el.tagName==='SELECT'?'select':(el.tagName==='TEXTAREA'?'textarea':type)), label:labelOf(el)||wrapLabel(el)||el.placeholder||el.name||'', required:req, name:el.name||'', placeholder:el.placeholder||'', value:el.value||''};
  if(el.tagName==='SELECT') f.options=[...el.options].map(o=>clean(o.text)).filter(t=>t && !/^select|^choose|^--/i.test(t));
  if(el.getAttribute('role')==='combobox' || /select__input|combobox|autocomplete/i.test(el.className||'')) f.kind='combobox';
  out.push(f);
});
// Ashby renders Yes/No questions as <button data-option=yes|no> pairs (hidden checkbox inside) - expose them as radio groups
document.querySelectorAll('.ashby-application-form-input-yesno').forEach(g=>{
  const bs=[...g.querySelectorAll('button')]; if(!bs.length || !vis(g)) return;
  let lab=''; let w=g.parentElement;
  for(let i=0;i<5&&w&&!lab;i++,w=w.parentElement){ const l=w.querySelector(':scope > label, :scope > legend, :scope > [class*=label i]'); if(l && !l.contains(g)) lab=clean(l.innerText); }
  const opts=bs.map(b=>{ b.setAttribute('data-ja', String(n)); return {text:clean(b.innerText), ja:n++}; });
  out.push({id:opts[0].ja, kind:'radio', label:lab, required:/\*|required/i.test(lab) || true, options:opts});
});
return out;
"""

CAPTCHA_VISIBLE = r"""
const v = el => { const r=el.getBoundingClientRect(); return r.width>120 && r.height>40 && getComputedStyle(el).visibility!=='hidden'; };
for (const el of document.querySelectorAll('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, .cf-turnstile')) {
  if (el.closest('.grecaptcha-badge')) continue;                         // invisible reCAPTCHA badge is not a challenge
  if (el.matches('.g-recaptcha') && el.getAttribute('data-size')==='invisible') continue;
  if (/recaptcha\/api2\/anchor/.test(el.src||'') && /size=invisible/.test(el.src||'')) continue;
  if (v(el)) return true;
}
return false;
"""

def _clean(s): return re.sub(r"\s+", " ", s or "").strip()

def candidate_facts():
    p = profile()
    return json.dumps({k: p[k] for k in ("identity", "current", "total_experience_years", "summary", "skills", "education", "certifications", "answers", "extra_history_linkedin_only")}, ensure_ascii=False) + \
        "\nEXPERIENCE:\n" + "\n".join(f"- {e['title']} @ {e['company']} ({e['dates']})" for e in p["experience"])

FORM_SYSTEM = """You fill job-application forms for one real candidate. Use ONLY the candidate facts supplied. Never invent facts.
Return JSON: {"answers": {"<field id>": <value>}, "missing": [{"id": <id>, "why": "..."}]}.
Value rules:
- text/email/tel/url/number/textarea/combobox: a string. select: EXACTLY one of the given options. radio: EXACTLY the text of one option. checkbox group: a list of option texts. single checkbox: true/false.
- phone: if the label mentions country code use the national number "__PHONE_LOCAL__" (country is India +91), otherwise "__PHONE_FULL__".
- Salary / CTC: use the candidate's numbers in the unit the form asks (LPA or INR per year). Current CTC __CUR_CTC__, expected CTC __EXP_CTC__. Notice period __NOTICE__.
- Work authorisation / sponsorship: decide by the JOB's country. India job -> authorised, no sponsorship needed. Any other country -> NOT authorised, requires sponsorship.
- Veteran/disability/gender/ethnicity/EEO questions: use the answers bank (decline/not a veteran). For dropdown-type EEO fields with unknown option text answer just 'Decline' (it filters to 'Decline to self identify'); for Hispanic/Latino answer 'Decline'; veteran -> 'I am not a protected veteran'. Consents: tick a checkbox ONLY when it is required to submit (terms, privacy notice acknowledgement, 'I certify the information is accurate'). Do NOT opt in to optional items: marketing, 'contact me about future opportunities', talent community, newsletters, SMS/WhatsApp. For a consent question about AI note-takers / recording / sharing data with third parties choose the option that does not consent (e.g. 'No, I do not consent'). 'How did you hear' -> pick a careers-page/job-board/other option.
- Links: LinkedIn/GitHub/portfolio from identity. Location/city: Gurugram, Haryana, India (or the nearest option); willing to relocate: yes.
- Free-text 'why us / why this role': write 3-4 sentences specific to THIS company and role (use details from the job text), linking 1-2 real achievements from the candidate facts; never paste the cover letter there and never use generic filler. 'Additional information' / 'cover letter' text areas: use the supplied cover letter text. Optional free-text you cannot answer from facts: leave blank.
- Years of experience: 1.5 overall in AI/ML (say 1.5 or 2 if an integer is required and rounding up is accepted; otherwise 1). For a specific tool, answer 1 or 1.5 only if the candidate facts show it (Python, LangChain, LangGraph, FastAPI, RAG, Docker, AWS, PyTorch, SQL, MLOps) else put it in missing.
- If a fact is not in the candidate data (date of birth, address, PAN, passport number, references, unknown tool experience...) do NOT guess: put the field id in "missing" (optional fields may simply be omitted).
- Skip file fields (handled separately)."""

def _form_system():
    """FORM_SYSTEM with personal numbers filled in from config/profile.yaml (nothing personal is hard-coded)."""
    p = profile(); i, a = p["identity"], p["answers"]
    return (FORM_SYSTEM.replace("__PHONE_LOCAL__", str(i["phone_local"])).replace("__PHONE_FULL__", str(i["phone"]))
            .replace("__CUR_CTC__", str(a["current_ctc"])).replace("__EXP_CTC__", str(a["expected_ctc"])).replace("__NOTICE__", str(a["notice_period"])))

def ask_answers(fields, job, cover_text):
    slim = [{k: v for k, v in f.items() if k in ("id", "kind", "label", "required", "options", "placeholder")} for f in fields if f["kind"] != "file"]
    prompt = f"CANDIDATE FACTS:\n{candidate_facts()}\n\nJOB: {job['title']} at {job['company']} | location: {job.get('location','')}\n{(job.get('description') or '')[:2500]}\n\nCOVER LETTER TEXT:\n{cover_text}\n\nFORM FIELDS:\n{json.dumps(slim, ensure_ascii=False)}"
    return llm.ask(prompt, system=_form_system(), json_out=True, temperature=0.1)

def _js_click(d, el): d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)

def _by_ja(d, n):
    return d.find_elements(By.CSS_SELECTOR, f'[data-ja="{n}"]')[0]

_DECLINE = re.compile(r"decline|prefer not|(do not|don.?t|dont) wish|not to (say|answer|disclose|specify)|rather not|choose not", re.I)

def _fuzzy(opts, want):
    w = _clean(str(want)).lower()
    if _DECLINE.search(w):   # 'Decline to self-identify' must find 'I don't wish to answer' etc.
        o = next((o for o in opts if _DECLINE.search(_clean(o))), None)
        if o: return o
    for o in opts:
        if _clean(o).lower() == w: return o
    for o in opts:
        if w and (w in _clean(o).lower() or _clean(o).lower() in w): return o
    return None

def _is_date_field(f, el):
    cls = (el.get_attribute("class") or "")
    return bool(re.search(r"date", cls, re.I) or re.search(r"pick (a )?date|mm/dd|dd/mm|yyyy", f.get("placeholder", ""), re.I))

def _date_from_answer(val):
    """Turn an answer like '30 days', '1 month', 'immediately' or a real date into a date. Default: notice period from profile (30 days)."""
    import datetime as _dt
    today = _dt.date.today(); v = str(val or "").strip().lower()
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%B %d, %Y", "%d %B %Y"):
        try: return _dt.datetime.strptime(v, fmt).date()
        except ValueError: pass
    m = re.search(r"(\d+)\s*(day|week|month)", v)
    if m: return today + _dt.timedelta(days=int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)])
    if re.search(r"immediate|asap|now", v): return today + _dt.timedelta(days=1)
    return today + _dt.timedelta(days=30)   # profile.yaml earliest_start: 30 days from offer (notice period)

def _fill_date(d, el, val):
    """react-datepicker style inputs reject free text; type a real date (MM/DD/YYYY), then close the popup with TAB (never ENTER)."""
    dt = _date_from_answer(val)
    el.click(); el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.BACKSPACE)
    el.send_keys(dt.strftime("%m/%d/%Y")); time.sleep(0.4); el.send_keys(Keys.TAB); time.sleep(0.4)
    if not (el.get_attribute("value") or "").strip(): raise ValueError("date not accepted")

def fill_field(d, f, val, files):
    k = f["kind"]
    if k == "file":
        lab = f["label"].lower()
        path = files["cover_pdf"] if "cover" in lab else files["resume"]
        _by_ja(d, f["id"]).send_keys(path); time.sleep(1.5); return
    if val in (None, "", []): return
    if k in ("text", "email", "tel", "url", "number", "textarea", "password"):
        el = _by_ja(d, f["id"])
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        if k == "text" and _is_date_field(f, el):
            return _fill_date(d, el, val)
        try: el.clear()
        except Exception: pass
        txt = str(val) if k == "textarea" else re.sub(r"\s*\n\s*", " ", str(val))
        el.send_keys(txt); return
    if k == "select":
        el = _by_ja(d, f["id"]); o = _fuzzy(f.get("options", []), val)
        if o: Select(el).select_by_visible_text(next(x.text for x in Select(el).options if _clean(x.text) == o)); return
        raise ValueError(f"no option for {val!r}")
    if k == "combobox":
        el = _by_ja(d, f["id"]); d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        alias = lambda t: _clean(str(t)).lower().replace("gurugram", "gurgaon").replace("bengaluru", "bangalore")
        first = str(val).split(",")[0].strip()
        for query in dict.fromkeys([str(val), first, alias(first), ""]):
            d.execute_script("arguments[0].focus(); arguments[0].click();", el); time.sleep(0.3)
            el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.BACKSPACE)
            if query: el.send_keys(query)
            else: el.send_keys(Keys.ARROW_DOWN)     # open the full unfiltered list (typed text can filter every option away)
            time.sleep(1.2)
            opts = d.find_elements(By.CSS_SELECTOR, '[role=option], [class*=option]:not([class*=options])')
            opts = [o for o in opts if o.is_displayed() and o.text.strip()]
            pick = next((o for o in opts if alias(o.text) == alias(val)), None) \
                or next((o for o in opts if alias(first) in alias(o.text)), None) \
                or (next((o for o in opts if _DECLINE.search(o.text)), None) if _DECLINE.search(str(val)) else None)
            if pick:
                try: ActionChains(d).move_to_element(pick).pause(0.2).click().perform()   # real mouse events: JS .click() does not commit in Ashby/react-select
                except WebDriverException: _js_click(d, pick)
                time.sleep(0.6)
                if not [o for o in d.find_elements(By.CSS_SELECTOR, '[role=option]') if o.is_displayed()]: return   # popup closed = committed
        el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.BACKSPACE); el.send_keys(Keys.ESCAPE)   # never press ENTER: it can submit the form
        raise ValueError(f"no option for {val!r}")
    if k in ("radio", "checkbox"):
        if f.get("options") and len(f["options"]) >= 1 and (k == "radio" or len(f["options"]) > 1):
            wants = val if isinstance(val, list) else [val]
            for w in wants:
                o = _fuzzy([x["text"] for x in f["options"]], w)
                if not o: raise ValueError(f"no option for {w!r}")
                _js_click(d, _by_ja(d, next(x["ja"] for x in f["options"] if x["text"] == o)))
        else:
            el = _by_ja(d, f["options"][0]["ja"])
            if bool(val) != el.is_selected(): _js_click(d, el)

def goto_form(d, job):
    url = job["apply_url"] or job["url"]; ats = job["ats"]
    if ats == "greenhouse":
        b = board_from_url(url); m = re.search(r"(?:/jobs/|gh_jid=|token=)(\d+)", url)
        if b and m: url = f"https://job-boards.greenhouse.io/{b[1]}/jobs/{m.group(1)}"
    elif ats == "lever" and not url.rstrip("/").endswith("/apply"): url = url.split("?")[0].rstrip("/") + "/apply"
    elif ats == "ashby" and "/application" not in url: url = url.split("?")[0].rstrip("/") + "/application"
    d.get(url); time.sleep(3.5)
    d.execute_script("document.querySelectorAll('button, a[role=button]').forEach(b=>{const t=(b.innerText||'').trim(); if(/^(accept( all)?( cookies)?|allow all( cookies)?|i agree|got it|ok(ay)?|deny|reject all|decline)$/i.test(t) && b.closest('[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[id*=onetrust i],[class*=privacy i]')) b.click()}); document.querySelectorAll('[id*=onetrust-banner],[class*=cookie-banner i],[id*=cookie-banner i]').forEach(e=>e.remove());")
    return url

def has_form(d):
    return bool(d.execute_script("return [...document.querySelectorAll('input[type=file], input[type=email], input[type=tel]')].length"))

def click_apply_button(d):
    for el in d.find_elements(By.CSS_SELECTOR, "a, button"):
        try:
            t = _clean(el.text).lower()
            if el.is_displayed() and re.fullmatch(r"(apply( now| for this (job|role|position))?|apply here|i'm interested|start application)", t):
                before = d.window_handles; _js_click(d, el); time.sleep(3)
                if len(d.window_handles) > len(before): d.switch_to.window(d.window_handles[-1])
                return True
        except WebDriverException: continue
    return False

def submit_buttons(d):
    cands = []
    for el in d.find_elements(By.CSS_SELECTOR, "button, input[type=submit], [role=button]"):
        try:
            t = _clean(el.text or el.get_attribute("value")).lower()
            if el.is_displayed() and (el.get_attribute("type") == "submit" or re.search(r"^(submit|apply|send application|submit application|finish|complete)", t)):
                cands.append(el)
        except WebDriverException: pass
    return cands

BOT_SCREEN = re.compile(r"not a bot|auto-?appl|prove (that )?you('re| are) (a )?(human|real|not)|are you (a )?(human|robot)|bots? (are|is) not (allowed|welcome)|(do not|don't|please do not|must not) use (ai|a\\.i\\.|chatgpt|llms?|generative)|without (the )?(use|help|assistance) of (ai|chatgpt|llms?)|ai[- ]generated (answers|responses|applications|content) (are|will be) (not|rejected|disqualif)|base64[- ]?(encoded|string)|figure out (a|the) secret", re.I)

SUCCESS = re.compile(r"thank you for (applying|your application|your interest)|application (has been |was )?(submitted|received|sent)|thanks for applying|we('ve| have) received your application|successfully (submitted|applied)|application complete", re.I)

def page_text(d):
    try: return d.find_element(By.TAG_NAME, "body").text
    except Exception: return ""

def _enter_security_code(d, code):
    """Greenhouse shows N single-character boxes (maxlength=1); others show one input labelled 'security/verification code'.
    Never touch any other field (an earlier version typed the code into First Name)."""
    boxes = [e for e in d.find_elements(By.CSS_SELECTOR, "input[maxlength='1']") if e.is_displayed()]
    if len(boxes) >= len(code):
        for e, ch in zip(boxes, code):
            e.click(); e.send_keys(ch)
        return True
    for e in d.find_elements(By.CSS_SELECTOR, "input"):
        try:
            lab = (e.get_attribute("aria-label") or "") + " " + (e.get_attribute("name") or "") + " " + (e.get_attribute("id") or "") + " " + (e.get_attribute("placeholder") or "")
            if e.is_displayed() and re.search(r"security|verification|otp|code", lab, re.I):
                e.clear(); e.send_keys(code); return True
        except WebDriverException: continue
    return False

def apply_to(d, job, tailored, dry_run, shot_dir):
    Path(shot_dir).mkdir(parents=True, exist_ok=True)
    """Returns (status, note). status in applied | dry_run_ok | captcha | needs_info | needs_manual | failed"""
    ats = job["ats"]
    if ats in ("workday", "icims", "taleo", "linkedin", "naukri"):
        return "needs_manual", f"{ats} requires an account/login - skipped"
    url = goto_form(d, job)
    if re.search(r"just a moment|performing security verification|verify you are human|access denied|attention required", (d.title or "") + " " + page_text(d)[:400], re.I):
        return "captcha", "bot-protection wall (Cloudflare/anti-bot) - skipped, not bypassed"
    if not has_form(d):
        if click_apply_button(d): time.sleep(3)
        if not has_form(d): return "needs_manual", "no application form found on page"
    if d.execute_script(CAPTCHA_VISIBLE):
        try: d.save_screenshot(str(Path(shot_dir) / f"{job['id']}_captcha.png"))
        except Exception: pass
        return "captcha", "visible CAPTCHA before form - skipped (not bypassed)"
    if dry_run:  # hard guarantee: a dry run can never submit, whatever a keypress or click does
        d.execute_script("document.addEventListener('submit', e => {e.preventDefault(); e.stopImmediatePropagation();}, true);")
    d.execute_script("document.querySelectorAll('[data-ja]').forEach(e=>e.removeAttribute('data-ja'))")
    fields = d.execute_script(JS_FIELDS)
    if not fields: return "needs_manual", "form has no readable fields"
    up = [f for f in fields if f["kind"] == "file"]
    for f in up:                      # upload first: many ATS auto-parse the resume and overwrite fields afterwards
        try: fill_field(d, f, None, tailored)
        except Exception as e: log(f"upload issue: {str(e)[:60]}", "WARN")
    if up:
        time.sleep(5)
        d.execute_script("document.querySelectorAll('[data-ja]').forEach(e=>e.removeAttribute('data-ja'))")
        fields = d.execute_script(JS_FIELDS)
    if BOT_SCREEN.search(page_text(d)):
        return "needs_manual", "employer's form has a human/anti-bot or no-AI screening question - skipped, not answered"
    res = ask_answers(fields, job, tailored["cover_text"])
    answers, missing = res.get("answers", {}), res.get("missing", [])
    req_missing = [m for m in missing if any(str(f["id"]) == str(m.get("id")) and f.get("required") for f in fields)]
    if req_missing:
        lab = {str(f["id"]): f["label"] for f in fields}
        return "needs_info", "required answer not in profile: " + "; ".join(lab.get(str(m["id"]), "?")[:60] for m in req_missing)
    errs = []
    for f in fields:
        if f["kind"] == "file": continue
        val = answers.get(str(f["id"]), answers.get(f["id"]))
        for attempt in range(3):
            try: fill_field(d, f, val, tailored); break
            except Exception as e:
                if attempt == 2 or "no option" in str(e): errs.append(f"{f['label'][:40]}: {str(e)[:50]}"); break
                time.sleep(1.2)
                try: d.execute_script(JS_FIELDS)  # re-tag after a React re-render (ids are DOM-order stable)
                except Exception: pass
    Path(shot_dir).mkdir(parents=True, exist_ok=True)
    shot = str(Path(shot_dir) / f"{job['id']}_filled.png")
    try: d.save_screenshot(shot)
    except Exception: pass
    unfilled = [f for f in fields if f.get("required") and f["kind"] not in ("file", "radio", "checkbox", "combobox", "select") and
                not d.execute_script("const e=document.querySelector('[data-ja=\"%d\"]'); return e ? !!(e.value||'').trim() : true" % f["id"])]
    if unfilled and not dry_run:
        return "failed", "required fields empty: " + "; ".join(f["label"][:40] for f in unfilled[:4])
    if dry_run:
        return "dry_run_ok", f"filled {len(fields)} fields" + (f"; issues: {'; '.join(errs[:3])}" if errs else "") + (f"; empty required: {[f['label'][:30] for f in unfilled[:3]]}" if unfilled else "")
    btns = submit_buttons(d)
    if not btns: return "failed", "no submit button"
    t0 = time.time(); _js_click(d, btns[-1]); time.sleep(6)
    txt = page_text(d)
    if re.search(r"security code|verification code|verify your email", txt, re.I):
        code = mailbox.verification_code(t0)
        if not code: return "needs_info", "email verification code required (set GMAIL_APP_PASSWORD in .env)"
        if not _enter_security_code(d, code): return "failed", "could not locate the security-code boxes"
        for b in submit_buttons(d)[-1:]: _js_click(d, b)
        time.sleep(6); txt = page_text(d)
    try: d.save_screenshot(str(Path(shot_dir) / f"{job['id']}_after.png"))
    except Exception: pass
    if SUCCESS.search(txt) or re.search(r"confirm|thank|submitted", d.current_url, re.I): return "applied", "submitted"
    if d.execute_script(CAPTCHA_VISIBLE): return "captcha", "CAPTCHA challenge appeared on submit - skipped (not bypassed)"
    err = d.execute_script("return [...document.querySelectorAll('[role=alert], .error, [class*=error], [class*=invalid]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,3).join(' | ')")
    if re.search(r"recaptcha|captcha|are you a robot|suspicious|verify you", err + " " + txt, re.I):
        return "captcha", "site demanded CAPTCHA verification on submit - skipped (not bypassed)"
    return "failed", ("validation: " + err[:200]) if err else "no confirmation detected after submit"

def google_discover(d, con, queries):
    """Search Google for ATS-hosted postings; register their boards. Stops at the first CAPTCHA/consent wall."""
    from .sources import register_board, detect_ats
    new = 0
    for q in queries:
        try:
            d.get("https://www.google.com/search?num=30&tbs=qdr:w&q=" + re.sub(r"\s", "+", q)); time.sleep(random.uniform(3, 6))
            if "/sorry/" in d.current_url or re.search(r"unusual traffic|not a robot", page_text(d), re.I):
                log("google: CAPTCHA/unusual-traffic page - stopping Google discovery (not bypassing)", "WARN"); return new
            for a in d.find_elements(By.CSS_SELECTOR, "a[href]"):
                h = a.get_attribute("href") or ""
                b = board_from_url(h) if detect_ats(h) in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable") else None
                if b and register_board(con, *b): new += 1
        except WebDriverException as e:
            log(f"google query failed: {str(e)[:60]}", "WARN")
    return new
