# Changelog

## 2.0.0 (2026-09-28)

Rewrite from scratch.

- MCP server rebuilt on version 2 of the official MCP Python SDK. Tools return structured results, and there are
  prompts and resources. It runs over stdio or Streamable HTTP (localhost only).
- New tools: review a PR, review local changes (working tree, staged or branch), review a raw diff, fetch a
  line-numbered PR diff, and post a review to GitHub. Posting is a dry run by default, and re-runs don't duplicate comments.
- The AI pass works with free-tier providers (Gemini, Groq, Cerebras, OpenRouter) or a local Ollama model, falls back
  between them, and caches responses.
- 48 regex rules for secrets, injection, unsafe deserialization, TLS and crypto misuse, XSS, SSRF, GitHub Actions
  workflow issues and common bugs.
- A risk score from 0 to 100 that lists the factors behind it.
- Text, Markdown, JSON and SARIF output.
- GitHub Action in the repo root.
- `.codeview.toml` configuration. For PR reviews it is read from the base branch.
- Hardening against prompt injection, malicious git config in reviewed repos, and token leakage.
- Removed: ChromaDB embeddings, keyring, OpenTelemetry tracing, the stub test generator and the benchmark script.

Breaking changes from 1.x:

- The package is now `codeview`, and so is the command. Install it from GitHub.
- `codeview check <url>` is replaced by `codeview review <url> --fail-on high`.
- AI keys use each provider's own variable (`GEMINI_API_KEY`, `GROQ_API_KEY`, ...) instead of
  `OPENAI_API_KEY`/`OPENAI_BASE_URL`. `GITHUB_TOKEN` is preferred, though `GH_TOKEN` still works.

## 1.3.0 (2025)

Last version of the original implementation.
