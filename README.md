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
