from textwrap import indent
def build_diff_prompt(files: list[dict]) -> str:
    """Return hunks with ±30 LOC context, capped at 2 000 tokens."""
    snippets = []
    for f in files[:5]:                         # safety cap
        if f["is_binary"]:
            continue
        for h in f["hunks"][:3]:
            header = h["section_header"] or "@@"
            snippets.append(f"### {f['path']} {header}\n{indent('...', '    ')}")
    return "\n".join(snippets)[:16_000]         # char cap ~2 k tokens
