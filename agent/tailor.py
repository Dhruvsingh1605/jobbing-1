"""Per-job resume (select/reorder REAL bullets only) and cover letter, with a numeric fact-guard."""
import json, re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from xml.sax.saxutils import escape
from .core import ROOT, profile
from . import llm

def _corpus():
    return json.dumps(profile()).lower()

def _numbers_ok(text, extra=""):
    corpus = _corpus() + " " + extra.lower()
    return all(n in corpus for n in re.findall(r"\d[\d,.]*\d|\d", text))

def _bullet_index():
    p = profile(); idx = {}
    for e in p["experience"]:
        for b in e.get("bullets", []): idx[b["id"]] = b["text"]
        for pr in e.get("projects", []):
            for b in pr["bullets"]: idx[b["id"]] = b["text"]
    for pr in p["projects"]:
        for b in pr["bullets"]: idx[b["id"]] = b["text"]
    return idx

def plan(job):
    p = profile(); idx = _bullet_index()
    prompt = f"""Tailor a resume for this job using ONLY the candidate facts. Return JSON:
{{"summary": "2-3 sentence professional summary", "bullet_order": ["ALL bullet ids, most relevant to the job first"],
 "skill_order": ["skill category names, most relevant first"], "highlight_skills": ["up to 8 skills from the candidate list that the job asks for"]}}
Rules: summary may reuse numbers/facts that exist in the candidate data but must not add any new number, employer, tool or claim.
Candidate summary: {p['summary']}
Bullets: {json.dumps(idx)}
Skill categories: {list(p['skills'].keys())}
Job: {job['title']} at {job['company']}
{(job['description'] or '')[:3500]}"""
    try:
        r = llm.ask(prompt, json_out=True)
    except Exception:
        r = {}
    summary = r.get("summary") or p["summary"]
    if not _numbers_ok(summary): summary = p["summary"]
    order = [b for b in r.get("bullet_order", []) if b in idx] or list(idx)
    return summary, order, [c for c in r.get("skill_order", []) if c in p["skills"]], r.get("highlight_skills", [])

def build_resume(job, outdir):
    p = profile(); idx = _bullet_index()
    summary, order, skill_order, hi = plan(job)
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "Dhruv_Singh_Resume.pdf"
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=11.5)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.5, leading=13, spaceBefore=6)
    name = ParagraphStyle("n", fontName="Helvetica-Bold", fontSize=17, leading=20, alignment=1)
    ctr = ParagraphStyle("c", parent=base, alignment=1)
    bul = ParagraphStyle("bl", parent=base, leftIndent=10, bulletIndent=2)
    sub = ParagraphStyle("s", parent=base, fontName="Helvetica-Bold")
    i = p["identity"]; s = []
    s += [Paragraph(escape(i["full_name"]), name),
          Paragraph(escape(f"{i['phone']} | {i['email']} | {i['location_full']}"), ctr),
          Paragraph(escape(f"{i['linkedin'].replace('https://www.','')} | {i['github'].replace('https://','')}"), ctr)]
    def sec(t): s.extend([Paragraph(t, h), HRFlowable(width="100%", thickness=0.6, color="#000000", spaceAfter=3)])
    sec("Professional Summary"); s.append(Paragraph(escape(summary), base))
    sec("Technical Skills")
    cats = skill_order + [c for c in p["skills"] if c not in skill_order]
    for c in cats:
        items = p["skills"][c]; items = [x for x in items if x in hi] + [x for x in items if x not in hi]
        s.append(Paragraph(f"<b>{escape(c)}:</b> {escape(', '.join(items))}", base))
    sec("Work Experience")
    order = order + [b for b in idx if b not in order]  # reorder only; never drop real achievements
    chosen = set(order)
    for e in p["experience"]:
        s.append(Paragraph(f"{escape(e['title'])} | {escape(e['company'])}, {escape(e['location'])} &nbsp;&nbsp; <i>{escape(e['dates'])}</i>", sub))
        groups = [(None, e.get("bullets", []))] + [(f"{pr['name']} | {pr['subtitle']}", pr["bullets"]) for pr in e.get("projects", [])]
        for label, bl in groups:
            keep = sorted([b for b in bl if b["id"] in chosen], key=lambda b: order.index(b["id"]))
            if not keep: continue
            if label: s.append(Paragraph(f"<b>{escape(label.split(' | ')[0])}</b> | <i>{escape(label.split(' | ')[1])}</i>", base))
            for b in keep: s.append(Paragraph(escape(b["text"]), bul, bulletText="•"))
    pj = [x for x in p["projects"] if any(b["id"] in chosen or True for b in x["bullets"])]
    if pj:
        sec("Projects")
        for x in pj:
            s.append(Paragraph(f"<b>{escape(x['name'])}</b> | <i>{escape(x['tech'])}</i>", base))
            for b in x["bullets"]: s.append(Paragraph(escape(b["text"]), bul, bulletText="•"))
    sec("Education")
    for e in p["education"]:
        s.append(Paragraph(f"<b>{escape(e['degree'])}</b> | {escape(e['school'])} &nbsp;&nbsp; <i>{escape(e['years'])}</i> &nbsp; CGPA: {escape(e['cgpa'])}", base))
    sec("Certifications")
    for c in p["certifications"][:4]: s.append(Paragraph(escape(c), bul, bulletText="•"))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=11*mm, bottomMargin=10*mm,
                      title="Dhruv Singh - Resume", author="Dhruv Singh").build(s)
    return str(path)

def cover_letter(job):
    p = profile()
    prompt = f"""Write a concise, genuine cover letter (110-160 words, no placeholders, no 'Dear Hiring Manager' fluff beyond one greeting line, sign off 'Dhruv Singh').
Use ONLY these facts: {json.dumps({'summary': p['summary'], 'experience': _bullet_index(), 'notice_period': '30 days', 'location': 'Gurugram, India'})}
Do not invent numbers, employers, or skills. Mention 2 concrete achievements relevant to the role. Mention notice period of 30 days only if natural.
Job: {job['title']} at {job['company']} ({job.get('location','')})
{(job['description'] or '')[:2500]}
Return plain text only."""
    try:
        txt = llm.ask(prompt, temperature=0.5)
        if _numbers_ok(txt, job.get("description") or "") and 60 < len(txt.split()) < 260: return txt
    except Exception: pass
    return (f"Hello,\n\nI'm applying for the {job['title']} role at {job['company']}. I'm an AI Engineer with 1.5+ years of experience building "
            "production LLM, RAG and multi-agent systems for banks and NBFCs, including an agent covering 50+ document types at 80% lower LLM cost "
            "and a fraud engine that caught Rs 78 lakh of fraud in a single day. I work mainly with Python, LangChain, LangGraph, FastAPI and AWS. "
            "My notice period is 30 days.\n\nThank you for your time.\n\nDhruv Singh")

def cover_letter_pdf(text, path):
    st = ParagraphStyle("c", fontName="Helvetica", fontSize=10.5, leading=14.5)
    flow = []
    for para in text.split("\n\n"): flow += [Paragraph(escape(para).replace("\n", "<br/>"), st), Spacer(1, 6)]
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=22*mm, rightMargin=22*mm, topMargin=22*mm, bottomMargin=20*mm).build(flow)
    return str(path)

def tailor(job, jid):
    d = ROOT / "data" / "resumes" / jid
    resume = build_resume(job, d)
    text = cover_letter(job)
    (d / "cover_letter.txt").write_text(text)
    cover_letter_pdf(text, d / "Dhruv_Singh_Cover_Letter.pdf")
    return {"resume": resume, "cover_pdf": str(d / "Dhruv_Singh_Cover_Letter.pdf"), "cover_text": text}
