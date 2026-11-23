"""Gmail via IMAP/SMTP with an app password (the cron job cannot use the Claude Gmail connector).
Without GMAIL_APP_PASSWORD in .env everything here degrades gracefully."""
import email, imaplib, os, re, smtplib, time
from email.message import EmailMessage
from email.header import decode_header
from .core import log

def _cred():
    u, p = os.getenv("GMAIL_ADDRESS"), (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    return (u, p) if u and p else (None, None)

def available(): return _cred()[0] is not None

def _dec(s):
    out = ""
    for t, enc in decode_header(s or ""): out += t.decode(enc or "utf-8", "ignore") if isinstance(t, bytes) else t
    return out

def _body(m):
    if m.is_multipart():
        for part in m.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try: return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                except Exception: pass
        return ""
    try: return m.get_payload(decode=True).decode(m.get_content_charset() or "utf-8", "ignore")
    except Exception: return ""

def _imap():
    u, p = _cred()
    M = imaplib.IMAP4_SSL("imap.gmail.com"); M.login(u, p); M.select("INBOX"); return M

def _pick_code(text):
    """Pick the security code out of an email. Real codes are random mixed-case/digit tokens (Greenhouse: 8 chars);
    plain words like 'resubmit' must never qualify."""
    def ok(t): return bool(re.search(r"\d", t) or (re.search(r"[a-z]", t) and re.search(r"[A-Z]", t))) and not re.fullmatch(r"[A-Z][a-z]+", t)
    for mm in re.finditer(r"code\W{0,40}?([A-Za-z0-9]{6,10})\b", text, re.I):
        if ok(mm.group(1)): return mm.group(1)
    for t in re.findall(r"\b([A-Za-z0-9]{8})\b", text):
        if ok(t): return t
    return None

def verification_code(since_epoch, wait=75):
    """Greenhouse & others email a code after submit. Returns code or None."""
    if not available(): return None
    end = time.time() + wait
    while time.time() < end:
        try:
            M = _imap()
            _, ids = M.search(None, '(UNSEEN SINCE "%s")' % time.strftime("%d-%b-%Y", time.gmtime(since_epoch - 86400)))
            for i in reversed(ids[0].split()[-15:]):
                _, d = M.fetch(i, "(RFC822)"); m = email.message_from_bytes(d[0][1])
                if email.utils.parsedate_to_datetime(m["Date"]).timestamp() < since_epoch - 30: continue
                subj = _dec(m["Subject"]); text = subj + " " + re.sub(r"<[^>]+>", " ", _body(m))
                if re.search(r"security code|verification code|verify your|confirm your", text, re.I):
                    code = _pick_code(text)
                    if code: M.logout(); return code
            M.logout()
        except Exception as e:
            log(f"imap error: {str(e)[:80]}", "WARN"); return None
        time.sleep(6)
    return None

def recent_replies(companies, hours=24):
    """Subjects of recent mails mentioning applied companies - for the EOD report."""
    if not available(): return []
    out = []
    try:
        M = _imap()
        _, ids = M.search(None, '(SINCE "%s")' % time.strftime("%d-%b-%Y", time.gmtime(time.time() - hours * 3600)))
        for i in reversed(ids[0].split()[-80:]):
            _, d = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])"); m = email.message_from_bytes(d[0][1])
            line = f"{_dec(m['From'])[:50]} | {_dec(m['Subject'])[:90]}"
            if any(c.lower()[:12] in line.lower() for c in companies): out.append(line)
        M.logout()
    except Exception as e: log(f"imap error: {str(e)[:80]}", "WARN")
    return out

def send_application(to, subject, body, attachments):
    u, p = _cred()
    if not u: return False, "GMAIL_APP_PASSWORD not set"
    m = EmailMessage(); m["From"] = f"Dhruv Singh <{u}>"; m["To"] = to; m["Subject"] = subject; m.set_content(body)
    for path in attachments:
        with open(path, "rb") as f: m.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(path))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s: s.starttls(); s.login(u, p); s.send_message(m)
        return True, "email sent"
    except Exception as e: return False, f"smtp error {str(e)[:80]}"
