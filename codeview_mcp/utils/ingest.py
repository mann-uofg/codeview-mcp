"""
Diff-ingestion helper for ReviewGenie
-------------------------------------
* Pulls a PR’s raw .diff via GitHub API
* Parses it with `unidiff.PatchSet`
* Adds rich per-hunk metadata
* Caches the JSON result in SQLite for 24 h
"""

from __future__ import annotations

import os
import requests
from typing import Any

from github import Github
from unidiff import PatchSet

from codeview_mcp.utils.helpers import parse_pr_url   # central regex
from codeview_mcp.cache import db                     # tiny SQLite wrapper

# ---------------------------------------------------------------------------

_GH = Github(os.getenv("GH_TOKEN"))

# ---------------------------------------------------------------------------


def fetch_pr(pr_url: str) -> dict[str, Any]:
    """
    Return a JSON-serialisable dict with:

        title, author, state, additions, deletions, changed_files,
        files = [
            {
              path, is_binary,
              hunks = [
                  {
                    section_header,           # '@@ def foo(): @@' (may be None)
                    source_start, source_len,
                    target_start, target_len,
                    added, removed
                  }, …
              ]
            }, …
        ],
        cached : bool   # True if served from SQLite cache

    Results older than 24 h are refreshed.
    """
    repo_slug, pr_num = parse_pr_url(pr_url)
    cache_key = f"{repo_slug}#{pr_num}"

    if (cached := db.get(cache_key)):
        cached["cached"] = True
        return cached

    pr = _GH.get_repo(repo_slug).get_pull(pr_num)

    # --- download raw diff --------------------------------------------------
    diff_txt = requests.get(
        pr.diff_url,
        headers={"Authorization": f"token {os.getenv('GH_TOKEN')}"},
        timeout=30,
    ).text

    patch = PatchSet(diff_txt)

    files: list[dict[str, Any]] = []
    for f in patch:
        hunks = [
            {
                "section_header": h.section_header,  # str | None
                "source_start":  h.source_start,
                "source_len":    h.source_length,
                "target_start":  h.target_start,
                "target_len":    h.target_length,
                "added":         h.added,
                "removed":       h.removed,
            }
            for h in f
        ]
        files.append(
            {
                "path":      f.path,
                "is_binary": f.is_binary_file,
                "hunks":     hunks,
            }
        )

    summary: dict[str, Any] = {
        "title":         pr.title,
        "author":        pr.user.login,
        "state":         pr.state,
        "additions":     pr.additions,
        "deletions":     pr.deletions,
        "changed_files": pr.changed_files,
        "files":         files,
        "cached":        False,
    }

    db.put(cache_key, summary)
    return summary
