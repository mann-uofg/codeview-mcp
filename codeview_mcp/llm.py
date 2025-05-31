"""
LLM helper – Day 7 version
1) local CodeLlama → fast smell tag list
2) cloud LLM (Groq, Together, etc.) → prose summary & base risk
3) static RULES scan → additional risk penalty
"""
from __future__ import annotations

import os, textwrap, json, re, requests
from openai import OpenAI
import tiktoken  # keep import; tokenizer may be used later

from codeview_mcp.rules import RULES  # static regex rules

# ── config ───────────────────────────────────────────────────────────────
LOCAL_URL    = "http://localhost:11434/api/generate"
LOCAL_MODEL  = "codellama:13b-instruct"
# Groq 2025-05 deprecation: migrate to llama-3.1-8b-instant
CLOUD_MODEL = os.getenv("RG_CLOUD_MODEL", "llama-3.1-8b-instant")
LOCAL_TIMEOUT = int(os.getenv("CODEVIEW_LOCAL_TIMEOUT", "45"))

_API_KEY  = os.getenv("OPENAI_API_KEY")
_BASE_URL = os.getenv("OPENAI_BASE_URL")
_client   = OpenAI(api_key=_API_KEY, base_url=_BASE_URL) if _API_KEY and _BASE_URL else None

# ── helper fns ───────────────────────────────────────────────────────────

def _local_complete(prompt: str, max_tokens: int = 256) -> str | None:
    """Return deterministic response from local Ollama; None on failure."""
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


def _cloud_chat(messages: list[dict], max_tokens: int = 512) -> str:
    if _client is None:
        return "{}"  # offline fallback
    resp = _client.chat.completions.create(
        model=CLOUD_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content

# ── public API ────────────────────────────────────────────────────────────

def _apply_static_rules(diff_snippet: str, base_risk: float) -> tuple[list[str], float]:
    """Return list of rule IDs hit & new risk score."""
    hits: list[str] = []
    penalties = 0.0
    for rule in RULES:
        if re.search(rule["pattern"], diff_snippet, re.M | re.I):
            hits.append(rule["id"])
            penalties += rule["severity"]
    return hits, min(1.0, base_risk + penalties)


def analyze(diff_snippet: str, loc_added: int, loc_removed: int) -> dict:
    """Return summary, smells[], rule_hits[], risk_score ∈ [0,1]."""

    # Stage 1 – fast smell list
    smell_prompt = f"List up to 5 code-smells you spot:\n\n{diff_snippet}\n"
    smells_raw   = _local_complete(smell_prompt) or ""
    smells       = [s.lstrip("- ").strip() for s in smells_raw.splitlines() if s.strip()]

    # Stage 2 – cloud reasoning
    cloud_messages = [
        {"role": "system", "content": "You are a senior software reviewer."},
        {"role": "user", "content": textwrap.dedent(f"""
            Provide:
            1. One‑paragraph summary of the change.
            2. Up to 5 key issues (reuse any from this list if valid): {smells}.
            3. A risk score 0‑1 (float, 1 = highest risk) based on complexity & security.

            Diff context below ```\n{diff_snippet}\n```
            Total ++{loc_added} --{loc_removed}.
            Output JSON with keys summary, smells, risk_score.
        """)},
    ]

    raw = _cloud_chat(cloud_messages)
    m   = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}

    summary    = data.get("summary", "n/a")
    smells_out = data.get("smells", smells)
    base_risk  = float(data.get("risk_score", 0.5))

    # Stage 3 – static rule penalties
    rule_hits, final_risk = _apply_static_rules(diff_snippet, base_risk)

    return {
        "summary":    summary,
        "smells":     smells_out,
        "rule_hits":  rule_hits,
        "risk_score": round(final_risk, 2),
    }
