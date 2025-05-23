"""
Very naive mapping: for each smell string, find first hunk containing
a keyword from smell → return (file_path, line_no).
"""
import re
from codeview_mcp.config import load

KEYWORDS = {
    "dup": r"duplicate|dup",
    "version": r"bump|version",
    "unpin": r"unpin|sha",
    "security": r"todo(dom|sec)|bcrypt|eval",
}

def locate(smells: list[str], files: list[dict]) -> list[tuple[str, int, str]]:
    results = []
    for smell in smells:
        kw_regex = next((v for k, v in KEYWORDS.items() if k in smell.lower()), None)
        if not kw_regex:
            continue
        pat = re.compile(kw_regex, re.I)
        for f in files:
            if f["is_binary"]:
                continue
            for h in f["hunks"]:
                if pat.search(h["section_header"] or ""):
                    results.append((f["path"], h["target_start"] or h["source_start"], smell))
                    break
            if results and results[-1][0] == f["path"]:
                break
    return results[: load()["max_comments"]]
