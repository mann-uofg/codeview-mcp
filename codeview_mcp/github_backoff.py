import backoff
from github import Github
from github.GithubException import GithubException   # ← correct import
from codeview_mcp.secret import require

# retryable statuses
_RETRY = {403, 500, 502, 503}

@backoff.on_exception(backoff.expo,
                      GithubException,
                      max_time=60,
                      giveup=lambda e: e.status not in _RETRY)
def gh_call(func, *args, **kwargs):
    """Call PyGitHub func with exponential back-off on 403 / 5xx."""
    return func(*args, **kwargs)

def gh_client() -> Github:
    return Github(require("GH_TOKEN"))
