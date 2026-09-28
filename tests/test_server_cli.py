"""MCP server (in-process client) and CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from mcp import Client
from typer.testing import CliRunner

from codeview import __version__
from codeview.cli import app
from codeview.server import mcp
from conftest import SAMPLE_DIFF

runner = CliRunner()


async def test_mcp_lists_tools_resources_and_prompts() -> None:
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {
            "review_pull_request",
            "review_local_changes",
            "review_diff_text",
            "get_pull_request_diff",
            "post_review",
            "list_rules",
            "provider_status",
        } <= set(tools)
        assert tools["review_pull_request"].annotations.read_only_hint is True
        assert tools["post_review"].annotations.read_only_hint is False
        assert tools["post_review"].input_schema["properties"]["dry_run"]["default"] is True
        assert tools["review_diff_text"].output_schema is not None

        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert {"codeview://rules", "codeview://providers", "codeview://config/example"} <= uris

        prompts = {p.name for p in (await client.list_prompts()).prompts}
        assert {"deep_review", "security_audit", "suggest_tests", "review_my_changes"} <= prompts


async def test_mcp_review_diff_tool_returns_structured_report() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("review_diff_text", {"diff": SAMPLE_DIFF, "use_ai": False})
        assert not result.is_error
        report = result.structured_content
        assert report is not None
        assert report["verdict"] == "request_changes"
        assert any(f["rule_id"] == "CV-SEC-025" for f in report["findings"])
        assert 0 <= report["risk"]["score"] <= 100


async def test_mcp_errors_are_clean_tool_errors() -> None:
    async with Client(mcp) as client:
        bad = await client.call_tool("review_pull_request", {"pr": "https://evil.example/o/r/pull/1"})
        assert bad.is_error
        assert "not a pull request URL" in bad.content[0].text
        not_diff = await client.call_tool("review_diff_text", {"diff": "hello"})
        assert not_diff.is_error
        assert "not a unified diff" in not_diff.content[0].text


async def test_mcp_rules_providers_and_prompt() -> None:
    async with Client(mcp) as client:
        rules = await client.call_tool("list_rules", {"category": "security"})
        payload = rules.structured_content
        assert payload is not None
        items = payload["result"] if isinstance(payload, dict) and "result" in payload else payload
        assert all(r["category"] == "security" for r in items)
        status = (await client.call_tool("provider_status", {})).structured_content
        assert status is not None
        assert status["fallback_order"] == []
        assert not any(p["configured"] for p in status["providers"])
        prompt = await client.get_prompt("deep_review", {"pr": "octo/demo#7"})
        assert "octo/demo#7" in prompt.messages[0].content.text
        res = await client.read_resource("codeview://config/example")
        assert "provider" in res.contents[0].text


@respx.mock
async def test_mcp_get_pull_request_diff() -> None:
    api = "https://api.github.com/repos/octo/demo/pulls/7"
    respx.get(api, headers={"Accept": "application/vnd.github+json"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "T",
                "body": "B",
                "user": {"login": "u"},
                "state": "open",
                "html_url": "https://github.com/octo/demo/pull/7",
                "base": {"ref": "main", "sha": "b" * 40},
                "head": {"ref": "f", "sha": "h" * 40},
            },
        )
    )
    respx.get(api, headers={"Accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(200, text=SAMPLE_DIFF)
    )
    async with Client(mcp) as client:
        out = (await client.call_tool("get_pull_request_diff", {"pr": "octo/demo#7"})).structured_content
    assert out is not None
    assert out["pull_request"]["title"] == "T"
    assert "   11 + " in out["diff"]
    assert "package-lock.json" in out["files_omitted"]


def test_cli_version_and_help() -> None:
    assert __version__ in runner.invoke(app, ["--version"]).output
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "review" in result.output


def test_cli_review_diff_file_formats_and_exit_codes(tmp_path: Path) -> None:
    diff = tmp_path / "change.diff"
    diff.write_text(SAMPLE_DIFF, encoding="utf-8")

    res = runner.invoke(app, ["review", "--diff", str(diff), "--format", "json", "--no-ai"])
    assert res.exit_code == 1  # a high finding with the default fail_on=high
    data = json.loads(res.stdout)
    assert data["verdict"] == "request_changes"

    res = runner.invoke(app, ["review", "--diff", str(diff), "--no-ai", "--fail-on", "never", "-f", "sarif"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["version"] == "2.1.0"

    out = tmp_path / "out" / "report.md"
    res = runner.invoke(
        app, ["review", "--diff", str(diff), "--no-ai", "--fail-on", "critical", "-f", "markdown", "-o", str(out)]
    )
    assert res.exit_code == 0
    assert "codeview review" in out.read_text(encoding="utf-8")

    res = runner.invoke(app, ["review", "--diff", str(diff), "--no-ai", "--fail-on", "never", "--max-risk", "1"])
    assert res.exit_code == 1

    res = runner.invoke(app, ["review", "--diff", "-", "--no-ai", "--fail-on", "never"], input=SAMPLE_DIFF)
    assert res.exit_code == 0
    assert "CV-SEC-025" in res.stdout


def test_cli_writes_github_step_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    diff = tmp_path / "c.diff"
    diff.write_text(SAMPLE_DIFF, encoding="utf-8")
    runner.invoke(app, ["review", "--diff", str(diff), "--no-ai", "--fail-on", "never"])
    assert "codeview review" in summary.read_text(encoding="utf-8")


def test_cli_errors_are_friendly(tmp_path: Path) -> None:
    res = runner.invoke(app, ["review", "https://evil.example/o/r/pull/1"])
    assert res.exit_code == 2
    assert "not a pull request URL" in res.output
    res = runner.invoke(app, ["review", "--diff", str(tmp_path / "missing.diff")])
    assert res.exit_code == 2
    bad = tmp_path / "bad.toml"
    bad.write_text("nope = 1\n", encoding="utf-8")
    res = runner.invoke(app, ["review", "--diff", "-", "--config", str(bad)], input=SAMPLE_DIFF)
    assert res.exit_code == 2
    res = runner.invoke(app, ["review", "--diff", "-", "--provider", "chatgpt"], input=SAMPLE_DIFF)
    assert res.exit_code == 2
    assert "unknown provider" in res.output


async def test_mcp_provider_status_never_reveals_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-very-secret")
    async with Client(mcp) as client:
        result = await client.call_tool("provider_status", {})
    assert "AIza-very-secret" not in json.dumps(result.structured_content)
    assert result.structured_content is not None
    assert result.structured_content["fallback_order"] == ["gemini"]


def test_cli_rules_providers_init_mcp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "CV-SEC-001" in runner.invoke(app, ["rules"]).stdout
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq-key")
    out = runner.invoke(app, ["providers"]).stdout
    assert "groq" in out.lower()
    assert "secret-groq-key" not in out
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert (tmp_path / ".codeview.toml").exists()
    assert runner.invoke(app, ["init"]).exit_code == 2
    snippet = json.loads(runner.invoke(app, ["mcp-config"]).stdout)
    assert snippet["mcpServers"]["codeview"]["args"][-2:] == ["codeview", "serve"]
    assert "github.com/mann-uofg/codeview-mcp" in snippet["mcpServers"]["codeview"]["args"][1]
    assert runner.invoke(app, ["clear-cache"]).exit_code == 0


def test_cli_extra_outputs(tmp_path: Path) -> None:
    diff = tmp_path / "c.diff"
    diff.write_text(SAMPLE_DIFF, encoding="utf-8")
    j, s = tmp_path / "r.json", tmp_path / "r.sarif"
    res = runner.invoke(
        app,
        [
            "review",
            "--diff",
            str(diff),
            "--no-ai",
            "--fail-on",
            "never",
            "-f",
            "markdown",
            "--json-output",
            str(j),
            "--sarif-output",
            str(s),
        ],
    )
    assert res.exit_code == 0
    assert json.loads(j.read_text(encoding="utf-8"))["risk"]["score"] >= 0
    assert json.loads(s.read_text(encoding="utf-8"))["runs"][0]["results"]


@respx.mock
def test_cli_post_on_read_only_token_warns_but_keeps_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "read-only")
    api = "https://api.github.com/repos/octo/demo"
    respx.get(f"{api}/pulls/7", headers={"Accept": "application/vnd.github+json"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "T",
                "body": "",
                "user": {"login": "u"},
                "state": "open",
                "html_url": "https://github.com/octo/demo/pull/7",
                "base": {"ref": "main", "sha": "b" * 40},
                "head": {"ref": "f", "sha": "h" * 40},
            },
        )
    )
    respx.get(f"{api}/pulls/7", headers={"Accept": "application/vnd.github.diff"}).mock(
        return_value=httpx.Response(200, text=SAMPLE_DIFF)
    )
    respx.get(url__regex=rf"{api}/contents/.*").mock(return_value=httpx.Response(404, json={}))
    respx.get(f"{api}/pulls/7/comments").mock(return_value=httpx.Response(200, json=[]))
    respx.post(f"{api}/pulls/7/reviews").mock(
        return_value=httpx.Response(403, json={"message": "Resource not accessible by integration"})
    )
    res = runner.invoke(app, ["review", "octo/demo#7", "--post", "--no-ai", "--fail-on", "never", "-f", "json"])
    assert res.exit_code == 0, res.output
    assert "could not post the review" in res.output
    assert json.loads(res.stdout)["verdict"] == "request_changes"
