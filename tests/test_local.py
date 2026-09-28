from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codeview.diff import parse_diff
from codeview.sources.local import GitError, local_diff, validate_ref

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "commit.gpgsign", "false")
    (r / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-qm", "init")
    return r


def test_working_tree_includes_untracked(repo: Path) -> None:
    (repo / "app.py").write_text("def f():\n    return eval(x)\n", encoding="utf-8")
    (repo / "new.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02")
    root, desc, diff = local_diff(repo, "working")
    assert root == repo.resolve()
    assert desc == "uncommitted changes"
    files = {f.path: f for f in parse_diff(diff)}
    assert set(files) == {"app.py", "new.py"}
    assert files["new.py"].status == "added"
    assert files["app.py"].added_lines()[0].content == "    return eval(x)"


def test_staged_only(repo: Path) -> None:
    (repo / "app.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    git(repo, "add", "app.py")
    (repo / "other.py").write_text("x = 1\n", encoding="utf-8")
    _, _, diff = local_diff(repo, "staged")
    assert [f.path for f in parse_diff(diff)] == ["app.py"]


def test_branch_mode(repo: Path) -> None:
    git(repo, "checkout", "-qb", "feature")
    (repo / "feat.py").write_text("y = 2\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "feat")
    _, desc, diff = local_diff(repo, "branch", base="main")
    assert "vs main" in desc
    assert [f.path for f in parse_diff(diff)] == ["feat.py"]
    _, desc, _ = local_diff(repo, "branch")  # auto-detects main
    assert "main" in desc


def test_repository_config_cannot_execute_commands(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker.as_posix()}'\ncat \"$1\"\n", encoding="utf-8")
    script.chmod(0o755)
    evil = script.as_posix()
    (repo / ".gitattributes").write_text("*.py diff=evil\n", encoding="utf-8")
    git(repo, "config", "diff.evil.textconv", evil)
    git(repo, "config", "diff.evil.command", evil)
    git(repo, "config", "diff.external", evil)
    git(repo, "config", "core.fsmonitor", evil)
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-qm", "attrs")
    (repo / "app.py").write_text("def f():\n    return 3\n", encoding="utf-8")
    # The helper's own plain `git add/commit` above may trigger the hooks; only codeview's calls count.
    marker.unlink(missing_ok=True)
    _, _, diff = local_diff(repo, "working")
    local_diff(repo, "staged")
    assert "return 3" in diff
    assert not marker.exists()
    # Sanity check that the trap is armed: a plain `git diff` in this repo does run it.
    git(repo, "diff", "HEAD")
    assert marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_untracked_symlinks_are_not_followed(repo: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET\n", encoding="utf-8")
    (repo / "link.txt").symlink_to(secret)
    _, _, diff = local_diff(repo, "working")
    assert "TOP SECRET" not in diff


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "-p", "a..b", "main;rm", "$(id)", "a b", "ref.lock", "x//y", ""])
def test_validate_ref_rejects(ref: str) -> None:
    with pytest.raises(GitError):
        validate_ref(ref)


@pytest.mark.parametrize("ref", ["main", "origin/main", "release/1.2", "HEAD~3", "v2.0.0", "abc123^"])
def test_validate_ref_accepts(ref: str) -> None:
    assert validate_ref(ref) == ref


def test_not_a_repo(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        local_diff(tmp_path, "working")
    with pytest.raises(GitError, match="not a directory"):
        local_diff(tmp_path / "missing", "working")


def test_unborn_head(tmp_path: Path) -> None:
    r = tmp_path / "fresh"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(r, "add", "a.py")
    _, _, diff = local_diff(r, "working")
    assert "a.py" in diff
