# CLI / MCP Tool Reference

| Command | Purpose | Core Args |
|---------|---------|-----------|
| **ping** | Sanity check; returns title/author/state | `pr_url` |
| **ingest** | Fetch diff JSON + cache | `pr_url` |
| **analyze** | Return summary, smells[], rule_hits[], risk_score | `pr_url` |
| **inline** | Post (or preview) inline review comments | `pr_url`, `--style`, `--dry-run` |
| **check** | Exit 1 if risk_score > threshold → CI gate | `pr_url`, `--threshold` |
| **generate_tests** | Draft stub pytest files and open a PR | `pr_url` |
| **bench.py** | Replay 10 PRs, record latency & accepted comments | — |

### Styles for `inline`

* `nitpick`   → lightweight tips  
* `security`  → highlights risky patterns, bcrypt, eval, etc.  
* `perf`      → loops, N × M scans, range copies  

Use **`--dry-run`** to measure without writing comments.

