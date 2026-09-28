"""Explainable risk scoring (0-100) built from deterministic signals, optionally blended with the AI's view."""

from __future__ import annotations

import math
import re

from codeview.diff import DiffFile
from codeview.models import Finding, Risk, RiskFactor, Severity, plural
from codeview.rules.engine import is_test_path

_SENSITIVE = [
    (
        re.compile(
            r"(?i)(^|/)(auth|oauth|login|session|security|crypto|permission|acl|rbac|jwt|password|secret|token)"
        ),
        "authentication / security code",
    ),
    (re.compile(r"(?i)(^|/)(payment|billing|checkout|invoice|wallet|stripe)"), "payments / billing code"),
    (
        re.compile(r"(?i)(^|/)(migrations?|alembic|schema\.(sql|prisma|rb))(/|$|\.)"),
        "database migrations / schema",
    ),
    (
        re.compile(r"(?i)^\.github/workflows/|(^|/)(action\.ya?ml|\.gitlab-ci\.yml|Jenkinsfile|azure-pipelines\.yml)$"),
        "CI/CD pipeline",
    ),
    (
        re.compile(r"(?i)(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|.*\.tf|k8s/|helm/|charts/)"),
        "infrastructure / deployment",
    ),
    (
        re.compile(r"(?i)(^|/)(\.env[^/]*|settings\.py|config/(prod|production)[^/]*)$"),
        "environment / production config",
    ),
    (
        re.compile(
            r"(?i)(^|/)(package\.json|requirements[^/]*\.txt|pyproject\.toml|go\.mod|Cargo\.toml|pom\.xml|build\.gradle(\.kts)?|Gemfile)$"
        ),
        "dependency manifest",
    ),
]

_SEVERITY_POINTS = {
    Severity.CRITICAL: 35.0,
    Severity.HIGH: 15.0,
    Severity.MEDIUM: 5.0,
    Severity.LOW: 1.5,
    Severity.INFO: 0.0,
}


def compute_risk(files: list[DiffFile], findings: list[Finding], ai_score: int | None = None) -> Risk:
    factors: list[RiskFactor] = []
    changed = sum(f.additions + f.deletions for f in files)

    # 1. Size: logarithmic, capped. ~100 lines -> 10, ~1000 lines -> 20.
    if changed:
        size_pts = min(22.0, 10.0 * math.log10(max(changed, 1)))
        factors.append(
            RiskFactor(
                name="size",
                points=round(size_pts, 1),
                detail=f"{changed} changed lines across {plural(len(files), 'file')}",
            )
        )
    if len(files) > 25:
        factors.append(RiskFactor(name="breadth", points=5, detail=f"{len(files)} files touched"))

    # 2. Sensitive areas.
    areas: dict[str, list[str]] = {}
    for f in files:
        for pattern, label in _SENSITIVE:
            if pattern.search(f.path):
                areas.setdefault(label, []).append(f.path)
                break
    if areas:
        pts = min(20.0, 7.0 * len(areas))
        detail = "; ".join(
            f"{label}: {', '.join(paths[:3])}{' …' if len(paths) > 3 else ''}" for label, paths in areas.items()
        )
        factors.append(RiskFactor(name="sensitive_areas", points=pts, detail=detail))

    # 3. Findings.
    if findings:
        pts = min(55.0, sum(_SEVERITY_POINTS[f.severity] for f in findings))
        worst = max(findings, key=lambda f: f.severity.rank).severity
        if pts:
            factors.append(
                RiskFactor(
                    name="findings",
                    points=round(pts, 1),
                    detail=f"{len(findings)} findings (worst: {worst.value})",
                )
            )

    # 4. Source changed without tests.
    src_lines = sum(
        f.additions
        for f in files
        if f.language not in (None, "markdown", "json", "yaml", "toml") and not is_test_path(f.path)
    )
    test_touched = any(is_test_path(f.path) for f in files)
    if src_lines >= 40 and not test_touched:
        factors.append(
            RiskFactor(name="no_tests", points=8, detail=f"{src_lines} lines of source added with no test changes")
        )

    # 5. Deleted files.
    deleted = [f.path for f in files if f.status == "deleted"]
    if deleted:
        factors.append(
            RiskFactor(name="deletions", points=min(6.0, 2.0 * len(deleted)), detail=f"{len(deleted)} files deleted")
        )

    score = sum(f.points for f in factors)
    if ai_score is not None:
        ai_score = max(0, min(100, int(ai_score)))
        blended = 0.65 * score + 0.35 * ai_score
        factors.append(
            RiskFactor(
                name="ai_assessment",
                points=round(blended - score, 1),
                detail=f"AI reviewer rated the change {ai_score}/100",
            )
        )
        score = blended

    # A critical finding always makes the change at least high risk.
    if any(f.severity is Severity.CRITICAL for f in findings):
        score = max(score, 60.0)

    final = round(max(0.0, min(100.0, score)))
    return Risk(score=final, level=Risk.level_for(final), factors=factors)
