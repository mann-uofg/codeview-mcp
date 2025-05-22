import re

def parse_pr_url(url: str) -> tuple[str, int]:
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError("Not a valid GitHub PR URL")
    return m.group(1), int(m.group(2))
