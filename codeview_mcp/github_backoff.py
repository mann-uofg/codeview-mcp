import backoff, github
from codeview_mcp.secret import require
from github import Github

def _is_retryable(exc):
    # 403 secondary-rate-limit or any 5xx
    return isinstance(exc, github.GithubException.GithubException) and \
           exc.status in (403, 500, 502, 503)

@backoff.on_exception(backoff.expo,
                      github.GithubException.GithubException,
                      max_time=60,
                      giveup=lambda e: not _is_retryable(e))
def gh_call(func, *args, **kwargs):
    """Call a PyGitHub function with exponential back-off."""
    return func(*args, **kwargs)

def gh_client() -> Github:
    return Github(require("GH_TOKEN"))
