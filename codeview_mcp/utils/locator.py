"""
Semantic locator: map detected smells to code hunks using embeddings.
"""
import re
from codeview_mcp.config import load
from codeview_mcp.utils.vector import nearest, index_files


def locate(smells: list[str], files: list[dict]) -> list[tuple[str, int, str]]:
    """
    For each smell string, embed code hunks and find the most relevant section.

    Returns a list of (file_path, line_number, smell_text), capped by max_comments.
    """
    # Ensure all hunks are indexed once (no-op if already up-to-date)
    index_files(files)

    results: list[tuple[str, int, str]] = []
    for smell in smells:
        # Retrieve the single best-matching hunk for this smell
        hunk_docs = nearest(smell, k=1)
        if not hunk_docs:
            continue
        d = hunk_docs[0]
        # Choose target_start or source_start for line number
        line_no = d.get("target_start") or d.get("source_start") or 1
        results.append((d.get("path", ""), line_no, smell))

    # Cap results according to configuration
    return results[: load()["max_comments"]]
