# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-09-27

A ground-up rewrite. The package is now published on PyPI as **`reviewgenie`**.

### Added
- MCP server on the official MCP Python SDK 2.x with structured outputs, tool annotations, prompts and
  resources; stdio and Streamable HTTP (localhost-only, DNS-rebinding protection) transports.
- Tools: `review_pull_request`, `review_local_changes`, `review_diff_text`, `get_pull_request_diff`,
  `post_review` (dry run by default, de-duplicated re-runs), `list_rules`, `provider_status`.
- Free AI providers with automatic fallback: Gemini, Groq, Cerebras, OpenRouter free models, local Ollama,
  or any OpenAI-compatible endpoint. Budgets sized to each free tier; responses cached locally.
- 45+ static rules: secrets (redacted), injection, unsafe deserialization, TLS/crypto misuse, XSS,
  SSRF, path traversal, GitHub Actions supply-chain issues, common bugs and leftovers; inline suppressions.
- Explainable 0-100 risk score with visible factors.
- Local reviews: working tree (including untracked files), staged changes, or branch vs base.
- Output formats: rich terminal, Markdown, JSON, SARIF 2.1.0; GitHub job summary.
- GitHub Action (`uses: mann-uofg/codeview-mcp@v2`) posting a single review with inline comments,
  SARIF output and risk/verdict outputs.
- `.reviewgenie.toml` / `[tool.reviewgenie]` configuration with custom rules and team instructions,
  read from the PR's base branch for PR reviews.
- Security hardening against prompt injection, hostile git configuration, SSRF and token leakage.

### Changed
- PyPI name `reviewgenie-mcp` → `reviewgenie`; import package `codeview_mcp` → `reviewgenie`.
- Environment variables: `GH_TOKEN` still works; `GITHUB_TOKEN` is preferred. AI keys use each
  provider's own variable (`GEMINI_API_KEY`, `GROQ_API_KEY`, …) instead of `OPENAI_API_KEY`/`OPENAI_BASE_URL`.
- The CLI is now `reviewgenie review <target>`; `check` is replaced by `--fail-on` / `--max-risk`.

### Removed
- ChromaDB/embedding-based comment placement (findings are now anchored to exact diff lines),
  the keyring dependency, OpenTelemetry console tracing, the stub test generator and the benchmark script.

### Migration from 1.x
```bash
pip uninstall reviewgenie-mcp && pip install reviewgenie
reviewgenie review https://github.com/OWNER/REPO/pull/N --fail-on high   # was: reviewgenie check <url>
```

## [1.3.0] - 2025
- Last release of the original `reviewgenie-mcp` package.
