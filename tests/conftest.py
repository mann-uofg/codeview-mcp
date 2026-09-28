from __future__ import annotations

import textwrap

import pytest

_ENV_VARS = [
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "CODEVIEW_API_KEY",
    "CODEVIEW_BASE_URL",
    "CODEVIEW_MODEL",
    "CODEVIEW_PROVIDER",
    "CODEVIEW_OLLAMA",
    "OLLAMA_HOST",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_API_URL",
    "GITHUB_SERVER_URL",
    "GITHUB_STEP_SUMMARY",
]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Every test starts with no credentials, no gh CLI lookup and a private cache directory."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CODEVIEW_NO_GH_CLI", "1")
    monkeypatch.setenv("CODEVIEW_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))


def make_diff(
    path: str, added: list[str], *, start: int = 1, context: list[str] | None = None, new_file: bool = False
) -> str:
    """Build a small git-style diff that adds ``added`` lines to ``path``."""
    context = context or []
    body = [f" {c}" for c in context] + [f"+{a}" for a in added]
    old_len = len(context)
    new_len = len(context) + len(added)
    header = f"diff --git a/{path} b/{path}\n"
    if new_file:
        header += f"new file mode 100644\n--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{new_len} @@\n"
    else:
        header += f"--- a/{path}\n+++ b/{path}\n@@ -{start},{old_len} +{start},{new_len} @@ def f():\n"
    return header + "\n".join(body) + "\n"


SAMPLE_DIFF = textwrap.dedent(
    """\
    diff --git a/app/db.py b/app/db.py
    index 1111111..2222222 100644
    --- a/app/db.py
    +++ b/app/db.py
    @@ -10,5 +10,8 @@ def get_user(conn, user_id):
         cur = conn.cursor()
    -    cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    +    cur.execute(f"SELECT id FROM users WHERE id = {user_id}")
    +    row = cur.fetchone()
    +    if row == None:
    +        return None
         return cur.fetchone()


    diff --git a/README.md b/README.md
    --- a/README.md
    +++ b/README.md
    @@ -1,2 +1,2 @@
    -# Old
    +# New
     text
    diff --git a/package-lock.json b/package-lock.json
    --- a/package-lock.json
    +++ b/package-lock.json
    @@ -1 +1 @@
    -{"a": 1}
    +{"a": 2}
    """
)
