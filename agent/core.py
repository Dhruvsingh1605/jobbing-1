"""Config, daily log, SQLite store and lock handling."""
import fcntl, hashlib, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
IST = timezone(timedelta(hours=5, minutes=30))
LOG_FILE = ROOT / "logs" / "today.log"
DB_FILE = ROOT / "data" / "jobs.db"

def now_ist(): return datetime.now(IST)

def load_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text())

_cfg = _prof = None
def cfg():
    global _cfg
    if _cfg is None: _cfg = load_yaml("preferences.yaml")
    return _cfg
def profile():
    global _prof
    if _prof is None: _prof = load_yaml("profile.yaml")
    return _prof

def log(msg, level="INFO"):
    """Short human-readable line. File is wiped every night at 00:30 IST by `cleanup`."""
    line = f"{now_ist():%H:%M:%S} [{level}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f: f.write(line + "\n")

def effective_mode(force_dry=False):
    c = cfg()
    if force_dry: return "dry_run"
    if (ROOT / "STOP").exists(): return "stopped"
    mode = c.get("mode", "dry_run")
    lf = c.get("live_from")
    if mode == "auto" and lf and now_ist().date().isoformat() < str(lf): return "dry_run"
    return mode

class Lock:
    def __init__(self, name="run"): self.path = ROOT / "data" / f".{name}.lock"; self.fh = None
    def __enter__(self):
        self.fh = open(self.path, "w")
        try: fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return None
        return self
    def __exit__(self, *a):
        if self.fh: fcntl.flock(self.fh, fcntl.LOCK_UN); self.fh.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, location TEXT, url TEXT, apply_url TEXT,
  ats TEXT, description TEXT, posted TEXT, discovered_at TEXT, status TEXT DEFAULT 'new',
  score INTEGER, reason TEXT, note TEXT, resume_path TEXT, applied_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);
CREATE TABLE IF NOT EXISTS seen_boards(ats TEXT, token TEXT, PRIMARY KEY(ats, token));
"""
def db():
    DB_FILE.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try: con.execute("ALTER TABLE jobs ADD COLUMN age_days REAL")
    except sqlite3.OperationalError: pass
    return con

def job_id(company, title, url):
    key = re.sub(r"[?#].*$", "", (url or "").lower().strip().rstrip("/"))
    return hashlib.sha1(key.encode()).hexdigest()[:16]

def dedupe_key(company, title):
    return re.sub(r"[^a-z0-9]", "", f"{company}{title}".lower())

def set_status(con, jid, status, note=None, **fields):
    sets = ["status=?", "updated_at=?"]; vals = [status, now_ist().isoformat()]
    if note is not None: sets.append("note=?"); vals.append(note[:500])
    for k, v in fields.items(): sets.append(f"{k}=?"); vals.append(v)
    vals.append(jid)
    con.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", vals); con.commit()

def applied_today(con):
    d = now_ist().date().isoformat()
    return con.execute("SELECT COUNT(*) FROM jobs WHERE status='applied' AND applied_at LIKE ?", (d + "%",)).fetchone()[0]

def already_applied_company_title(con, company, title):
    k = dedupe_key(company, title)
    for r in con.execute("SELECT company,title FROM jobs WHERE status IN ('applied','dry_run_ok')"):
        if dedupe_key(r["company"], r["title"]) == k: return True
    return False
