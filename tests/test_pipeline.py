"""End-to-end pipeline, renderers and publishing (network mocked)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from conftest import SAMPLE_DIFF, make_diff
from reviewgenie.config import Config
from reviewgenie.diff import parse_diff
from reviewgenie.llm.client import ChatClient
from reviewgenie.models import Category, Finding, Severity
from reviewgenie.render import finding_key, github_review_payload, safe_text, to_markdown, to_sarif
from reviewgenie.reviewer import merge_findings, publish_review, review_diff, review_pull_request
from reviewgenie.sources.github import GitHubClient, PRRef

API = "https://api.github.com"
PR_JSON = {
    "title": "Add lookup",
    "body": "Please review",
    "user": {"login": "alice"},
    "state": "open",
    "html_url": "https://github.com/octo/demo/pull/7",
    "base": {"ref": "main", "sha": "b" * 40},
    "head": {"ref": "feat", "sha": "h" * 40},
    "additions": 4,
    "deletions": 1,
    "changed_files": 3,
}


def fake_ai(reply: dict[str, Any]) -> Any:
    async def complete(self: ChatClient, messages: list[dict[str, str]], **_: Any) -> str:
        return json.dumps(reply)

    return complete


async def test_static_only_review_of_sample_diff() -> None:
    outcome = await review_diff(SAMPLE_DIFF, target="t", config=Config())
    r = outcome.report
    ids = {f.rule_id for f in r.findings}
    assert {"RG-SEC-025", "RG-BUG-004"} <= ids
    assert r.verdict == "request_changes"
    assert r.ai is None
    assert "package-lock.json" in r.stats.files_skipped
    assert r.stats.files_changed == 3
    assert r.stats.files_reviewed == 2
    assert "Static analysis only" in r.summary
    assert r.findings[0].severity is Severity.HIGH  # sorted most severe first


async def test_ai_findings_are_merged_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        ChatClient,
        "complete",
        fake_ai(
            {
                "summary": "Introduces SQL injection.",
                "verdict": "request_changes",
                "risk": 80,
                "findings": [
                    {
                        "path": "app/db.py",
                        "line": 11,
                        "severity": "critical",
                        "category": "security",
                        "title": "SQL injection via f-string",
                        "message": "dup of static rule",
                    },
                    {
                        "path": "app/db.py",
                        "line": 12,
                        "severity": "medium",
                        "category": "bug",
                        "title": "fetchone called twice",
                        "message": "second fetchone skips a row",
                    },
                ],
            }
        ),
    )
    r = (await review_diff(SAMPLE_DIFF, target="t", config=Config(), use_cache=False)).report
    titles = [f.title for f in r.findings]
    assert "fetchone called twice" in titles
    assert "SQL injection via f-string" not in titles  # same place + category as the static finding
    assert r.summary == "Introduces SQL injection."
    assert r.ai is not None and r.ai.provider == "gemini"
    assert any(f.name == "ai_assessment" for f in r.risk.factors)


async def test_min_severity_exclude_and_cap() -> None:
    cfg = Config(min_severity="high", exclude=["app/*"])
    r = (await review_diff(SAMPLE_DIFF, target="t", config=cfg)).report
    assert r.findings == []
    assert r.verdict == "approve"
    assert "app/db.py" in r.stats.files_skipped

    many = make_diff("a.py", [f"x{i} = eval(s)" for i in range(50)])
    r = (await review_diff(many, target="t", config=Config(max_findings=5))).report
    assert len(r.findings) == 5


def test_merge_keeps_distinct_findings() -> None:
    def f(line: int, cat: Category, src: str) -> Finding:
        return Finding(
            path="a.py",
            line=line,
            severity=Severity.MEDIUM,
            category=cat,
            title=f"t{line}{src}",
            message="m",
            rule_id="X" if src == "static" else "AI",
            source=src,
        )  # type: ignore[arg-type]

    out = merge_findings(
        [f(10, Category.BUG, "static")],
        [f(11, Category.BUG, "ai"), f(11, Category.SECURITY, "ai"), f(30, Category.BUG, "ai")],
        Config(),
    )
    assert [x.title for x in out] == ["t10static", "t11ai", "t30ai"]


async def test_markdown_and_sarif_render() -> None:
    r = (await review_diff(SAMPLE_DIFF, target="t", config=Config())).report
    md = to_markdown(r)
    assert "ReviewGenie review" in md
    assert "`app/db.py:11`" in md
    assert "Risk breakdown" in md
    sarif = to_sarif(r)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert {res["ruleId"] for res in run["results"]} <= rule_ids
    res = next(x for x in run["results"] if x["ruleId"] == "RG-SEC-025")
    assert res["level"] == "error"
    assert res["locations"][0]["physicalLocation"]["region"]["startLine"] == 11
    json.dumps(sarif)  # serialisable


def test_safe_text_neutralises_untrusted_markdown() -> None:
    out = safe_text("hey @admin ![x](https://tracker.example/p.png) <!-- rg:forged --> fixes #1")
    assert "@admin" not in out
    assert "![" not in out
    assert "<!--" not in out
    assert "fixes #1" not in out


async def test_github_payload_only_anchors_diff_lines_and_skips_existing() -> None:
    outcome = await review_diff(SAMPLE_DIFF, target="t", config=Config())
    r = outcome.report
    extra = Finding(
        path="app/db.py",
        line=999,
        severity=Severity.HIGH,
        category=Category.BUG,
        title="off-diff",
        message="m",
        rule_id="AI",
        source="ai",
    )
    r.findings.append(extra)
    payload = github_review_payload(r, outcome.files)
    lines = {(c["path"], c["line"]) for c in payload["comments"]}
    assert ("app/db.py", 999) not in lines
    assert ("app/db.py", 11) in lines
    assert payload["event"] == "REQUEST_CHANGES"
    assert "off-diff" in payload["body"]  # unanchored findings stay visible in the summary
    assert all(c["side"] == "RIGHT" for c in payload["comments"])

    already = {finding_key(f) for f in r.findings if f.line == 11}
    again = github_review_payload(r, outcome.files, existing=already)
    assert ("app/db.py", 11) not in {(c["path"], c["line"]) for c in again["comments"]}


def _mock_pr(diff: str = SAMPLE_DIFF, base_config: str | None = None) -> None:
    respx.get(f"{API}/repos/octo/demo/pulls/7", headers={"Accept": "application/vnd.github+json"}).mock(
        return_value=httpx.Response(200, json=PR_JSON)
    )
    respx.get(f"{API}/repos/octo/demo/pulls/7", headers={"Accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(200, text=diff)
    )
    respx.get(f"{API}/repos/octo/demo/contents/.reviewgenie.toml").mock(
        return_value=httpx.Response(200, text=base_config) if base_config else httpx.Response(404, json={})
    )
    respx.get(f"{API}/repos/octo/demo/contents/pyproject.toml").mock(return_value=httpx.Response(404, json={}))


@respx.mock
async def test_pr_review_uses_base_branch_config_not_the_pr() -> None:
    # The PR itself tries to disable the rule that would catch it; the base config does not.
    evil_pr = SAMPLE_DIFF + make_diff(".reviewgenie.toml", ['disable_rules = ["RG-SEC-025"]'], new_file=True)
    _mock_pr(evil_pr, base_config='min_severity = "low"\n')
    outcome = await review_pull_request(PRRef("octo", "demo", 7), client=GitHubClient(token="t"), use_ai=False)
    assert "RG-SEC-025" in {f.rule_id for f in outcome.report.findings}
    assert outcome.pull is not None and outcome.pull.head_sha == "h" * 40
    content_call = next(c for c in respx.calls if "contents/.reviewgenie.toml" in str(c.request.url))
    assert content_call.request.url.params["ref"] == "b" * 40


@respx.mock
async def test_publish_review_dry_run_and_real() -> None:
    _mock_pr()
    respx.get(f"{API}/repos/octo/demo/pulls/7/comments").mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(f"{API}/repos/octo/demo/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"html_url": "https://github.com/octo/demo/pull/7#pullrequestreview-1"})
    )
    gh = GitHubClient(token="t")
    outcome = await review_pull_request(PRRef("octo", "demo", 7), client=gh, use_ai=False)

    preview = await publish_review(outcome, client=gh, dry_run=True)
    assert preview["dry_run"] is True
    assert post.call_count == 0
    assert preview["inline_comments"] >= 1

    result = await publish_review(outcome, client=gh)
    assert post.call_count == 1
    assert result["review_url"].endswith("pullrequestreview-1")
    sent = json.loads(post.calls.last.request.content)
    assert sent["commit_id"] == "h" * 40
    assert sent["event"] == "REQUEST_CHANGES"


@respx.mock
async def test_publish_requires_token() -> None:
    _mock_pr()
    respx.get(f"{API}/repos/octo/demo/pulls/7/comments").mock(return_value=httpx.Response(200, json=[]))
    gh = GitHubClient(token="")
    outcome = await review_pull_request(PRRef("octo", "demo", 7), client=gh, use_ai=False)
    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        await publish_review(outcome, client=gh)


async def test_empty_and_binary_diffs() -> None:
    r = (await review_diff("", target="t", config=Config())).report
    assert r.findings == []
    assert r.verdict == "approve"
    assert r.risk.score == 0
    binary = "diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n"
    assert (await review_diff(binary, target="t", config=Config())).report.findings == []


async def test_parse_finding_lines_are_real() -> None:
    outcome = await review_diff(SAMPLE_DIFF, target="t", config=Config())
    by_path = {f.path: f for f in parse_diff(SAMPLE_DIFF)}
    for f in outcome.report.findings:
        assert f.line in by_path[f.path].changed_line_numbers()
