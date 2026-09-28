from __future__ import annotations

import textwrap

from codeview.diff import is_noise, language_for, matches_any, parse_diff, render_for_model
from conftest import SAMPLE_DIFF, make_diff


def test_parses_files_hunks_and_line_numbers() -> None:
    files = parse_diff(SAMPLE_DIFF)
    assert [f.path for f in files] == ["app/db.py", "README.md", "package-lock.json"]
    db = files[0]
    assert db.status == "modified"
    assert db.additions == 4
    assert db.deletions == 1
    assert db.language == "python"
    added = db.added_lines()
    assert [ln.new_no for ln in added] == [11, 12, 13, 14]
    assert added[0].content.strip().startswith('cur.execute(f"SELECT')
    # Context lines keep both numbers; removed lines only the old one.
    assert db.hunks[0].lines[0].old_no == 10
    assert db.hunks[0].lines[0].new_no == 10
    removed = [ln for ln in db.hunks[0].lines if ln.kind == "-"][0]
    assert removed.new_no is None
    assert removed.old_no == 11
    assert db.hunks[0].header == "def get_user(conn, user_id):"
    assert 15 in db.new_line_numbers()
    assert db.changed_line_numbers() == {11, 12, 13, 14}


def test_wrong_hunk_counts_do_not_swallow_the_next_file() -> None:
    lines = [
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1,9 +1,9 @@",
        "-x",
        "+y",
        "diff --git a/b.py b/b.py",
        "--- a/b.py",
        "+++ b/b.py",
        "@@ -1 +1 @@",
        "-p",
        "+q",
    ]
    files = parse_diff("\n".join(lines) + "\n")
    assert [f.path for f in files] == ["a.py", "b.py"]
    assert files[1].additions == 1


def test_new_deleted_renamed_and_binary() -> None:
    text = textwrap.dedent(
        """\
        diff --git a/new.py b/new.py
        new file mode 100644
        index 0000000..e69de29
        --- /dev/null
        +++ b/new.py
        @@ -0,0 +1,2 @@
        +a = 1
        +b = 2
        diff --git a/gone.py b/gone.py
        deleted file mode 100644
        --- a/gone.py
        +++ /dev/null
        @@ -1 +0,0 @@
        -x = 1
        diff --git a/old/name.py b/new/name.py
        similarity index 90%
        rename from old/name.py
        rename to new/name.py
        --- a/old/name.py
        +++ b/new/name.py
        @@ -1 +1 @@
        -v = 1
        +v = 2
        diff --git a/logo.png b/logo.png
        Binary files a/logo.png and b/logo.png differ
        """
    )
    files = {f.path: f for f in parse_diff(text)}
    assert files["new.py"].status == "added"
    assert [ln.new_no for ln in files["new.py"].added_lines()] == [1, 2]
    assert files["gone.py"].status == "deleted"
    assert files["new/name.py"].status == "renamed"
    assert files["new/name.py"].old_path == "old/name.py"
    assert files["logo.png"].is_binary


def test_hunk_lines_starting_with_dashes_are_content_not_headers() -> None:
    # A removed line "-- comment" looks like a "---" header; the parser must count hunk lines.
    text = "--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n--- old comment\n+-- new comment\n select 1;\n"
    [f] = parse_diff(text)
    assert f.path == "q.sql"
    assert f.deletions == 1
    assert f.additions == 1
    assert f.added_lines()[0].content == "-- new comment"


def test_no_newline_marker_and_plain_diff_without_git_header() -> None:
    text = "--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n"
    [f] = parse_diff(text)
    assert f.additions == 1
    assert f.deletions == 1


def test_quoted_paths_with_unicode() -> None:
    text = 'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n@@ -1 +1 @@\n-a\n+b\n'
    [f] = parse_diff(text)
    assert f.path == "café.py"


def test_garbage_input_yields_nothing() -> None:
    assert parse_diff("hello world\nnot a diff") == []
    assert parse_diff("") == []


def test_language_and_noise_detection() -> None:
    assert language_for("src/app.tsx") == "typescript"
    assert language_for("Dockerfile.prod") == "dockerfile"
    assert language_for("notes.unknown") is None
    assert is_noise("frontend/package-lock.json")
    assert is_noise("static/app.min.js")
    assert is_noise("web/node_modules/x/index.js")
    assert not is_noise("src/app.py")
    assert matches_any("docs/guide/intro.md", ["docs/**"])


def test_render_for_model_numbers_lines_and_respects_budget() -> None:
    files = parse_diff(SAMPLE_DIFF)
    text, included, truncated = render_for_model(files, 10_000)
    assert not truncated
    assert "### app/db.py (modified)" in text
    assert "   11 + " in text
    assert "      - " in text  # removed lines carry no number
    assert set(included) == {"app/db.py", "README.md", "package-lock.json"}

    big = make_diff("big.py", [f"x{i} = {i}" for i in range(2000)])
    small = make_diff("small.py", ["y = 1"])
    text, included, truncated = render_for_model(parse_diff(big + small), 3_000)
    assert truncated
    assert "small.py" in included
    assert len(text) <= 3_500
