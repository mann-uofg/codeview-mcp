#!/usr/bin/env python
"""
Replay PR URLs from bench/urls.txt, measure latency for
ingest → analyze → inline (dry-run), and write bench/benchmarks.md.

Skips any PR that 404s / 403s or subprocess returns non-zero.
"""
from __future__ import annotations
import time, json, pathlib, statistics as st, os, subprocess, shlex
from rich.progress import Progress
from github import Github
from codeview_mcp.utils.helpers import parse_pr_url

# ── config ──────────────────────────────────────────────────────────────
URL_FILE = pathlib.Path("bench/urls.txt")
OUT_MD   = pathlib.Path("bench/benchmarks.md")
GH       = Github(os.getenv("GH_TOKEN"))

# ── helpers ─────────────────────────────────────────────────────────────
def clean(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    return line.split()[0]

URLS = [u for u in map(clean, URL_FILE.read_text().splitlines()) if u]

def safe_pull(repo_slug: str, num: int):
    try:
        return GH.get_repo(repo_slug).get_pull(num)
    except Exception as exc:
        print(f"[skip] {repo_slug}#{num} → {exc.__class__.__name__}: {exc}")
        return None

def timed(cmd_parts: list[str]) -> float | None:
    """Run `reviewgenie ...` via subprocess; return latency or None on error."""
    cmd = ["reviewgenie", *cmd_parts]
    t0 = time.perf_counter()
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return time.perf_counter() - t0
    except subprocess.CalledProcessError as exc:
        print(f"[skip] {' '.join(cmd_parts[:2])} → {exc.returncode} {exc.output[:80]}")
        return None

# ── main loop ───────────────────────────────────────────────────────────
results = []
with Progress() as bar:
    for url in bar.track(URLS, description="Benchmarking"):
        repo, num = parse_pr_url(url)

        t_ing = timed(["ingest",  url])
        t_ana = timed(["analyze", url])
        t_inl = timed(["inline",  url, "--style", "nitpick", "--dry-run"])

        if None in (t_ing, t_ana, t_inl):
            continue  # skip rows with any failure

        pr = safe_pull(repo, num)
        accepted = 0
        if pr is not None:
            accepted = sum(
                1 for c in pr.get_issue_comments()
                if "accepted" in (c.body or "").lower()
            )

        results.append(dict(
            pr=url, ingest=t_ing, analyze=t_ana, inline=t_inl, accepted=accepted
        ))

# ── Markdown report ─────────────────────────────────────────────────────
if not results:
    print("No successful rows; aborting.")
    exit()

md = ["# ReviewGenie Bench – Day 7",
      "",
      "| PR | ingest (s) | analyze (s) | inline (s) | accepted |",
      "|----|-----------:|------------:|-----------:|---------:|"]

for r in results:
    md.append(f"| [{r['pr'].split('/')[-1]}]({r['pr']}) "
              f"| {r['ingest']:.2f} | {r['analyze']:.2f} "
              f"| {r['inline']:.2f} | {r['accepted']} |")

md += ["",
       "## Totals / Averages",
       f"* avg ingest   : **{st.mean(r['ingest']  for r in results):.2f}s**",
       f"* avg analyze  : **{st.mean(r['analyze'] for r in results):.2f}s**",
       f"* avg inline   : **{st.mean(r['inline']  for r in results):.2f}s**",
       f"* comments accepted total: **{sum(r['accepted'] for r in results)}**"]

OUT_MD.parent.mkdir(exist_ok=True)
OUT_MD.write_text("\n".join(md))
print("✅ Bench complete →", OUT_MD)
