"""
LLM helper: 2-stage scoring
1) local CodeLlama → quick smells
2) cloud (Groq) → write prose + risk
"""
from __future__ import annotations
import os, textwrap, tiktoken
from openai import OpenAI
import requests

# ── config ───────────────────────────────────────────────────────────────
LOCAL_URL   = "http://localhost:11434/api/generate"
LOCAL_MODEL = "codellama:13b-instruct"
CLOUD_MODEL = "llama3-8b-8192"
LOCAL_TIMEOUT = int(os.getenv("CODEVIEW_LOCAL_TIMEOUT", "45"))  # was 15
client      = OpenAI(api_key=os.environ["OPENAI_API_KEY"],
                     base_url=os.environ["OPENAI_BASE_URL"])

def _local_complete(prompt: str, max_tokens=256) -> str | None:
    try:
        resp = requests.post(
            LOCAL_URL,
            json={
                "model": LOCAL_MODEL,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.0,
                "max_tokens": max_tokens,
            },
            timeout=LOCAL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except Exception as e:
        print("[warn] local LLM failed:", e)
        return None

def _cloud_chat(messages: list[dict], max_tokens=512) -> str:
    resp = client.chat.completions.create(
        model=CLOUD_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content

# ── public API ────────────────────────────────────────────────────────────
def analyze(diff_snippet: str, loc_added: int, loc_removed: int) -> dict:
    """Return summary, smells[], risk_score∈[0-1]."""
    # Stage 1 – quick static smell tags
    smell_prompt = f"""List up to 5 code-smells you spot:\n\n{diff_snippet}\n"""
    smells_raw = _local_complete(smell_prompt) or ""
    smells = [s.lstrip("- ").strip() for s in smells_raw.splitlines() if s.strip()]

    # Stage 2 – cloud reasoning
    cloud_prompt = [
        {"role":"system","content":"You are a senior software reviewer."},
        {"role":"user","content":
        textwrap.dedent(f"""
        Provide:
        1. One-paragraph summary of the change.
        2. Up to 5 key issues (reuse any from this list if valid): {smells}.
        3. A risk score 0-1 (float, 1 = highest risk) based on complexity & security.

        Diff context below ```\n{diff_snippet}\n```
        Total ++{loc_added} --{loc_removed}.
        Output JSON with keys summary, smells, risk_score.
        """)},
    ]
    import json, re
    raw = _cloud_chat(cloud_prompt)
    # Extract first JSON block
    m = re.search(r'\{.*\}', raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    return {
        "summary":    data.get("summary", "n/a"),
        "smells":     data.get("smells", smells),
        "risk_score": float(data.get("risk_score", 0.5)),
    }
