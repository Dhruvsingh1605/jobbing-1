"""CLI: python -m agent.run [run|cleanup|report|test-url]"""
import os
import argparse, concurrent.futures as cf, glob, os, random, shutil, sys, time
from datetime import timedelta
from pathlib import Path
from .core import *
from . import sources, match, tailor, mailbox

def _insert(con, j):
    jid = job_id(j["company"], j["title"], j["url"])
    if con.execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone(): return None
    ok, why = match.prefilter(j)
    if ok and already_applied_company_title(con, j["company"], j["title"]): ok, why = False, "same company+title already applied"
    con.execute("INSERT INTO jobs(id,source,company,title,location,url,apply_url,ats,description,posted,discovered_at,status,note,updated_at,age_days) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid, j["source"], j["company"], j["title"], j["location"], j["url"], j["apply_url"], j["ats"],
         (j["description"] or "")[:8000] if ok else "", j["posted"], now_ist().isoformat(), "new" if ok else "skipped", None if ok else why, now_ist().isoformat(), sources.age_days(j["posted"])))
    if ok and j.get("email"): con.execute("UPDATE jobs SET note=? WHERE id=?", ("email:" + j["email"], jid))
    return ok

def discover(con, c, driver_factory, allow_google):
    allj = []
    if c["sources"].get("ats_boards"): allj += sources.ats_boards(con)
    if c["sources"].get("aggregators"): allj += sources.aggregators(con)
    n_new = n_pass = 0
    for j in allj:
        r = _insert(con, j)
        if r is not None: n_new += 1; n_pass += 1 if r else 0
    con.commit()
    log(f"discovery: {len(allj)} postings, {n_new} new, {n_pass} passed title/location filter")
    if c["sources"].get("serper") and os.getenv("SERPER_KEY"):
        cq = ['(careers OR jobs) ("AI Engineer" OR "ML Engineer" OR "Machine Learning Engineer" OR "Data Scientist" OR "GenAI") (bank OR NBFC OR fintech OR "financial services" OR lending OR payments) India "apply"',
              '(careers OR jobs) ("AI Engineer" OR "LLM" OR "Data Scientist" OR "Machine Learning") (Gurugram OR Gurgaon OR Noida OR Delhi OR Bengaluru OR Hyderabad OR Pune) apply -naukri -linkedin -indeed',
              'careers "Data Scientist" OR "ML Engineer" OR "AI Engineer" ("HDFC" OR "ICICI" OR "Axis Bank" OR "Bajaj Finserv" OR "Paytm" OR "PhonePe" OR "Razorpay" OR "Pine Labs" OR "Cred" OR "Groww" OR "Navi" OR "Jio Financial" OR "Aditya Birla Capital")',
              '("Series A" OR "Series B" OR "Series C" OR seed OR "YC" OR "funded startup") ("AI Engineer" OR "LLM Engineer" OR "GenAI Engineer" OR "ML Engineer") India careers apply -naukri -linkedin -indeed',
              'startup careers ("AI Engineer" OR "Founding Engineer" OR "GenAI Engineer" OR "AI Agent") (Gurugram OR Gurgaon OR Bengaluru OR Hyderabad OR Pune OR Noida OR "Remote India") apply -naukri -linkedin -indeed',
              'site:recruitee.com OR site:breezy.hr OR site:freshteam.com OR site:pinpointhq.com OR site:jobs.workable.com OR site:careers.kula.ai ("AI Engineer" OR "ML Engineer" OR "Data Scientist" OR "GenAI") India',
              '"we are hiring" ("AI Engineer" OR "LLM" OR "GenAI" OR "agents") startup India apply now -naukri -linkedin -indeed',
              '(careers OR jobs) ("KYC" OR "fraud" OR "credit risk" OR "underwriting" OR "collections") ("AI Engineer" OR "Data Scientist" OR "ML Engineer") India NBFC OR bank apply']
        try:
            for j in sources.career_pages(cq, max_calls=8):
                if _insert(con, j): n_pass += 1
                n_new += 1
            con.commit()
        except Exception as e: log(f"career pages failed: {str(e)[:100]}", "WARN")
    if c["sources"].get("google_cse") or c["sources"].get("serper"):
        qs = ['site:jobs.lever.co OR site:boards.greenhouse.io OR site:job-boards.greenhouse.io OR site:jobs.ashbyhq.com OR site:apply.workable.com ("AI Engineer" OR "GenAI Engineer" OR "LLM Engineer" OR "ML Engineer") India',
              'site:jobs.lever.co OR site:jobs.ashbyhq.com OR site:boards.greenhouse.io ("Machine Learning" OR "MLOps" OR "Data Scientist" OR "AI Agent") (Gurgaon OR Gurugram OR Bangalore OR Hyderabad OR Pune OR "Remote")',
              'site:jobs.ashbyhq.com OR site:jobs.lever.co "Python Developer" OR "AI Consultant" OR "Applied AI" India OR Remote',
              'site:jobs.smartrecruiters.com OR site:apply.workable.com ("AI Engineer" OR "ML Engineer" OR "Data Scientist") India',
              'site:jobs.lever.co OR site:boards.greenhouse.io OR site:jobs.ashbyhq.com OR site:apply.workable.com (fintech OR NBFC OR lending OR payments OR banking OR "credit risk" OR KYC OR fraud) ("AI Engineer" OR "ML Engineer" OR "Data Scientist" OR "GenAI") India']
        new = sources.serper_search(con, qs) if os.getenv("SERPER_KEY") else sources.google_cse(con, qs)
        if new:
            log(f"search (past 2 days): {new} new boards")
            for r in con.execute("SELECT * FROM seen_boards ORDER BY rowid DESC LIMIT ?", (new,)).fetchall():
                for j in sources.fetch_board(r["ats"], r["token"]): _insert(con, j)
            con.commit()

def score_new(con, c):
    rows = con.execute("SELECT * FROM jobs WHERE status='new' ORDER BY (age_days IS NULL), age_days ASC, discovered_at DESC LIMIT ?", (c["max_llm_scored_per_run"],)).fetchall()
    if not rows: return
    log(f"scoring {len(rows)} jobs with Gemini")
    def work(r):
        j = dict(r); sources.fill_description(j)
        try: return r["id"], j, match.score(j), None
        except Exception as e: return r["id"], j, None, str(e)[:100]
    q = sk = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for jid, j, res, err in ex.map(work, rows):
            if err: set_status(con, jid, "new", f"score error: {err}"); continue
            s, ok, why = res
            if ok: set_status(con, jid, "queued", why, score=s, description=j["description"]); q += 1
            else: set_status(con, jid, "skipped", f"score {s}: {why}", score=s, description=""); sk += 1
    log(f"scoring done: {q} queued, {sk} rejected")

def apply_queue(con, c, mode, driver_factory, t_end, cap_override=None):
    from . import apply as ap
    dry = mode != "auto"
    per_run = min(cap_override or c["max_applications_per_run"], 10 if dry else 10**6)
    left_today = c["max_applications_per_day"] - applied_today(con)
    n_target = max(0, min(per_run, left_today if not dry else per_run))
    states = ("queued",) if dry else ("queued", "dry_run_ok")
    rows = con.execute(f"SELECT * FROM jobs WHERE status IN ({','.join('?'*len(states))}) ORDER BY (COALESCE(age_days, 99) <= 2) DESC, score DESC, COALESCE(age_days, 99) ASC", states).fetchall()
    log(f"applying (mode={mode}): {len(rows)} candidates, target up to {n_target}")
    d = None; done = 0; counts = {}
    for r in rows:
        if done >= n_target or time.time() > t_end: break
        j = dict(r); label = f"{j['company']} - {j['title']} ({j['location'][:30]}) score {j['score']}"
        if (ROOT / "STOP").exists(): log("STOP file found - halting"); break
        try:
            t = tailor.tailor(j, j["id"])
            email_to = (j.get("note") or "").startswith("email:") and j["note"][6:]
            if email_to and j["ats"] == "other":
                if dry: status, note = "dry_run_ok", f"would email {email_to}"
                else:
                    ok, note = mailbox.send_application(email_to, f"Application: {j['title']} - Dhruv Singh", t["cover_text"], [t["resume"]])
                    status = "applied" if ok else "needs_info"
            else:
                d = d or driver_factory()
                try: status, note = ap.apply_to(d, j, t, dry, ROOT / "data" / "shots")
                finally:
                    for h in d.window_handles[1:]: d.switch_to.window(h); d.close()
                    d.switch_to.window(d.window_handles[0])
        except Exception as e:
            status, note = "failed", f"{type(e).__name__}: {str(e)[:120]}"
            try: d and d.quit()
            except Exception: pass
            d = None
        extra = {"applied_at": now_ist().isoformat()} if status == "applied" else {}
        set_status(con, j["id"], status, note, resume_path=t["resume"] if 't' in dir() else None, **extra)
        counts[status] = counts.get(status, 0) + 1
        tag = {"applied": "APPLIED", "dry_run_ok": "DRY-RUN OK"}.get(status, status.upper())
        log(f"{tag}: {label} -> {note[:140]}  <{j['apply_url'][:100]}>")
        if status in ("applied", "dry_run_ok"): done += 1
        lo, hi = c["pause_between_applications_sec"]; time.sleep(random.uniform(lo, hi) if not dry else 3)
    try: d and d.quit()
    except Exception: pass
    log(f"apply stage finished: {counts or 'nothing attempted'}")

def report(con=None):
    con = con or db(); today = now_ist().date().isoformat()
    L = [f"=== Job agent report {now_ist():%Y-%m-%d %H:%M} IST  (mode now: {effective_mode()}) ==="]
    def q(sql, *a): return con.execute(sql, a).fetchall()
    for status, title in (("applied", "APPLIED TODAY"), ("dry_run_ok", "DRY-RUN OK (filled, not submitted)")):
        rows = q("SELECT * FROM jobs WHERE status=? AND updated_at LIKE ? ORDER BY score DESC", status, today + "%")
        L.append(f"\n{title}: {len(rows)}")
        L += [f"  - {r['company']} | {r['title']} | {r['location'][:30]} | score {r['score']} | {r['apply_url']}" for r in rows]
    for status, title in (("needs_info", "NEEDS YOUR INFO"), ("captcha", "BLOCKED BY CAPTCHA (skipped)"), ("needs_manual", "NEEDS MANUAL APPLY (login/unsupported form)"), ("failed", "FAILED")):
        rows = q("SELECT * FROM jobs WHERE status=? AND updated_at LIKE ? ORDER BY score DESC", status, today + "%")
        L.append(f"\n{title}: {len(rows)}")
        L += [f"  - {r['company']} | {r['title']} | {r['note'][:110]} | {r['apply_url']}" for r in rows[:25]]
    n = q("SELECT COUNT(*) c FROM jobs WHERE status='queued'")[0]["c"]; L.append(f"\nQueued for later runs: {n}")
    L.append("Totals ever: " + ", ".join(f"{r['status']}={r['c']}" for r in q("SELECT status, COUNT(*) c FROM jobs GROUP BY status")))
    try:
        comps = [r["company"] for r in q("SELECT company FROM jobs WHERE status='applied'")]
        rep = mailbox.recent_replies(comps) if comps else []
        L.append("\nRECENT EMAILS FROM COMPANIES YOU APPLIED TO: " + ("" if mailbox.available() else "(Gmail app password not set - not checked)"))
        L += ["  - " + x for x in rep]
    except Exception: pass
    text = "\n".join(L); (ROOT / "logs" / "report.txt").write_text(text); return text

def cleanup():
    """Nightly 00:30 IST: wipe logs and screenshots. The dedupe DB is kept so jobs are never applied to twice."""
    n = 0
    for p in glob.glob(str(ROOT / "logs" / "*")): os.remove(p); n += 1
    for p in glob.glob(str(ROOT / "data" / "shots" / "*")): os.remove(p); n += 1
    cutoff = time.time() - 7 * 86400
    for p in glob.glob(str(ROOT / "data" / "resumes" / "*")):
        if os.path.getmtime(p) < cutoff: shutil.rmtree(p, ignore_errors=True)
    con = db(); con.execute("UPDATE jobs SET description='' WHERE status IN ('skipped') OR (updated_at < ? )", ((now_ist() - timedelta(days=14)).isoformat(),)); con.commit(); con.execute("VACUUM")
    print(f"cleanup: removed {n} log/screenshot files")

def main():
    ap_ = argparse.ArgumentParser(prog="agent"); sub = ap_.add_subparsers(dest="cmd")
    r = sub.add_parser("run"); r.add_argument("--dry-run", action="store_true"); r.add_argument("--max", type=int); r.add_argument("--google", action="store_true"); r.add_argument("--no-discover", action="store_true")
    sub.add_parser("cleanup"); sub.add_parser("report")
    t = sub.add_parser("test-url"); t.add_argument("url"); t.add_argument("--title", default="AI Engineer"); t.add_argument("--company", default="Test Co"); t.add_argument("--live", action="store_true")
    a = ap_.parse_args(); c = cfg()
    if a.cmd == "cleanup": return cleanup()
    if a.cmd == "report": return print(report())
    if a.cmd == "test-url":
        from . import apply as ap
        j = dict(id="testurl", company=a.company, title=a.title, location="India", apply_url=a.url, url=a.url, ats=sources.detect_ats(a.url), description="AI engineering role: LLMs, RAG, Python.")
        t_ = tailor.tailor(j, "testurl"); d = ap.new_driver()
        try: print(ap.apply_to(d, j, t_, not a.live, ROOT / "data" / "shots"))
        finally: d.quit()
        return
    mode = effective_mode(a.dry_run)
    if mode == "stopped": return log("STOP file present - not running", "WARN")
    if mode not in ("auto", "dry_run"): return log(f"unknown mode {mode}", "ERROR")
    with Lock() as lk:
        if lk is None: return log("previous run still active - exiting", "WARN")
        con = db(); t_end = time.time() + c["run_time_budget_minutes"] * 60
        log(f"===== run start | mode={mode} | applied today so far: {applied_today(con)} =====")
        from . import apply as ap
        holder = {}
        def drv():
            if "d" not in holder:
                holder["d"] = ap.new_driver()
            return holder["d"]
        try:
            if not a.no_discover: discover(con, c, drv, allow_google=(a.google or now_ist().hour < 9))
            if holder.get("d"):
                try: holder["d"].quit()
                except Exception: pass
                holder.clear()
            score_new(con, c)
            apply_queue(con, c, mode, ap.new_driver, t_end, a.max)
        except Exception as e:
            log(f"run crashed: {type(e).__name__}: {str(e)[:150]}", "ERROR")
        finally:
            if holder.get("d"):
                try: holder["d"].quit()
                except Exception: pass
            report(con); log("===== run end =====")

if __name__ == "__main__": main()
