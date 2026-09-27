from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SAMPLE_DIFF, make_diff
from reviewgenie.config import EXAMPLE_CONFIG, Config, ConfigError, find_config, load_config, parse_config
from reviewgenie.diff import parse_diff
from reviewgenie.models import Category, Finding, Risk, Severity
from reviewgenie.risk import compute_risk


def finding(sev: Severity, path: str = "a.py") -> Finding:
    return Finding(
        path=path, line=1, severity=sev, category=Category.BUG, title="t", message="m", rule_id="X", source="static"
    )


def test_example_config_is_valid() -> None:
    cfg = parse_config(EXAMPLE_CONFIG)
    assert cfg.fail_on is Severity.HIGH
    assert cfg.custom_rules[0].id == "TEAM-001"
    assert cfg.focus == ["security", "bugs"]


def test_config_rejects_unknown_keys_and_bad_regex() -> None:
    with pytest.raises(ConfigError, match="extra"):
        parse_config('provder = "gemini"')
    with pytest.raises(ConfigError, match="invalid regex"):
        parse_config('[[custom_rules]]\nid = "X1"\npattern = "("\nmessage = "m"\n')
    with pytest.raises(ConfigError, match="invalid TOML"):
        parse_config("= nope")


def test_fail_on_never_and_severity_aliases() -> None:
    assert parse_config('fail_on = "never"').fail_on is None
    assert parse_config('min_severity = "warning"').min_severity is Severity.MEDIUM


def test_pyproject_and_discovery(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text('[tool.reviewgenie]\nprovider = "groq"\n', encoding="utf-8")
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    assert find_config(sub) == tmp_path / "pyproject.toml"
    assert load_config(start=sub).provider == "groq"
    (tmp_path / ".reviewgenie.toml").write_text('provider = "gemini"\n', encoding="utf-8")
    assert load_config(start=sub).provider == "gemini"


def test_discovery_stops_at_git_root(tmp_path: Path) -> None:
    (tmp_path / ".reviewgenie.toml").write_text('provider = "groq"\n', encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert find_config(repo) is None


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RG_PROVIDER", "Cerebras")
    monkeypatch.setenv("RG_MODEL", "some-model")
    cfg = Config().with_env()
    assert (cfg.provider, cfg.model) == ("cerebras", "some-model")


def test_risk_small_clean_change_is_low() -> None:
    risk = compute_risk(parse_diff(make_diff("README.md", ["hello"])), [])
    assert risk.level == "low"
    assert risk.score < 10


def test_risk_factors_accumulate_and_explain() -> None:
    files = parse_diff(
        make_diff("src/auth/login.py", [f"x{i} = {i}" for i in range(120)])
        + make_diff(".github/workflows/ci.yml", ["on: push"])
    )
    risk = compute_risk(files, [finding(Severity.HIGH), finding(Severity.MEDIUM)])
    names = {f.name for f in risk.factors}
    assert {"size", "sensitive_areas", "findings", "no_tests"} <= names
    assert risk.score == round(sum(f.points for f in risk.factors))
    assert 25 <= risk.score <= 100


def test_critical_finding_forces_high_risk_and_ai_blend_is_bounded() -> None:
    files = parse_diff(make_diff("a.py", ["x = 1"]))
    assert compute_risk(files, [finding(Severity.CRITICAL)]).score >= 60
    blended = compute_risk(parse_diff(SAMPLE_DIFF), [], ai_score=500)
    assert 0 <= blended.score <= 100
    assert any(f.name == "ai_assessment" for f in blended.factors)


@pytest.mark.parametrize(("score", "level"), [(0, "low"), (24, "low"), (25, "medium"), (50, "high"), (75, "critical")])
def test_risk_levels(score: int, level: str) -> None:
    assert Risk.level_for(score) == level


def test_severity_parsing() -> None:
    assert Severity.parse("BLOCKER") is Severity.CRITICAL
    assert Severity.parse("nonsense", Severity.LOW) is Severity.LOW
    with pytest.raises(ValueError, match="nonsense"):
        Severity.parse("nonsense")
    assert Category.parse("perf") is Category.PERFORMANCE
    assert Category.parse("???") is Category.MAINTAINABILITY
