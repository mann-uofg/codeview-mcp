"""Command-line interface: ``codeview review``, ``serve``, ``providers``, ``rules``, ``init``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from codeview import __version__
from codeview.cache import ResponseCache
from codeview.config import CONFIG_FILENAME, EXAMPLE_CONFIG, Config, ConfigError, load_config
from codeview.llm.client import LLMError
from codeview.models import ReviewReport, plural
from codeview.render import LABELS, VERDICT_TEXT, to_markdown, to_sarif
from codeview.sources.github import GitHubError, parse_pr_ref

GIT_SOURCE = "git+https://github.com/mann-uofg/codeview-mcp"

app = typer.Typer(
    name="codeview",
    help="AI code review for pull requests and local changes, on free-tier models. Also an MCP server.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)
err = Console(stderr=True)


class OutputFormat(StrEnum):
    text = "text"
    markdown = "markdown"
    json = "json"
    sarif = "sarif"


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"codeview {__version__}")
        raise typer.Exit


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show debug logging on stderr.")] = False,
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")] = False,
) -> None:
    _utf8_stdout()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)


def _fail(message: str, code: int = 2) -> typer.Exit:
    err.print(f"[bold red]error:[/] {escape(message)}")
    return typer.Exit(code)


def print_text(report: ReviewReport, console: Console) -> None:
    r = report
    console.print(f"\n[bold]codeview[/] · {escape(r.target)}")
    if r.title:
        console.print(f"[dim]{escape(r.title)}[/]")
    color = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}[r.risk.level]
    console.print(
        f"{VERDICT_TEXT[r.verdict]} · risk [{color}]{r.risk.score}/100 ({r.risk.level})[/] · "
        f"{plural(r.stats.files_reviewed, 'file')} · [green]+{r.stats.additions}[/]/[red]-{r.stats.deletions}[/]\n"
    )
    console.print(escape(r.summary), soft_wrap=True)
    if r.findings:
        table = Table(show_header=True, header_style="bold", expand=True, show_lines=True)
        table.add_column("Severity", width=9)
        table.add_column("Finding", ratio=3)
        table.add_column("Location", ratio=1, overflow="fold")
        table.add_column("Source", width=11)
        for f in r.findings:
            body = f"[bold]{escape(f.title)}[/]\n{escape(f.message)}"
            if f.suggestion:
                body += f"\n[cyan]→ {escape(f.suggestion)}[/]"
            table.add_row(
                LABELS[f.severity],
                body,
                escape(f"{f.path}:{f.line}" if f.line else f.path),
                f.rule_id if f.source == "static" else "AI",
            )
        console.print(table)
    else:
        console.print("\n[green]No issues found.[/]")
    engine = (
        f"{r.ai.provider} · {r.ai.model}{' (cached)' if r.ai.cached else ''}"
        if r.ai and not r.ai.error
        else "static rules only"
    )
    console.print(f"\n[dim]{escape(engine)} · {r.duration_ms} ms[/]")
    if r.ai and r.ai.error:
        console.print(f"[yellow]AI pass unavailable:[/] {escape(r.ai.error)}")
    elif r.ai is None:
        console.print("[dim]Tip: set GEMINI_API_KEY (free) for AI review — run `codeview providers`.[/]")


def _emit(report: ReviewReport, fmt: OutputFormat, output: Path | None) -> None:
    if fmt is OutputFormat.text and output is None:
        print_text(report, Console())
        return
    if fmt is OutputFormat.markdown or fmt is OutputFormat.text:
        text = to_markdown(report)
    elif fmt is OutputFormat.json:
        text = report.model_dump_json(indent=2)
    else:
        text = json.dumps(to_sarif(report), indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        err.print(f"[dim]wrote {output}[/]")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


@app.command()
def review(
    target: Annotated[
        str | None,
        typer.Argument(help="PR URL or OWNER/REPO#N. Omit to review local uncommitted changes.", show_default=False),
    ] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Review only staged changes.")] = False,
    branch: Annotated[bool, typer.Option("--branch", "-b", help="Review the current branch against its base.")] = False,
    base: Annotated[str | None, typer.Option(help="Base branch for --branch.")] = None,
    repo: Annotated[Path, typer.Option("--repo", "-C", help="Local repository path.")] = Path(),
    diff_file: Annotated[str | None, typer.Option("--diff", help="Review a unified diff file ('-' for stdin).")] = None,
    fmt: Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format.")] = OutputFormat.text,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write the report to a file.")] = None,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Static rules only; no AI call.")] = False,
    provider: Annotated[
        str | None,
        typer.Option(help="auto, gemini, groq, cerebras, openrouter, ollama, openai-compatible, none."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override the provider's default model.")] = None,
    focus: Annotated[list[str] | None, typer.Option(help="Extra emphasis (repeatable), e.g. --focus security.")] = None,
    fail_on: Annotated[
        str | None,
        typer.Option(help="Exit 1 if a finding is at/above this severity (critical|high|medium|low|info|never)."),
    ] = None,
    max_risk: Annotated[
        int | None, typer.Option(min=0, max=100, help="Exit 1 if the risk score exceeds this value.")
    ] = None,
    post: Annotated[bool, typer.Option("--post", help="Publish the review to the pull request.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="With --post: print the GitHub payload instead of posting.")
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help=f"Config file (default: nearest {CONFIG_FILENAME}).")
    ] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Don't reuse cached AI responses.")] = False,
    json_output: Annotated[Path | None, typer.Option(help="Also write the JSON report to this file.")] = None,
    sarif_output: Annotated[Path | None, typer.Option(help="Also write a SARIF 2.1.0 report to this file.")] = None,
) -> None:
    """Review a GitHub pull request, local git changes, or a diff file."""
    from codeview.reviewer import (
        ReviewOutcome,
        apply_focus,
        publish_review,
        review_diff,
        review_local,
        review_pull_request,
    )
    from codeview.sources.local import GitError, LocalMode

    try:
        config: Config | None = load_config(config_path) if config_path else None
        overrides: dict[str, object] = {}
        if provider:
            overrides["provider"] = provider.strip().lower()
        if model:
            overrides["model"] = model.strip()
        if fail_on:
            overrides["fail_on"] = Config.model_validate({"fail_on": fail_on}).fail_on

        def finalize(cfg: Config) -> Config:
            return apply_focus(cfg.model_copy(update=overrides), focus)

        use_ai = False if no_ai else None
        use_cache = False if no_cache else None

        if diff_file is not None:
            text = (
                sys.stdin.read() if diff_file == "-" else Path(diff_file).read_text(encoding="utf-8", errors="replace")
            )
            cfg = finalize(config or load_config())
            outcome = asyncio.run(review_diff(text, target=diff_file, config=cfg, use_ai=use_ai, use_cache=use_cache))
        elif target:
            ref = parse_pr_ref(target)

            async def _pr() -> tuple[ReviewOutcome, dict[str, object] | None]:
                from codeview.sources.github import GitHubClient

                async with GitHubClient() as gh:
                    outcome = await review_pull_request(
                        ref, config=config, client=gh, use_ai=use_ai, use_cache=use_cache, adjust=finalize
                    )
                    published = None
                    if post:
                        try:
                            published = await publish_review(
                                outcome,
                                client=gh,
                                dry_run=dry_run,
                                max_comments=min(outcome.config.max_findings, 50),
                            )
                        except GitHubError as exc:
                            if exc.status not in (401, 403, 404):
                                raise
                            # e.g. PRs from forks get a read-only token: keep the report, skip posting.
                            err.print(f"[yellow]warning:[/] could not post the review: {escape(str(exc))}")
                    return outcome, published

            outcome, published = asyncio.run(_pr())
            if published is not None:
                if dry_run:
                    err.print_json(json.dumps(published, default=str))
                else:
                    err.print(f"[green]posted review:[/] {published.get('review_url')}")
        else:
            if post:
                raise _fail("--post needs a pull request target")
            mode: LocalMode = "staged" if staged else "branch" if branch else "working"
            cfg = finalize(config or load_config(start=repo))
            outcome = asyncio.run(
                review_local(repo, mode=mode, base=base, config=cfg, use_ai=use_ai, use_cache=use_cache)
            )
    except (ValueError, ConfigError, GitHubError, GitError, LLMError, OSError) as exc:
        raise _fail(str(exc)) from None

    report = outcome.report
    _emit(report, fmt, output)
    if json_output:
        _emit(report, OutputFormat.json, json_output)
    if sarif_output:
        _emit(report, OutputFormat.sarif, sarif_output)
    _github_step_summary(report)

    threshold = outcome.config.fail_on
    worst = report.worst()
    if threshold is not None and worst is not None and worst.rank >= threshold.rank:
        err.print(f"[red]findings at or above '{threshold.value}': failing[/]")
        raise typer.Exit(1)
    if max_risk is not None and report.risk.score > max_risk:
        err.print(f"[red]risk {report.risk.score} exceeds --max-risk {max_risk}[/]")
        raise typer.Exit(1)


def _github_step_summary(report: ReviewReport) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(to_markdown(report) + "\n")
    except OSError:
        pass


@app.command()
def serve(
    http: Annotated[bool, typer.Option("--http", help="Serve over Streamable HTTP instead of stdio.")] = False,
    host: Annotated[str, typer.Option(help="HTTP bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="HTTP port.")] = 8765,
) -> None:
    """Run the MCP server (stdio by default, for MCP clients)."""
    from codeview.server import run

    run("http" if http else "stdio", host=host, port=port)


@app.command()
def providers() -> None:
    """Show free AI providers, which are configured, and how to get a key."""
    from codeview.server import _providers_info

    info = _providers_info()
    table = Table(title="AI providers (all free)", show_lines=False)
    for col in ("Configured", "Provider", "Default model", "Key variable", "Get a key"):
        table.add_column(col)
    for p in info["providers"]:
        table.add_row(
            "yes" if p["configured"] else "-",
            p["label"],
            p["default_model"] or "CODEVIEW_MODEL",
            ", ".join(p["key_env"] or ["CODEVIEW_OLLAMA=1" if p["name"] == "ollama" else "CODEVIEW_BASE_URL"]),
            p["get_a_key"] or "",
        )
    Console().print(table)
    order = info["fallback_order"]
    plan = ", ".join(order) if order else "[yellow]none (static rules only)[/]"
    Console().print(f"provider = [bold]{info['selected']}[/] → will try: {plan}")


@app.command()
def rules(category: Annotated[str | None, typer.Option(help="Filter by category.")] = None) -> None:
    """List built-in static rules."""
    from codeview.rules.builtin import BUILTIN_RULES

    table = Table(show_lines=False)
    for col in ("ID", "Severity", "Category", "Title", "CWE"):
        table.add_column(col)
    for r in BUILTIN_RULES:
        if category and r.category.value != category.lower():
            continue
        table.add_row(r.id, r.severity.value, r.category.value, r.title, r.cwe or "")
    Console().print(table)


@app.command()
def init(force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False) -> None:
    """Create a commented .codeview.toml in the current directory."""
    path = Path(CONFIG_FILENAME)
    if path.exists() and not force:
        raise _fail(f"{path} already exists (use --force to overwrite)")
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    err.print(f"[green]created {path}[/]")


@app.command("mcp-config")
def mcp_config() -> None:
    """Print a JSON snippet to register codeview in an MCP client."""
    snippet = {
        "mcpServers": {
            "codeview": {
                "command": "uvx",
                "args": ["--from", GIT_SOURCE, "codeview", "serve"],
                "env": {
                    "GEMINI_API_KEY": "<free key from https://aistudio.google.com/apikey>",
                    "GITHUB_TOKEN": "<optional: needed for private repos and posting reviews>",  # nosec B105
                },
            }
        }
    }
    sys.stdout.write(json.dumps(snippet, indent=2) + "\n")


@app.command("clear-cache")
def clear_cache() -> None:
    """Delete cached AI responses."""
    removed = ResponseCache().clear()
    err.print(f"removed {removed} cached responses")


if __name__ == "__main__":  # pragma: no cover
    app()
