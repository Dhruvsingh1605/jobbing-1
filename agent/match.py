"""Cheap heuristic prefilter, then LLM fit scoring."""
import json, re
from .core import cfg, profile
from . import llm

WEST = r"(united states|usa|u\.s\.|\bus\b|canada|uk\b|united kingdom|europe|\beu\b|emea|germany|france|spain|netherlands|poland|portugal|brazil|latam|mexico|australia|new zealand|singapore|japan|israel|ireland|italy|sweden|switzerland|austria|romania|argentina|colombia|nigeria|egypt|turkey|dubai|uae|philippines|vietnam|indonesia)"
OPEN = r"(india|worldwide|anywhere|global|apac|asia|any location|international|remote - any|work from anywhere)"

def _words(lst): return re.compile(r"(?<![a-z])(" + "|".join(re.escape(w) for w in lst) + r")(?![a-z])", re.I)

def prefilter(job):
    """Returns (ok, reason)."""
    c = cfg(); title = job["title"].lower(); comp = job["company"].lower(); loc = (job.get("location") or "").lower()
    desc = (job.get("description") or "").lower()
    if any(b in comp for b in c["blocklist_companies"]): return False, "blocklisted company"
    from .sources import age_days
    a = age_days(job.get("posted"))
    if a is not None and a > c.get("max_job_age_days", 10): return False, f"stale posting ({a:.0f} days old)"
    if job["source"] == "hn":
        head = (job["description"] or "")[:500]
        if not re.search(r"\b(ai|llm|ml|machine learning|genai|python|agent)\b", head, re.I): return False, "hn: not AI"
        if _words(["senior", "staff", "principal", "lead"]).search(head[:150]): return False, "hn: senior"
        if re.search(r"\b(seeking|looking for work)\b", head[:60], re.I): return False, "hn: candidate post"
        return True, ""
    title = re.sub(r"member of (the )?technical staff", "mts", title)   # startup title, not 'staff-level'
    if _words(c["exclude_title_words"]).search(title): return False, "excluded title word"
    if not _words(c["target_titles"]).search(title): return False, "title not targeted"
    m = [int(x) for x in re.findall(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", desc[:6000])]
    if m and min(m) > c["max_required_years"] + 1 and max(m) >= 6: return False, f"needs {min(m)}+ yrs"
    visa = bool(re.search(r"visa sponsor|sponsorship (is )?available|relocation (support|assistance|package)|we sponsor", desc))
    india = bool(re.search(r"india|gurgaon|gurugram|delhi|noida|bangalore|bengaluru|hyderabad|pune|mumbai|chennai", loc))
    if india: return True, ""
    if re.search(OPEN, loc): return True, ""
    placed = re.sub(r"[\s,()\-/]*remote[\s,()\-/]*", " ", loc).strip()
    if "remote" in loc and placed and not visa: return False, "location-bound foreign role (remote only within that country)"
    if "remote" in loc or loc.strip() in ("", "remote"):
        if re.search(WEST, loc) and not visa: return False, "remote but region-restricted"
        return True, ""
    if re.search(WEST, loc) or loc:
        if c.get("allow_international") and visa: return True, ""
        return False, "foreign location without visa sponsorship"
    return True, ""

SYSTEM = """You are a strict job-fit evaluator for one candidate. Judge ONLY from the candidate facts and job text given.
Return JSON: {"score": 0-100, "min_years_required": number|null, "location_ok": bool, "salary_ok": bool, "seniority_ok": bool, "reason": "<=20 words"}.
Rules:
- Startups (seed to Series C, AI-native or product companies) are the candidate's best fit: judge them on skills and ownership potential, and do not penalise a missing formal title or a 'founding'/'MTS' role. Still reject roles that clearly need 5+ years or a senior/lead scope.
- Candidate lives in Gurugram, India, has ~1.5 years of AI/ML experience (junior/mid). Seniority_ok=false for senior/lead roles or when min_years_required > 4.
- location_ok=true if the job is in India (Gurugram, Delhi NCR, Noida, Bangalore, Hyderabad, Pune), or remote and open to India-based candidates, or international AND the posting offers visa sponsorship/relocation. Otherwise false (candidate needs visa sponsorship outside India).
- salary_ok=false only if the posting clearly states pay below INR __MIN_LPA__ LPA (or an equivalent low figure). Unknown -> true.
- Candidate works in fintech/BFSI (banks, NBFCs, lending, payments, KYC/fraud). Add up to +8 to the score when the employer or role is in fintech, NBFC, banking, insurance-tech, payments, lending, KYC/fraud/risk, or document AI; this domain experience is a real strength. Never raise a score to hide a seniority or location problem.
- score reflects skill match (LLMs, RAG, agents, LangChain/LangGraph, Python, FastAPI, MLOps, NLP, fraud/document AI) and role fit. Be honest, not generous."""

def score(job):
    p = profile()
    cand = {"summary": p["summary"], "skills": p["skills"], "experience_years": p["total_experience_years"],
            "recent_work": [pr["name"] + ": " + pr["subtitle"] for e in p["experience"][:1] for pr in e.get("projects", [])]}
    prompt = f"CANDIDATE:\n{json.dumps(cand)}\n\nJOB:\nCompany: {job['company']}\nTitle: {job['title']}\nLocation: {job['location']}\nDescription:\n{(job['description'] or '')[:5000]}"
    r = llm.ask(prompt, system=SYSTEM.replace("__MIN_LPA__", str(cfg().get("min_salary_lpa", 12))), json_out=True)
    c = cfg()
    ok = (r.get("score", 0) >= c["min_score"] and r.get("location_ok") and r.get("salary_ok", True) and r.get("seniority_ok", True))
    return int(r.get("score", 0)), bool(ok), str(r.get("reason", ""))[:200]
