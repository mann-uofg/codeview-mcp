from mcp.server.fastmcp import FastMCP
from github import Github
import os
import re

# --- GitHub client (reads token from env) -------------------------
GH_TOKEN = os.getenv("GH_TOKEN")
if not GH_TOKEN:
    raise RuntimeError("GH_TOKEN not found in env; export it first.")

gh = Github(GH_TOKEN)

# --- MCP server instance ------------------------------------------
mcp = FastMCP("reviewgenie")   # auto-registers tools via decorator


def _parse_pr_url(url: str) -> tuple[str, int]:
    """
    Extract 'owner/repo' and PR number from a GitHub PR URL.
    """
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError("Not a valid GitHub PR URL")
    return m.group(1), int(m.group(2))


@mcp.tool()
def ping(pr_url: str) -> dict:
    """
    Sanity-check tool: returns title & author of the pull request.
    """
    repo_slug, pr_num = _parse_pr_url(pr_url)
    pr = gh.get_repo(repo_slug).get_pull(pr_num)
    return {
        "title": pr.title,
        "author": pr.user.login,
        "state": pr.state,
    }


if __name__ == "__main__":
    # Run in stdio transport; MCP host (e.g. Claude Desktop) will spawn it.
    mcp.run()
