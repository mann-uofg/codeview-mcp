# CodeView MCP Server

*Day-wise build log starts tomorrow (Day 1).*

## Day 1 (2025-05-22 (delayed, supposed to be 21st))

* Added Python deps: PyGitHub, patch-ng, python-dotenv
* Implemented `server.py` with FastMCP skeleton
* Built & tested `ping` tool – returns PR metadata

## Day 2 (2025-05-22)

* Added SQLite cache (`codeview_mcp/cache/db.py`)
* `fetch_pr()` parses diff via **unidiff** and caches JSON
* New MCP tool `ingest_pr` exposed in `server.py`
* Verified on PR #6883 – 24 h cache hit works

## Day 3 (2025-05-23)

* Added `llm.py` – 2-stage review (local CodeLlama + cloud Groq)
* Built prompt builder (`utils/prompt.py`)
* New MCP tool `analyze_pr(pr_url)` returns summary, smells, risk_score

## Day 4 (2025-05-23)

* Inline comment engine – new MCP tool `inline_comments`
* YAML config loader (`.reviewgenie.yml`)
* CLI harness: `python -m codeview_mcp.cli analyze <PR_URL>`
* Added pytest smoke test

## Day 5 [0.1.0] – 2025-05-23
### Added
- `generate_tests` MCP tool opens stub-test PR
- GitHub Actions CI (pytest)
- CLI harness (`codeview_mcp.cli`)
### Fixed
- SQLite WAL to avoid 'database is locked'

## Day 6 (2025-05-24)

* Upgraded `locator.py` to semantic, embedding-driven matching via ChromaDB + OpenAI (with zero-vector fallback for tests)
* Added end-to-end integration test for `inline_comments` in `tests/test_inline.py`
* Introduced a daily-cron GitHub Actions workflow (`.github/workflows/daily.yml`) to run `reviewgenie analyze` on open PRs at 09:00 UTC
* Tagged **v0.2.0** release

## Day 7 (2025-05-24)

* Introduced **static security + quality rules** (`rules.py`) and integrated them into `llm.analyze` → each hit increases `risk_score`.
* Added new CLI/MCP command **`check`** — fails with non-zero exit when `risk_score` exceeds a configurable threshold (`RG_RISK_THRESHOLD` or `--threshold`).
* Updated GitHub Actions workflow to gate PRs with the risk check (job **reviewgenie**).
* Created `pyproject.toml`, set `__version__ = "1.0.0"`, and published the package to **Test PyPI** (`pip install --index-url https://test.pypi.org/simple reviewgenie-mcp`).
* Added PyPI badge and one-line install snippet to the README.
* Tagged and pushed **v1.0.0** – first public release!
* **Benchmarks**: added `bench/bench.py` and `bench/urls.txt` to replay 10 historical PRs  
  – Measures latency for `ingest`, `analyze`, and `inline` (dry-run) via subprocess  
  – Safely skips PRs that 404/403 or CLI errors  
  – Counts “accepted” comments and outputs `bench/benchmarks.md` with per‐PR timings and totals/averages  
* **Robustified**: 
  – `inline_comments` gained a `--dry-run` option  
  – Fixed review comment arg order and added URL sanitization  
  – Updated Chroma upsert to skip duplicate IDs  
* **Resilience**: PR fetch and subprocess invocations now wrapped to log and skip failures rather than crash  
