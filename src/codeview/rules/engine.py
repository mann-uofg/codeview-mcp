"""Deterministic rule engine: fast regex checks over *added* lines only."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from codeview.config import Config, CustomRule
from codeview.diff import DiffFile, matches_any
from codeview.models import Category, Finding, Severity

MAX_LINE_LENGTH = 2000  # longer lines are almost always minified or generated
_SUPPRESS_RE = re.compile(r"(?:codeview|cv)-ignore(?:\[(?P<ids>[A-Za-z0-9_.,\s-]+)\])?", re.I)
_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|testdata|fixtures?)/|(^|/)(test_[^/]+|[^/]+_test\.\w+|[^/]+\.(test|spec)\.\w+|conftest\.py)$"
)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    title: str
    severity: Severity
    category: Category
    pattern: re.Pattern[str]
    message: str
    suggestion: str | None = None
    cwe: str | None = None
    languages: frozenset[str] | None = None
    paths: tuple[str, ...] = ()
    secret: bool = False
    skip_tests: bool = False
    ignore_if: re.Pattern[str] | None = None
    tags: tuple[str, ...] = field(default=())

    def applies_to(self, f: DiffFile) -> bool:
        if self.languages is not None and f.language not in self.languages:
            return False
        if self.paths and not matches_any(f.path, self.paths):
            return False
        # Dangerous-API rules (eval, pickle, shell…) are noise in tests; leaked secrets are not.
        noisy_in_tests = self.skip_tests or (self.category is Category.SECURITY and not self.secret and not self.paths)
        return not (noisy_in_tests and is_test_path(f.path))


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path.replace("\\", "/")))


def redact(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}…{'*' * 4} ({len(secret)} chars)"


def _suppressed(line: str, rule_id: str) -> bool:
    m = _SUPPRESS_RE.search(line)
    if not m:
        return False
    ids = m.group("ids")
    if not ids:
        return True
    return rule_id.upper() in {i.strip().upper() for i in ids.split(",")}


def compile_custom(rule: CustomRule) -> Rule:
    return Rule(
        id=rule.id,
        title=rule.title or rule.message[:80],
        severity=rule.severity,
        category=rule.category,
        pattern=re.compile(rule.pattern),
        message=rule.message,
        suggestion=rule.suggestion,
        paths=tuple(rule.paths),
    )


def active_rules(config: Config) -> list[Rule]:
    from codeview.rules.builtin import BUILTIN_RULES

    disabled = {r.upper() for r in config.disable_rules}
    rules = [r for r in BUILTIN_RULES if r.id.upper() not in disabled]
    rules += [compile_custom(c) for c in config.custom_rules if c.id.upper() not in disabled]
    return rules


def scan(files: Iterable[DiffFile], rules: list[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    for f in files:
        if f.is_binary or f.status == "deleted":
            continue
        applicable = [r for r in rules if r.applies_to(f)]
        if not applicable:
            continue
        for ln in f.added_lines():
            text = ln.content
            if len(text) > MAX_LINE_LENGTH or not text.strip():
                continue
            for rule in applicable:
                m = rule.pattern.search(text)
                if not m:
                    continue
                if rule.ignore_if is not None and rule.ignore_if.search(m.group(0)):
                    continue
                if _suppressed(text, rule.id):
                    continue
                message = rule.message
                if rule.secret:
                    message = f"{message} Detected value: `{redact(m.group(0))}`."
                findings.append(
                    Finding(
                        path=f.path,
                        line=ln.new_no,
                        severity=rule.severity,
                        category=rule.category,
                        title=rule.title,
                        message=message,
                        suggestion=rule.suggestion,
                        rule_id=rule.id,
                        source="static",
                        cwe=rule.cwe,
                    )
                )
    return findings
