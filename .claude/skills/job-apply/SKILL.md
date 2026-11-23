---
name: job-apply
description: Run, review or change Dhruv Singh's autonomous job-application agent (discovers AI/ML jobs on ATS career pages and free job feeds, scores fit with Gemini, tailors resume + cover letter, fills and submits forms with Selenium, runs from cron 4x/day). Use when asked to apply to jobs, check today's applications/EOD report, add a job source, fix a failing application form, change targeting/salary/location rules, pause or resume the agent, or update the candidate profile.
---

# job-apply

The agent lives in `/root/jobbing/job-agent` (Python venv at `.venv`). Candidate: **Dhruv Singh**.

## Where things are
| What | Path |
|---|---|
| Verified facts + answers bank (CTC, notice, visa, EEO) | `config/profile.yaml` - the ONLY source of facts |
| Targeting, caps, mode, blocklist, sources | `config/preferences.yaml` |
| Company job-board tokens (grows automatically) | `config/boards.yaml` + `seen_boards` table |
| Secrets (Gemini key, optional Gmail app password) | `.env` (chmod 600) - never print or log it |
| Dedupe DB (kept forever) | `data/jobs.db` (SQLite, table `jobs`) |
| Today's log + EOD report (wiped 00:30 IST) | `logs/today.log`, `logs/report.txt` |
| Code | `agent/` : `sources.py` discover, `match.py` filter+score, `tailor.py` resume/cover letter, `apply.py` Selenium, `mailbox.py` Gmail, `run.py` CLI |

## Commands (run from `/root/jobbing/job-agent`)
- `.venv/bin/python -m agent run [--dry-run] [--max N] [--google]` - one full cycle
- `.venv/bin/python -m agent report` - print today's applied / needs-info / captcha / failed
- `.venv/bin/python -m agent test-url <url> --company X --title Y [--live]` - dry-run ONE form (default never submits)
- `.venv/bin/python -m agent cleanup` - the nightly wipe
- Schedule: `scripts/install_cron.sh` (06:00, 11:00, 15:00, 18:00 IST + 00:30 cleanup). Pause everything: `touch STOP`; resume: `rm STOP`.
- Modes: `mode: auto` submits, `mode: dry_run` fills but never submits. `live_from` forces dry-run before that date.

## Hard rules (never relax without the user saying so)
1. **Never invent facts.** Answers come only from `profile.yaml`. A required answer that is not there -> status `needs_info`, skip, log it. Do not guess DOB, address, PAN, references, tool experience not in the CV.
2. **Resume tailoring may only select/reorder real bullets and rewrite the summary**; every number must exist in the profile (`tailor._numbers_ok`). Cover letters pass the same guard.
3. **No CAPTCHA / bot-wall bypassing.** Visible CAPTCHA, Cloudflare challenge, login wall -> status `captcha`/`needs_manual`, skip, log. Do not add solvers, stealth plugins or proxies. Also skip forms that contain an employer 'prove you are not a bot / no AI-written answers / decode this' screening question (`BOT_SCREEN` in apply.py) - answering them defeats the employer's own gate.
4. **No LinkedIn, Naukri or anything needing a logged-in personal account.** Login-free sources and ATS pages only.
5. **Never apply to current/past employers** (blocklist in preferences) or the same company+title twice.
6. Optional consents (marketing, future opportunities, AI note-taker) are NOT opted into; only consents required to submit are ticked.
7. Work authorisation: authorised in India (no sponsorship needed); outside India requires visa sponsorship. Veteran: no. Gender/ethnicity/disability: decline to self-identify.
8. Logs are deleted nightly; do not add persistent logs of personal data elsewhere.

## Typical tasks
- **"What happened today?"** -> `report`, then summarise: applied, needs_info (what question), captcha-blocked, failed (why).
- **A form keeps failing** -> `test-url` on its URL, read `data/shots/*_filled.png`, fix `apply.py` (field extraction `JS_FIELDS`, `fill_field`, or the rules in `FORM_SYSTEM`). Re-test dry-run before touching `mode`.
- **Change targeting** -> edit `preferences.yaml` (titles, `exclude_title_words`, `min_score`, locations, caps). Rows already `skipped` are not re-scored; to re-evaluate: `UPDATE jobs SET status='new' WHERE status='skipped' AND note LIKE 'score %'`.
- **Add a source** -> add a function to `sources.py` returning job dicts (`_mk(...)`), register it in `aggregators()` or `ats_boards()`.
- **Update facts** (new job, new CTC) -> edit `profile.yaml` only; the resume PDF is regenerated per job.
- **Gmail**: the cron job cannot use the Claude Gmail connector. For verification codes and the reply digest, set `GMAIL_APP_PASSWORD` in `.env` (Google account -> Security -> App passwords). Interactively, you may use the Gmail connector to check recruiter replies.
- **Gemini models**: configured in `agent/llm.py` (`gemini-3.5-flash`, fallback `gemini-3.1-flash-lite`). If calls 404, list models with the REST `models` endpoint and update.

## Freshness & Google
- Postings older than `max_job_age_days` (default 10) are dropped; the newest are scored first and, in the apply queue, postings <=2 days old go first. Cron runs 4x/day, so new postings are normally picked up within hours.
- Raw Google scraping is OFF: Google CAPTCHA-blocks this VPS IP and we do not bypass it. Gemini's Google-Search tool needs a billed key (free tier returns 429).
- Official route: set `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` in `.env` (Programmable Search Engine searching the whole web + Custom Search API key; 100 free queries/day). `sources.google_cse` then runs past-2-day ATS queries each run and registers new company boards.
- To widen coverage: add company slugs to `NAMES` in `scripts/expand_boards.py` and run it (keeps only boards that respond; currently 164).

## Known limits (be honest about these with the user)
Many career pages sit behind CAPTCHA/anti-bot (Coinbase, some Greenhouse/Lever/Ashby tenants) and will be skipped; Workday/iCIMS/Taleo need accounts and are queued as `needs_manual`. International roles are applied to only when the posting offers visa sponsorship/relocation or is remote-open to India. Expect most days to yield a modest number of submitted applications, not dozens.
