"""Render review reports as Markdown, SARIF 2.1.0, or a GitHub pull-request review payload."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from reviewgenie import __version__
from reviewgenie.diff import DiffFile
from reviewgenie.models import Finding, ReviewReport, Severity
from reviewgenie.sources.github import REVIEW_MARKER, neutralize_mentions

HOMEPAGE = "https://github.com/mann-uofg/codeview-mcp"
ICONS = {
    Severity.CRITICAL: "🛑",
    Severity.HIGH: "🔴",
    Severity.MEDIUM: "🟠",
    Severity.LOW: "🟡",
    Severity.INFO: "🔵",
}
RISK_ICONS = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
VERDICT_TEXT = {
    "approve": "✅ Looks good",
    "comment": "💬 Worth a look",
    "request_changes": "⛔ Changes requested",
}


def safe_text(text: str | None) -> str:
    """Make untrusted (model- or diff-derived) text safe to post: no pings, no remote images, no raw HTML comments."""
    if not text:
        return ""
    text = neutralize_mentions(text)
    text = text.replace("![", "!\u200b[")  # no tracking pixels / remote images
    return re.sub(r"<!--|-->", "", text)  # cannot forge our hidden markers


def _cell(text: str) -> str:
    return safe_text(text).replace("|", "\\|").replace("\n", " ")


def _suggestion_block(suggestion: str) -> str:
    s = safe_text(suggestion).strip()
    if "```" in s:
        return s
    if "\n" in s or re.search(r"[;{}()=]\s*$", s):
        return f"```\n{s}\n```"
    return s


def finding_key(f: Finding) -> str:
    return hashlib.sha256(f.fingerprint.encode()).hexdigest()[:16]


def to_markdown(report: ReviewReport, *, heading: bool = True) -> str:
    r = report
    out: list[str] = []
    if heading:
        out.append("## 🧞 ReviewGenie review\n")
    out.append(
        f"**{VERDICT_TEXT[r.verdict]}** · Risk {RISK_ICONS[r.risk.level]} **{r.risk.score}/100** "
        f"({r.risk.level}) · {r.stats.files_reviewed} files · +{r.stats.additions}/-{r.stats.deletions}\n"
    )
    out.append(safe_text(r.summary) + "\n")

    if r.findings:
        counts = r.counts()
        out.append(" · ".join(f"{ICONS[Severity(s)]} {n} {s}" for s, n in reversed(counts.items()) if n) + "\n")
        out.append("| | Finding | Location | Source |\n|---|---|---|---|")
        for f in r.findings:
            loc = f"`{f.path}:{f.line}`" if f.line else f"`{f.path}`"
            src = f.rule_id if f.source == "static" else "AI"
            out.append(f"| {ICONS[f.severity]} | **{_cell(f.title)}** — {_cell(f.message)} | {loc} | {src} |")
        out.append("")
    else:
        out.append("No issues found. 🎉\n")

    if r.risk.factors:
        out.append("<details><summary>Risk breakdown</summary>\n")
        for factor in r.risk.factors:
            sign = "+" if factor.points >= 0 else ""
            out.append(f"- **{factor.name}** ({sign}{factor.points}): {_cell(factor.detail)}")
        out.append("\n</details>\n")
    if r.stats.files_skipped:
        skipped = ", ".join(f"`{p}`" for p in r.stats.files_skipped[:15])
        more = f" and {len(r.stats.files_skipped) - 15} more" if len(r.stats.files_skipped) > 15 else ""
        out.append(f"<sub>Skipped (generated/lockfiles/excluded): {skipped}{more}</sub>\n")
    engine = f"{r.ai.provider} · {r.ai.model}" if r.ai and not r.ai.error else "static rules only"
    if r.ai and r.ai.error:
        engine += f" (AI unavailable: {_cell(r.ai.error[:160])})"
    out.append(f"<sub>ReviewGenie {__version__} · {engine} · {r.duration_ms} ms · [docs]({HOMEPAGE})</sub>")
    return "\n".join(out).strip() + "\n"


def comment_body(f: Finding) -> str:
    parts = [f"{ICONS[f.severity]} **{safe_text(f.title)}** · _{f.severity.value} {f.category.value}_"]
    parts.append(safe_text(f.message))
    if f.suggestion:
        parts.append("**Suggestion:** " + _suggestion_block(f.suggestion))
    ref = f.rule_id if f.source == "static" else "AI review"
    if f.cwe:
        ref += f" · {f.cwe}"
    parts.append(f"<sub>{ref}</sub>\n{REVIEW_MARKER}<!-- rg:{finding_key(f)} -->")
    return "\n\n".join(parts)


def github_review_payload(
    report: ReviewReport, files: list[DiffFile], *, existing: set[str] | None = None, max_comments: int = 30
) -> dict[str, Any]:
    """Build ``{"body", "event", "comments"}`` for ``POST /pulls/{n}/reviews``.

    Findings that can't be anchored to a line in the diff are kept in the summary body.
    ``existing`` holds keys of comments already posted, which are skipped on re-runs.
    """
    existing = existing or set()
    commentable = {f.path: f.new_line_numbers() for f in files}
    comments: list[dict[str, Any]] = []
    for f in report.findings:
        if f.line is None or f.line not in commentable.get(f.path, set()):
            continue
        if finding_key(f) in existing or len(comments) >= max_comments:
            continue
        comments.append({"path": f.path, "line": f.line, "side": "RIGHT", "body": comment_body(f)})
    event = "REQUEST_CHANGES" if report.verdict == "request_changes" else "COMMENT"
    body = to_markdown(report) + f"\n{REVIEW_MARKER}"
    return {"body": body, "event": event, "comments": comments}


_SARIF_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}
_SECURITY_SEVERITY = {
    Severity.CRITICAL: "9.5",
    Severity.HIGH: "8.0",
    Severity.MEDIUM: "5.5",
    Severity.LOW: "3.0",
    Severity.INFO: "1.0",
}


def to_sarif(report: ReviewReport) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for f in report.findings:
        rule_id = f.rule_id if f.source == "static" else f"AI/{f.category.value}"
        if rule_id not in rules:
            tags = [f.category.value] + (["security", f.cwe] if f.cwe else [])
            rules[rule_id] = {
                "id": rule_id,
                "name": re.sub(r"[^A-Za-z0-9]+", "", f.title.title())[:60] or rule_id,
                "shortDescription": {"text": f.title if f.source == "static" else f"AI review: {f.category.value}"},
                "helpUri": HOMEPAGE,
                "properties": {"tags": tags, "security-severity": _SECURITY_SEVERITY[f.severity]},
            }
        text = f.message + (f"\n\nSuggestion: {f.suggestion}" if f.suggestion else "")
        location: dict[str, Any] = {"physicalLocation": {"artifactLocation": {"uri": f.path}}}
        if f.line:
            location["physicalLocation"]["region"] = {"startLine": f.line}
        results.append(
            {
                "ruleId": rule_id,
                "level": _SARIF_LEVEL[f.severity],
                "message": {"text": f"{f.title}: {text}" if f.source == "ai" else text},
                "locations": [location],
                "partialFingerprints": {"reviewgenie/v1": finding_key(f)},
                "properties": {"severity": f.severity.value, "source": f.source},
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ReviewGenie",
                        "version": __version__,
                        "informationUri": HOMEPAGE,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
                "properties": {"riskScore": report.risk.score, "verdict": report.verdict},
            }
        ],
    }
