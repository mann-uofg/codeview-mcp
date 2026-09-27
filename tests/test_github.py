from __future__ import annotations

import json

import httpx
import pytest
import respx

from conftest import SAMPLE_DIFF
from reviewgenie.sources.github import (
    GitHubClient,
    GitHubError,
    PRRef,
    neutralize_mentions,
    parse_pr_ref,
    resolve_token,
)

API = "https://api.github.com"
REF = PRRef("octo", "demo", 7)
PR_JSON = {
    "title": "Add lookup",
    "body": "Please review",
    "user": {"login": "alice"},
    "state": "open",
    "draft": False,
    "merged": False,
    "html_url": "https://github.com/octo/demo/pull/7",
    "base": {"ref": "main", "sha": "b" * 40},
    "head": {"ref": "feat", "sha": "h" * 40},
    "additions": 4,
    "deletions": 1,
    "changed_files": 3,
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/psf/requests/pull/6883", ("psf", "requests", 6883)),
        ("https://github.com/psf/requests/pull/6883/files", ("psf", "requests", 6883)),
        ("https://github.com/psf/requests/pull/6883?diff=split#r1", ("psf", "requests", 6883)),
        ("github.com/a-b/c.d_e/pull/1", ("a-b", "c.d_e", 1)),
        ("https://www.github.com/o/r/pulls/2", ("o", "r", 2)),
        ("octo/demo#7", ("octo", "demo", 7)),
    ],
)
def test_parse_pr_ref_accepts(value: str, expected: tuple[str, str, int]) -> None:
    ref = parse_pr_ref(value)
    assert (ref.owner, ref.repo, ref.number) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/o/r/pull/1",  # not https
        "https://evil.com/o/r/pull/1",
        "https://github.com.evil.com/o/r/pull/1",
        "https://github.com@evil.com/o/r/pull/1",
        "https://user:pw@github.com/o/r/pull/1",
        "https://github.com:8443/o/r/pull/1",
        "https://github.com/o/r/issues/1",
        "https://github.com/o/../pull/1",
        "https://github.com/-bad/r/pull/1",
        "https://github.com/o/r/pull/0",
        "https://github.com/o/r/pull/abc",
        "o/r#-1",
        "",
        "file:///etc/passwd",
    ],
)
def test_parse_pr_ref_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        parse_pr_ref(value)


def test_enterprise_host_from_actions_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://git.corp.example")
    assert parse_pr_ref("https://git.corp.example/o/r/pull/3").number == 3
    with pytest.raises(ValueError):
        parse_pr_ref("https://github.com/o/r/pull/3")
    monkeypatch.setenv("GITHUB_API_URL", "http://git.corp.example/api/v3")
    with pytest.raises(GitHubError, match="https"):
        GitHubClient()


def test_token_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_token() is None
    monkeypatch.setenv("GH_TOKEN", "t2")
    assert resolve_token() == "t2"
    monkeypatch.setenv("GITHUB_TOKEN", "t1")
    assert resolve_token() == "t1"


def test_neutralize_mentions() -> None:
    out = neutralize_mentions("ping @octocat and @org/team; mail a@b.com; `@code`; closes #5")
    assert "@octocat" not in out
    assert "@org/team" not in out
    assert "a@b.com" in out
    assert "`@code`" in out
    assert "closes #5" not in out


@respx.mock
async def test_get_pull_and_diff() -> None:
    respx.get(f"{API}/repos/octo/demo/pulls/7", headers={"Accept": "application/vnd.github+json"}).mock(
        return_value=httpx.Response(200, json=PR_JSON)
    )
    diff_route = respx.get(f"{API}/repos/octo/demo/pulls/7", headers={"Accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(200, text=SAMPLE_DIFF)
    )
    async with GitHubClient(token="tok") as gh:
        pull = await gh.get_pull(REF)
        diff = await gh.get_diff(REF)
    assert pull.title == "Add lookup"
    assert pull.head_sha == "h" * 40
    assert diff == SAMPLE_DIFF
    assert diff_route.calls.last.request.headers["authorization"] == "Bearer tok"


@respx.mock
async def test_too_large_diff_falls_back_to_files_api() -> None:
    respx.get(f"{API}/repos/octo/demo/pulls/7").mock(
        return_value=httpx.Response(406, json={"message": "Sorry, the diff exceeded the maximum number of lines"})
    )
    respx.get(f"{API}/repos/octo/demo/pulls/7/files").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"filename": "a.py", "status": "modified", "patch": "@@ -1 +1 @@\n-a\n+b"},
                {"filename": "new.py", "status": "added", "patch": "@@ -0,0 +1 @@\n+x = 1"},
                {"filename": "img.png", "status": "added"},
            ],
        )
    )
    async with GitHubClient(token="tok") as gh:
        diff = await gh.get_diff(REF)
    assert "diff --git a/a.py b/a.py" in diff
    assert "+++ b/new.py" in diff
    assert "Binary files differ" in diff


@respx.mock
async def test_errors_are_descriptive_and_never_leak_the_token() -> None:
    respx.get(f"{API}/repos/octo/demo/pulls/7").mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    async with GitHubClient(token="") as gh:
        with pytest.raises(GitHubError, match="if the repository is private, set GITHUB_TOKEN") as exc:
            await gh.get_pull(REF)
    assert exc.value.status == 404
    respx.get(f"{API}/repos/octo/demo/pulls/8").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    async with GitHubClient(token="ghp_secret_value") as gh:
        with pytest.raises(GitHubError) as exc2:
            await gh.get_pull(PRRef("octo", "demo", 8))
    assert "ghp_secret_value" not in str(exc2.value)


@respx.mock
async def test_get_file_404_is_none() -> None:
    respx.get(f"{API}/repos/octo/demo/contents/.reviewgenie.toml").mock(return_value=httpx.Response(404, json={}))
    async with GitHubClient(token="t") as gh:
        assert await gh.get_file(REF, ".reviewgenie.toml", "b" * 40) is None


@respx.mock
async def test_create_review_recovers_from_422s() -> None:
    route = respx.post(f"{API}/repos/octo/demo/pulls/7/reviews").mock(
        side_effect=[
            httpx.Response(422, json={"message": "Can not request changes on your own pull request"}),
            httpx.Response(422, json={"message": "Line could not be resolved"}),
            httpx.Response(200, json={"html_url": "https://github.com/octo/demo/pull/7#review-1"}),
        ]
    )
    async with GitHubClient(token="t") as gh:
        out = await gh.create_review(
            REF,
            commit_id="h" * 40,
            body="b",
            event="REQUEST_CHANGES",
            comments=[{"path": "a.py", "line": 1, "side": "RIGHT", "body": "x"}],
        )
    assert out["html_url"].endswith("review-1")
    payloads = [json.loads(c.request.content) for c in route.calls]
    assert payloads[0]["event"] == "REQUEST_CHANGES"
    assert payloads[1]["event"] == "COMMENT"
    assert "comments" in payloads[1]
    assert "comments" not in payloads[2]


@respx.mock
async def test_existing_comment_keys() -> None:
    respx.get(f"{API}/repos/octo/demo/pulls/7/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"body": "hi <!-- reviewgenie --><!-- rg:abc123 -->"},
                {"body": "human comment <!-- rg:zzz -->"},
            ],
        )
    )
    async with GitHubClient(token="t") as gh:
        assert await gh.existing_comment_keys(REF) == {"abc123"}


def test_neutralize_mentions_preserves_code() -> None:
    text = "Ping @alice. Suggested:\n```python\n@app.route('/x')\ndef x(): ...  # closes #3\n```\nand `@decorator` fixes #9"
    out = neutralize_mentions(text)
    assert "@app.route('/x')" in out
    assert "# closes #3" in out
    assert "`@decorator`" in out
    assert "@alice" not in out
    assert "fixes #9" not in out
    assert neutralize_mentions("```\nunterminated @fence") == "```\nunterminated @fence"
