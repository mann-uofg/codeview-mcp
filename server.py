"""
ReviewGenie – MCP server entry-point
Day-2 version: adds ingest_pr() tool and uses shared helpers/cache.
"""

from __future__ import annotations

import os
from mcp.server.fastmcp import FastMCP
from github import Github

from codeview_mcp.utils.helpers import parse_pr_url          # central regex
from codeview_mcp.utils.ingest import fetch_pr              # new Day-2 logic
from codeview_mcp.utils.prompt import build_diff_prompt
from codeview_mcp.llm import analyze as llm_analyze
from codeview_mcp.utils.locator import locate
from codeview_mcp.config import load as load_cfg

# ---------------------------------------------------------------------------
# GitHub authentication
# ---------------------------------------------------------------------------

GH_TOKEN = os.getenv("GH_TOKEN")
if not GH_TOKEN:
    raise RuntimeError(
        "GH_TOKEN not found in environment. "
        "Create a fine-grained PAT and `export GH_TOKEN=...`."
    )

gh = Github(GH_TOKEN)        # lightweight client for quick calls

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("reviewgenie")   # auto-registers @mcp.tool() decorated callables

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def ping(pr_url: str) -> dict:
    """
    Light sanity-check: return title, author and state for a GitHub PR.

    Example call:
        ping("https://github.com/psf/requests/pull/6883")
    """
    repo_slug, pr_num = parse_pr_url(pr_url)
    pr = gh.get_repo(repo_slug).get_pull(pr_num)

    return {
        "title": pr.title,
        "author": pr.user.login,
        "state": pr.state,
    }


@mcp.tool()
def ingest_pr(pr_url: str) -> dict:
    """
    **Day-2 core tool**

    Fetch the PR's diff, per-file hunks and metadata.
    Results are cached for 24 h in ~/.cache/reviewgenie.db.

    Returns a JSON-serialisable dict:
        {
          title, author, state, additions, deletions, changed_files,
          files: [ {path, is_binary, hunks:[…]} ],
          cached: bool
        }
    """
    return fetch_pr(pr_url)

@mcp.tool()
def analyze_pr(pr_url: str) -> dict:
    """
    Run two-stage LLM review and return:
      {summary, smells[], risk_score}
    """
    pr_json = fetch_pr(pr_url)
    diff_prompt = build_diff_prompt(pr_json["files"])
    return llm_analyze(
        diff_prompt,
        pr_json["additions"],
        pr_json["deletions"],
    )

@mcp.tool()
def inline_comments(pr_url: str, style: str | None = None) -> dict:
    """
    Post inline review comments based on analyze_pr output.
    Returns {'posted': int}.
    """
    cfg   = load_cfg()
    if style is None:
        style = cfg["style"]

    pr_json  = fetch_pr(pr_url)
    analysis = analyze_pr(pr_url)        # reuse existing tool

    targets = locate(analysis["smells"], pr_json["files"])
    repo_slug, pr_num = parse_pr_url(pr_url)
    pr = gh.get_repo(repo_slug).get_pull(pr_num)

    posted = 0
    body_tmpl = {
        "nitpick":   "- *Nitpick*: {smell}",
        "security":  "⚠️ **Security**: {smell}",
        "perf":      "⏱ **Performance**: {smell}",
    }[style]

    for path, line_no, smell in targets:
        pr.create_review_comment(
            body_tmpl.format(smell=smell),
            commit_id = pr.head.sha,
            path      = path,
            line      = line_no,
            side      = "RIGHT",
        )
        posted += 1

    return {"posted": posted, "style": style}

# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Stdio transport: the MCP host will spawn this process and talk via stdin/stdout.
    mcp.run()
