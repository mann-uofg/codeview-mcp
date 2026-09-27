# Contributing

Thanks for helping make ReviewGenie better!

```bash
git clone https://github.com/mann-uofg/codeview-mcp && cd codeview-mcp
uv sync                              # creates .venv with dev tools
uv run pytest                        # all network access is mocked
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run bandit -q -r src -c pyproject.toml
```

## Adding a static rule

1. Add a `_r(...)` entry to `src/reviewgenie/rules/builtin.py` with a unique `RG-<AREA>-NNN` id,
   a precise regex, a helpful message and suggestion, and a CWE where one applies.
2. Add positive **and** negative cases to `tests/test_rules.py`. Rules must be high-signal: when in doubt,
   leave nuance to the AI pass.

## Adding an AI provider

Providers must offer a free tier (or run locally) and expose an OpenAI-compatible `/chat/completions`
endpoint. Add a `Provider` to `src/reviewgenie/llm/providers.py`, including a `budget_chars` that fits its
free-tier tokens-per-minute limit, and extend `AUTO_ORDER`.

## Pull requests

Keep changes focused, add tests, and update `CHANGELOG.md`. CI runs lint, type checks, tests on
Linux/macOS/Windows × Python 3.11–3.14, bandit and pip-audit.
