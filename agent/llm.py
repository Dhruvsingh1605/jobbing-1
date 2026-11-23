"""Gemini client (REST). Key comes from .env only; it is never logged."""
import json, os, re, time
import requests
from .core import log

MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), "gemini-3.1-flash-lite", "gemini-flash-latest"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

def _call(prompt, system=None, json_out=False, temperature=0.2, model=None):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "thinkingConfig": {"thinkingLevel": "low"}}}
    if system: body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_out: body["generationConfig"]["responseMimeType"] = "application/json"
    r = requests.post(URL.format(m=model), json=body, timeout=120,
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    if r.status_code == 400 and "thinking" in r.text.lower():
        body["generationConfig"].pop("thinkingConfig", None)
        r = requests.post(URL.format(m=model), json=body, timeout=120, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.json().get('error', {}).get('message', '')[:120]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))

def ask(prompt, system=None, json_out=False, temperature=0.2, retries=4):
    last = None
    for attempt in range(retries):
        for m in MODELS:
            try:
                out = _call(prompt, system, json_out, temperature, m)
                if json_out:
                    out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M).strip()
                    return json.loads(out)
                return out.strip()
            except Exception as e:
                last = e
                if "429" in str(e): time.sleep(10 + attempt * 10)
        time.sleep(3 + attempt * 5)
    raise RuntimeError(f"LLM failed: {last}")
