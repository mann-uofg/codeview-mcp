"""Configuration: ``.reviewgenie.toml`` or ``[tool.reviewgenie]`` in ``pyproject.toml``.

For pull-request reviews the configuration is read from the PR's *base* branch (see
:mod:`reviewgenie.reviewer`), so a pull request cannot weaken its own review.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reviewgenie.models import Category, Severity

CONFIG_FILENAME = ".reviewgenie.toml"
MAX_CUSTOM_PATTERN = 300


class ConfigError(ValueError):
    pass


class CustomRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{1,40}$")
    pattern: str = Field(max_length=MAX_CUSTOM_PATTERN)
    message: str = Field(max_length=500)
    title: str | None = Field(default=None, max_length=120)
    severity: Severity = Severity.MEDIUM
    category: Category = Category.MAINTAINABILITY
    paths: list[str] = Field(default_factory=list, description="Glob patterns; empty means all files.")
    suggestion: str | None = Field(default=None, max_length=500)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return value

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, value: Any) -> Severity:
        return Severity.parse(value)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(
        default="auto",
        description="auto, gemini, groq, cerebras, openrouter, ollama, openai-compatible or none",
    )
    model: str | None = None
    ai: bool = True
    cache: bool = True
    exclude: list[str] = Field(default_factory=list, description="Glob patterns of files to skip entirely.")
    include_noise: bool = Field(default=False, description="Also review lockfiles, minified and generated files.")
    disable_rules: list[str] = Field(default_factory=list)
    min_severity: Severity = Severity.LOW
    fail_on: Severity | None = Severity.HIGH
    max_findings: int = Field(default=30, ge=1, le=200)
    focus: list[str] = Field(default_factory=list, description="Extra emphasis for the AI reviewer, e.g. ['security'].")
    instructions: str = Field(default="", max_length=4000, description="Team guidelines appended to the AI prompt.")
    custom_rules: list[CustomRule] = Field(default_factory=list)

    @field_validator("min_severity", mode="before")
    @classmethod
    def _min_sev(cls, value: Any) -> Severity:
        return Severity.parse(value)

    @field_validator("fail_on", mode="before")
    @classmethod
    def _fail_on(cls, value: Any) -> Severity | None:
        if value in (None, "", "never", "none", False):
            return None
        return Severity.parse(value)

    def with_env(self) -> Config:
        """Apply ``RG_PROVIDER`` / ``RG_MODEL`` environment overrides."""
        updates: dict[str, Any] = {}
        if provider := os.environ.get("RG_PROVIDER"):
            updates["provider"] = provider.strip().lower()
        if model := os.environ.get("RG_MODEL"):
            updates["model"] = model.strip()
        return self.model_copy(update=updates) if updates else self


def parse_config(text: str, *, source: str = "config", pyproject: bool = False) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: invalid TOML: {exc}") from exc
    if pyproject:
        data = data.get("tool", {}).get("reviewgenie", {})
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{source}: {exc}") from exc


def find_config(start: Path) -> Path | None:
    """Find the nearest config file walking up from ``start`` (stops at the git root)."""
    start = start.resolve()
    for folder in (start, *start.parents):
        candidate = folder / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file() and "[tool.reviewgenie" in pyproject.read_text(encoding="utf-8", errors="replace"):
            return pyproject
        if (folder / ".git").exists():
            break
    return None


def load_config(path: Path | None = None, *, start: Path | None = None) -> Config:
    """Load config from an explicit path or by discovery; defaults when nothing is found."""
    target = path or find_config(start or Path.cwd())
    if target is None:
        return Config().with_env()
    if not target.is_file():
        raise ConfigError(f"config file not found: {target}")
    text = target.read_text(encoding="utf-8")
    return parse_config(text, source=str(target), pyproject=target.name == "pyproject.toml").with_env()


EXAMPLE_CONFIG = """\
# ReviewGenie configuration. Every key is optional.

# AI provider: auto | gemini | groq | cerebras | openrouter | ollama | openai-compatible | none
provider = "auto"
# model = "..."            # override the provider's default model

min_severity = "low"       # drop findings below this level
fail_on = "high"           # `reviewgenie review` exits 1 at/above this level ("never" to disable)
max_findings = 30

exclude = ["docs/**", "**/*.generated.ts"]
disable_rules = []          # e.g. ["RG-QUAL-001"]
focus = ["security", "bugs"]

instructions = \"\"\"
We use SQLAlchemy 2.x; flag any raw SQL built with string formatting.
Public functions need docstrings.
\"\"\"

[[custom_rules]]
id = "TEAM-001"
pattern = "print\\\\("
message = "Use the structured logger instead of print()."
severity = "low"
paths = ["src/**/*.py"]
"""
