"""The review pipeline: diff -> filters -> static rules -> AI pass -> merge -> risk -> report."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from reviewgenie.cache import ResponseCache
from reviewgenie.config import CONFIG_FILENAME, Config, ConfigError, load_config, parse_config
from reviewgenie.diff import DiffFile, is_noise, matches_any, parse_diff
from reviewgenie.llm.review import AIResult, ai_review
from reviewgenie.models import Category, DiffStats, Finding, ReviewReport, Severity
from reviewgenie.risk import compute_risk
from reviewgenie.rules import active_rules, scan
from reviewgenie.sources.github import GitHubClient, PRRef, PullRequest
from reviewgenie.sources.local import LocalMode, local_diff

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ReviewOutcome:
    report: ReviewReport
    files: list[DiffFile]
    config: Config
    pull: PullRequest | None = None


def split_files(files: list[DiffFile], config: Config) -> tuple[list[DiffFile], list[str]]:
    keep: list[DiffFile] = []
    skipped: list[str] = []
    for f in files:
        if matches_any(f.path, config.exclude) or (not config.include_noise and is_noise(f.path)):
            skipped.append(f.path)
        else:
            keep.append(f)
    return keep, skipped


def merge_findings(static: list[Finding], ai: list[Finding], config: Config) -> list[Finding]:
    merged = list(static)
    for f in ai:
        # The AI often re-reports what a rule already caught (e.g. the same injection or secret).
        # Treat it as a duplicate on the same line, or within two lines for security issues.
        duplicate = any(
            s.path == f.path
            and s.category == f.category
            and s.line is not None
            and f.line is not None
            and abs(s.line - f.line) <= (2 if f.category is Category.SECURITY else 0)
            for s in static
        )
        if not duplicate:
            merged.append(f)
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in merged:
        if f.fingerprint in seen:
            continue
        seen.add(f.fingerprint)
        unique.append(f)
    unique = [f for f in unique if f.severity.rank >= config.min_severity.rank]
    unique.sort(key=lambda f: (-f.severity.rank, f.source != "static", f.path, f.line or 0))
    return unique[: config.max_findings]


def decide_verdict(findings: list[Finding], ai: AIResult | None) -> str:
    worst = max((f.severity.rank for f in findings), default=-1)
    if worst >= Severity.HIGH.rank:
        return "request_changes"
    if worst >= Severity.MEDIUM.rank or (ai and ai.verdict == "request_changes"):
        return "comment"
    if findings and any(f.severity.rank >= Severity.LOW.rank for f in findings):
        return "comment"
    return "approve"


def _fallback_summary(stats: DiffStats, findings: list[Finding], ai: AIResult | None) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    breakdown = ", ".join(f"{n} {sev}" for sev, n in counts.items()) or "no issues"
    text = (
        f"Reviewed {stats.files_reviewed} of {stats.files_changed} changed files "
        f"(+{stats.additions}/-{stats.deletions}): {breakdown}."
    )
    if ai is None:
        text += " Static analysis only; configure a free AI provider (e.g. GEMINI_API_KEY) for a deeper review."
    elif ai.info and ai.info.error:
        text += " The AI pass was unavailable, so this is static analysis only."
    return text


async def review_diff(
    diff_text: str,
    *,
    target: str,
    config: Config | None = None,
    title: str | None = None,
    description: str | None = None,
    use_ai: bool | None = None,
    use_cache: bool | None = None,
) -> ReviewOutcome:
    started = time.perf_counter()
    config = config or load_config()
    files = parse_diff(diff_text)
    reviewable, skipped = split_files(files, config)

    static = scan(reviewable, active_rules(config))
    ai: AIResult | None = None
    if use_ai if use_ai is not None else config.ai:
        cache = ResponseCache() if (use_cache if use_cache is not None else config.cache) else None
        ai = await ai_review(reviewable, config, title=title, description=description, cache=cache)

    findings = merge_findings(static, ai.findings if ai else [], config)
    stats = DiffStats(
        files_changed=len(files),
        additions=sum(f.additions for f in files),
        deletions=sum(f.deletions for f in files),
        files_reviewed=len(reviewable),
        files_skipped=skipped,
    )
    risk = compute_risk(reviewable, findings, ai.risk if ai and not (ai.info and ai.info.error) else None)
    summary = ai.summary if ai and ai.summary else _fallback_summary(stats, findings, ai)
    report = ReviewReport(
        target=target,
        title=title,
        summary=summary,
        verdict=decide_verdict(findings, ai),  # type: ignore[arg-type]
        risk=risk,
        findings=findings,
        stats=stats,
        ai=ai.info if ai else None,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return ReviewOutcome(report=report, files=reviewable, config=config)


async def load_base_config(client: GitHubClient, ref: PRRef, base_sha: str) -> Config:
    """Read config from the PR's base commit so the PR under review cannot change its own rules."""
    text = await client.get_file(ref, CONFIG_FILENAME, base_sha)
    if text is not None:
        return parse_config(text, source=f"{ref.slug}@{base_sha[:7]}:{CONFIG_FILENAME}").with_env()
    text = await client.get_file(ref, "pyproject.toml", base_sha)
    if text is not None and "[tool.reviewgenie" in text:
        try:
            return parse_config(text, source="pyproject.toml", pyproject=True).with_env()
        except ConfigError as exc:
            log.warning("ignoring invalid [tool.reviewgenie] in base pyproject.toml: %s", exc)
    return Config().with_env()


def apply_focus(config: Config, focus: list[str] | None) -> Config:
    if not focus:
        return config
    return config.model_copy(update={"focus": [f.strip()[:40] for f in focus[:8] if f.strip()]})


async def review_pull_request(
    ref: PRRef,
    *,
    config: Config | None = None,
    client: GitHubClient | None = None,
    use_ai: bool | None = None,
    use_cache: bool | None = None,
    focus: list[str] | None = None,
    adjust: Callable[[Config], Config] | None = None,
) -> ReviewOutcome:
    """Review a PR. ``adjust`` can tweak the (base-branch) config, e.g. for CLI overrides."""
    owns_client = client is None
    gh = client or GitHubClient()
    try:
        pull = await gh.get_pull(ref)
        diff_text = await gh.get_diff(ref)
        cfg = apply_focus(config or await load_base_config(gh, ref, pull.base_sha), focus)
        if adjust is not None:
            cfg = adjust(cfg)
    finally:
        if owns_client:
            await gh.__aexit__(None, None, None)
    outcome = await review_diff(
        diff_text,
        target=pull.html_url or str(ref),
        config=cfg,
        title=pull.title,
        description=pull.body,
        use_ai=use_ai,
        use_cache=use_cache,
    )
    outcome.pull = pull
    return outcome


async def review_local(
    path: str | Path = ".",
    *,
    mode: LocalMode = "working",
    base: str | None = None,
    config: Config | None = None,
    use_ai: bool | None = None,
    use_cache: bool | None = None,
    focus: list[str] | None = None,
) -> ReviewOutcome:
    repo, description, diff_text = local_diff(path, mode, base)
    cfg = apply_focus(config or load_config(start=repo), focus)
    return await review_diff(
        diff_text,
        target=f"{repo.name}: {description}",
        config=cfg,
        title=None,
        use_ai=use_ai,
        use_cache=use_cache,
    )


async def publish_review(
    outcome: ReviewOutcome,
    *,
    client: GitHubClient | None = None,
    dry_run: bool = False,
    max_comments: int = 30,
) -> dict[str, object]:
    """Post the report as a single GitHub review with inline comments (skipping ones already posted)."""
    from reviewgenie.render import github_review_payload

    if outcome.pull is None:
        raise ValueError("only pull request reviews can be published")
    pull = outcome.pull
    owns_client = client is None
    gh = client or GitHubClient()
    try:
        existing = await gh.existing_comment_keys(pull.ref)
        payload = github_review_payload(outcome.report, outcome.files, existing=existing, max_comments=max_comments)
        result: dict[str, object] = {
            "pull_request": pull.html_url,
            "event": payload["event"],
            "inline_comments": len(payload["comments"]),
            "already_posted": len(existing),
            "dry_run": dry_run,
        }
        if dry_run:
            result["preview"] = payload
            return result
        if not gh.token:
            raise ValueError("posting a review needs GITHUB_TOKEN (or `gh auth login`)")
        created = await gh.create_review(
            pull.ref,
            commit_id=pull.head_sha,
            body=payload["body"],
            event=payload["event"],
            comments=payload["comments"],
        )
        result["review_url"] = created.get("html_url")
        return result
    finally:
        if owns_client:
            await gh.__aexit__(None, None, None)
