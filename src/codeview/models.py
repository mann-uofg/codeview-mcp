"""Typed data model shared by the reviewer, the renderers, the CLI and the MCP server."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @classmethod
    def parse(cls, value: str | Severity | None, default: Severity | None = None) -> Severity:
        """Lenient parser for severities coming from config files and model output."""
        if isinstance(value, Severity):
            return value
        text = (value or "").strip().lower()
        aliases = {
            "blocker": "critical",
            "major": "high",
            "warning": "medium",
            "warn": "medium",
            "minor": "low",
            "nit": "info",
            "nitpick": "info",
            "note": "info",
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError:
            if default is None:
                raise
            return default


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class Category(StrEnum):
    SECURITY = "security"
    BUG = "bug"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    TESTING = "testing"
    STYLE = "style"

    @classmethod
    def parse(cls, value: str | None) -> Category:
        text = (value or "").strip().lower()
        aliases = {
            "correctness": "bug",
            "logic": "bug",
            "reliability": "bug",
            "perf": "performance",
            "readability": "maintainability",
            "design": "maintainability",
            "tests": "testing",
            "test": "testing",
            "docs": "style",
            "documentation": "style",
        }
        text = aliases.get(text, text)
        try:
            return cls(text)
        except ValueError:
            return cls.MAINTAINABILITY


class Finding(BaseModel):
    """A single review comment anchored to a changed line."""

    path: str
    line: int | None = Field(default=None, description="Line number in the new version of the file.")
    severity: Severity
    category: Category
    title: str
    message: str
    suggestion: str | None = None
    rule_id: str = Field(description="Static rule id (e.g. CV-SEC-001) or 'AI' for model findings.")
    source: Literal["static", "ai"]
    cwe: str | None = None

    @property
    def fingerprint(self) -> str:
        return f"{self.path}:{self.line}:{self.rule_id}:{self.title.lower()}"


class RiskFactor(BaseModel):
    name: str
    points: float
    detail: str


class Risk(BaseModel):
    score: int = Field(ge=0, le=100)
    level: Literal["low", "medium", "high", "critical"]
    factors: list[RiskFactor] = Field(default_factory=list)

    @staticmethod
    def level_for(score: float) -> Literal["low", "medium", "high", "critical"]:
        if score >= 75:
            return "critical"
        if score >= 50:
            return "high"
        if score >= 25:
            return "medium"
        return "low"


class DiffStats(BaseModel):
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    files_reviewed: int = 0
    files_skipped: list[str] = Field(default_factory=list)


class AIInfo(BaseModel):
    provider: str
    model: str
    cached: bool = False
    truncated: bool = Field(default=False, description="True when the diff was trimmed to fit the model budget.")
    error: str | None = None


class ReviewReport(BaseModel):
    """The result of reviewing one change set."""

    target: str
    title: str | None = None
    summary: str
    verdict: Literal["approve", "comment", "request_changes"]
    risk: Risk
    findings: list[Finding] = Field(default_factory=list)
    stats: DiffStats = Field(default_factory=DiffStats)
    ai: AIInfo | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int = 0

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), key=lambda s: s.rank, default=None)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
