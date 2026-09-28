"""A small, dependency-free unified diff parser.

It understands ``git diff`` output (renames, new/deleted files, binary markers, quoted paths)
as well as plain ``diff -u`` output, and keeps the new-file line number of every added or
context line so findings can be anchored precisely.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_GIT_HEADER_RE = re.compile(r'^diff --git (?P<a>"(?:[^"\\]|\\.)+"|\S+) (?P<b>"(?:[^"\\]|\\.)+"|\S+)$')

LineKind = Literal["+", "-", " "]
FileStatus = Literal["added", "deleted", "modified", "renamed"]

_LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".tf": "terraform",
    ".html": "html",
    ".htm": "html",
    ".vue": "vue",
    ".svelte": "svelte",
    ".css": "css",
    ".scss": "css",
    ".md": "markdown",
    ".dart": "dart",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
}
_NAMED_LANGUAGES = {"dockerfile": "dockerfile", "makefile": "make", "jenkinsfile": "groovy"}

# Files that are rarely worth an AI reviewer's attention.
NOISE_PATTERNS = (
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.snap",
    "*.svg",
    "dist/*",
    "build/*",
    "vendor/*",
    "node_modules/*",
    "*_pb2.py",
    "*.pb.go",
    "*.generated.*",
)


@dataclass(slots=True)
class DiffLine:
    kind: LineKind
    content: str
    old_no: int | None
    new_no: int | None


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class DiffFile:
    path: str
    old_path: str | None = None
    status: FileStatus = "modified"
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "+")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "-")

    @property
    def language(self) -> str | None:
        return language_for(self.path)

    def added_lines(self) -> list[DiffLine]:
        return [ln for h in self.hunks for ln in h.lines if ln.kind == "+"]

    def new_line_numbers(self) -> set[int]:
        """Line numbers (new side) that appear in the diff, i.e. lines that can carry a comment."""
        return {ln.new_no for h in self.hunks for ln in h.lines if ln.new_no is not None}

    def changed_line_numbers(self) -> set[int]:
        return {ln.new_no for ln in self.added_lines() if ln.new_no is not None}


def language_for(path: str) -> str | None:
    p = PurePosixPath(path)
    name = p.name.lower()
    if name in _NAMED_LANGUAGES or name.startswith("dockerfile"):
        return _NAMED_LANGUAGES.get(name, "dockerfile")
    return _LANGUAGES.get(p.suffix.lower())


def is_noise(path: str) -> bool:
    return matches_any(path, NOISE_PATTERNS)


def matches_any(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    name = PurePosixPath(path).name
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(name, pattern):
            return True
        # "dir/*" should also match nested paths like "a/dir/x".
        if pattern.endswith("/*") and f"/{pattern[:-1]}" in f"/{path}":
            return True
    return False


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        body = token[1:-1]
        raw = bytes(body, "utf-8").decode("unicode_escape").encode("latin-1")
        return raw.decode("utf-8", errors="replace")
    return token


def _strip_prefix(path: str) -> str:
    path = _unquote(path.split("\t", 1)[0].strip())
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def parse_diff(text: str) -> list[DiffFile]:
    """Parse unified diff text into :class:`DiffFile` objects. Unknown lines are ignored."""
    files: list[DiffFile] = []
    current: DiffFile | None = None
    hunk: Hunk | None = None
    old_left = new_left = 0
    old_no = new_no = 0

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1

        # Inside a hunk: consume exactly as many lines as the header promised.
        if hunk is not None and (old_left > 0 or new_left > 0) and not line.startswith("diff --git "):
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            tag = line[:1] or " "
            body = line[1:]
            if tag == "+":
                hunk.lines.append(DiffLine("+", body, None, new_no))
                new_no += 1
                new_left -= 1
                continue
            if tag == "-":
                hunk.lines.append(DiffLine("-", body, old_no, None))
                old_no += 1
                old_left -= 1
                continue
            if tag == " " or line == "":
                hunk.lines.append(DiffLine(" ", body, old_no, new_no))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
                continue
            hunk = None  # malformed: fall through and treat as a header line

        if line.startswith("\\"):
            continue

        m = _GIT_HEADER_RE.match(line)
        if m or line.startswith("diff --git "):
            a = _strip_prefix(m.group("a")) if m else line.split()[-2][2:]
            b = _strip_prefix(m.group("b")) if m else line.split()[-1][2:]
            current = DiffFile(path=b, old_path=a if a != b else None)
            files.append(current)
            hunk = None
            continue

        if line.startswith("--- ") and i < len(lines) and lines[i].startswith("+++ "):
            old = line[4:]
            new = lines[i][4:]
            i += 1
            old_path = None if old.startswith("/dev/null") else _strip_prefix(old)
            new_path = None if new.startswith("/dev/null") else _strip_prefix(new)
            if current is None or current.hunks:
                current = DiffFile(path=new_path or old_path or "unknown")
                files.append(current)
            if new_path is None:
                current.status = "deleted"
                current.path = old_path or current.path
            elif old_path is None:
                current.status = "added"
                current.path = new_path
            else:
                current.path = new_path
                if old_path != new_path:
                    current.old_path = old_path
                    current.status = "renamed"
            hunk = None
            continue

        if current is None:
            continue

        if line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.old_path = _unquote(line[len("rename from ") :])
            current.status = "renamed"
        elif line.startswith("rename to "):
            current.path = _unquote(line[len("rename to ") :])
            current.status = "renamed"
        elif line.startswith(("Binary files ", "GIT binary patch")):
            current.is_binary = True
        else:
            hm = _HUNK_RE.match(line)
            if hm:
                old_start = int(hm.group(1))
                old_len = int(hm.group(2)) if hm.group(2) is not None else 1
                new_start = int(hm.group(3))
                new_len = int(hm.group(4)) if hm.group(4) is not None else 1
                hunk = Hunk(old_start, old_len, new_start, new_len, hm.group(5).strip())
                current.hunks.append(hunk)
                old_left, new_left = old_len, new_len
                old_no, new_no = old_start, new_start

    return files


def render_for_model(files: list[DiffFile], budget_chars: int) -> tuple[str, list[str], bool]:
    """Render files as numbered diff text for an LLM, within ``budget_chars``.

    Each added or context line is prefixed with its new-file line number so the model can cite
    exact lines. Returns ``(text, included_paths, truncated)``.
    """
    chunks: list[str] = []
    included: list[str] = []
    used = 0
    truncated = False
    # Review smaller, source-code files first so large generated files don't starve the budget.
    ordered = sorted(files, key=lambda f: (f.language is None, f.additions + f.deletions))
    for f in ordered:
        if f.is_binary or not f.hunks:
            continue
        header = f"### {f.path} ({f.status}{', from ' + f.old_path if f.old_path else ''})\n"
        body: list[str] = []
        for h in f.hunks:
            body.append(f"@@ {h.header}".rstrip())
            for ln in h.lines:
                num = f"{ln.new_no:>5}" if ln.new_no is not None else "     "
                body.append(f"{num} {ln.kind} {ln.content}")
        block = header + "\n".join(body) + "\n"
        if used + len(block) > budget_chars:
            remaining = budget_chars - used - len(header)
            if remaining > 400 and not included:
                block = header + "\n".join(body)[:remaining] + "\n… (file truncated)\n"
                chunks.append(block)
                included.append(f.path)
                used += len(block)
            truncated = True
            continue
        chunks.append(block)
        included.append(f.path)
        used += len(block)
    return "\n".join(chunks), included, truncated
