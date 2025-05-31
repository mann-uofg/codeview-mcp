# Changelog

All notable changes, organized by development day.

## Day 0 – Project skeleton
- Initialized repository and Python package layout  
- Added MCP “hello” example to verify SDK wiring

## Day 1 – GitHub ingest + diff cache
- Implemented `ingest_pr` tool using PyGitHub and `unidiff`  
- Added SQLite caching (24 h TTL) for PR diffs and stats

## Day 2 – LLM analysis & risk scoring
- Created local LLM smells stage with CodeLlama-13B (Ollama)  
- Integrated cloud LLM (Groq Llama-3 8K) for summary and risk score  
- Exposed `analyze_pr` tool

## Day 3 – Inline locator & embeddings
- Built `locate` util that maps static rule “smells” to file hunks  
- Added ChromaDB-backed hunk embeddings to improve line-number accuracy  
- Wrapped all GitHub calls to avoid duplicate requests

## Day 4 – CLI & CI risk gate
- Developed `reviewgenie` CLI with subcommands: `ping`, `ingest`, `analyze`, `inline`, `check`  
- Added `check` tool to fail CI when `risk_score > threshold`  
- Updated GitHub Actions CI workflow to run `pytest` + risk gate

## Day 5 – Stub test generator
- Implemented `generate_tests` tool to draft pytest stubs and open a PR  
- Created branch, added files, and submitted pull request via PyGitHub

## Day 6 – Stability fixes & CI passing
- Fixed Duplicate-ID bug in Chroma upsert logic  
- Corrected review-comment arg order for PyGitHub  
- Finalized CI so all tests pass (`ping`, `ingest`, `analyze`, `inline`, `check`)

## Day 7 – Evaluation & benchmarks
- Added `bench.py` to replay 10 historical PRs  
- Measures latency (ingest/analyze/inline) and accepted-comment counts  
- Produces `bench/benchmarks.md` with per-PR stats and averages  
- Introduced `--dry-run` for inline to avoid write errors

## Day 8 – Secrets, back-off, tracing
- Moved secrets to `codeview_mcp/secret.py` (env-vars or OS keyring)  
- Wrapped all GitHub API calls in `gh_call()` with exponential back-off  
- Instrumented tools with OpenTelemetry spans via `@traced`

## Day 9 – Full docs & schema
- Published complete `docs/` suite: Architecture, Quickstart, Usage, Config, Contributing, API schema  
- Added `scripts/export_schema.py` to generate `docs/API_SCHEMA.json`  
- Polished `README.md` and finalized changelog entries

## [1.3.0] – 2025-05-31
### Changed
* Switched Groq default model from `llama3-8b-8192` → `llama-3.1-8b-instant`
* Added `RG_CLOUD_MODEL` env-var to override at runtime
