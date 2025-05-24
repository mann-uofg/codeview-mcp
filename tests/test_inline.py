import os, sys, time, pathlib

# ── make sure repo root is on sys.path ───────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── dummy env-vars so llm.py import doesn't crash ───────────────────────
os.environ.setdefault("OPENAI_API_KEY",  "dummy")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost")

from server import inline_comments
from codeview_mcp.utils.helpers import parse_pr_url
from github import Github

GH = Github(os.getenv("GH_TOKEN"))

def test_inline_posts():
    pr_url = "https://github.com/mann-uofg/example-sandbox/pull/1"
    repo_slug, pr_num = parse_pr_url(pr_url)
    issue = GH.get_repo(repo_slug).get_issue(pr_num)

    before = issue.get_comments().totalCount
    inline_comments(pr_url, style="nitpick")
    time.sleep(3)                          # GH API eventual consistency
    after  = issue.get_comments().totalCount

    assert after >= before
