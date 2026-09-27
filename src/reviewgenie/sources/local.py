"""Local git changes: staged, working tree, or the current branch against its base."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

LocalMode = Literal["staged", "working", "branch"]

MAX_DIFF_BYTES = 8 * 1024 * 1024
MAX_UNTRACKED_BYTES = 256 * 1024
_REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/~^+-]{0,200}$")

# Hardening for repositories we don't trust: never run external diff drivers, textconv filters,
# fsmonitor hooks or pagers configured by the repository.
_SAFE_CONFIG = [
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.pager=cat",
    "-c",
    "diff.external=",
    "-c",
    "core.quotepath=false",
    "-c",
    "color.ui=false",
]
_SAFE_DIFF_FLAGS = ["--no-ext-diff", "--no-textconv", "--no-color", "-M", "--unified=3"]


class GitError(RuntimeError):
    pass


def validate_ref(ref: str) -> str:
    ref = ref.strip()
    if not _REF_RE.match(ref) or ".." in ref or "//" in ref or ref.endswith((".lock", "/", ".")):
        raise GitError(f"invalid git ref: {ref!r}")
    return ref


def _git_exe() -> str:
    exe = shutil.which("git")
    if not exe:
        raise GitError("git is not installed or not on PATH")
    return exe


def run_git(repo: Path, *args: str, max_bytes: int = MAX_DIFF_BYTES) -> str:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_EXTERNAL_DIFF": "",
    }
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    try:
        proc = subprocess.run(  # nosec B603
            [_git_exe(), *_SAFE_CONFIG, "-C", str(repo), *args],
            capture_output=True,
            timeout=60,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError("git timed out") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise GitError(f"git {args[0]} failed: {msg[-1] if msg else proc.returncode}")
    if len(proc.stdout) > max_bytes:
        raise GitError("diff is larger than 8 MB; review it in smaller pieces")
    return proc.stdout.decode("utf-8", errors="replace")


def repo_root(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise GitError(f"not a directory: {p}")
    return Path(run_git(p, "rev-parse", "--show-toplevel").strip())


def default_base(repo: Path) -> str:
    try:
        head = run_git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD").strip()
        if head:
            return head
    except GitError:
        pass
    for candidate in ("origin/main", "origin/master", "main", "master", "origin/develop", "develop"):
        try:
            run_git(repo, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
            return candidate
        except GitError:
            continue
    raise GitError("could not determine the base branch; pass base='<branch>'")


def _untracked_diff(repo: Path) -> str:
    out = run_git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    blocks: list[str] = []
    for rel in filter(None, out.split("\0")):
        raw = repo / rel
        # Never follow symlinks (checked before resolving) or read paths escaping the repository.
        if raw.is_symlink():
            continue
        path = raw.resolve()
        if not path.is_file() or repo not in path.parents:
            continue
        if path.stat().st_size > MAX_UNTRACKED_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        if not lines:
            continue
        body = "\n".join(f"+{ln}" for ln in lines)
        blocks.append(
            f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
        )
    return "".join(blocks)


def local_diff(
    path: str | Path = ".",
    mode: LocalMode = "working",
    base: str | None = None,
    include_untracked: bool = True,
) -> tuple[Path, str, str]:
    """Return ``(repo_root, description, diff_text)`` for local changes."""
    repo = repo_root(path)
    if mode == "staged":
        return repo, "staged changes", run_git(repo, "diff", "--cached", *_SAFE_DIFF_FLAGS)
    if mode == "working":
        has_head = True
        try:
            run_git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        except GitError:
            has_head = False
        diff = run_git(repo, "diff", *_SAFE_DIFF_FLAGS, "HEAD" if has_head else "--cached")
        if include_untracked:
            diff += _untracked_diff(repo)
        return repo, "uncommitted changes", diff
    if mode == "branch":
        base_ref = validate_ref(base) if base else default_base(repo)
        diff = run_git(repo, "diff", *_SAFE_DIFF_FLAGS, f"{base_ref}...HEAD", "--")
        return repo, f"branch changes vs {base_ref}", diff
    raise GitError(f"unknown mode {mode!r}; use staged, working or branch")
