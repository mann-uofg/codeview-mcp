# codeview

[![CI](https://github.com/mann-uofg/codeview-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/mann-uofg/codeview-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

codeview reviews code changes: GitHub pull requests, your local uncommitted work, or any diff.
It runs as an MCP server (so an editor assistant can call it), as a command-line tool, and as a GitHub Action.

Each review has two parts:

1. A set of about 50 regex rules that run on the added lines. They catch things like committed secrets,
   SQL built with string formatting, `eval`, `shell=True`, disabled TLS verification, and risky GitHub Actions workflows.
2. An optional AI pass that looks for logic bugs, edge cases and missing tests. It only uses providers with a
   free tier (Gemini, Groq, Cerebras, OpenRouter) or a local model through Ollama, so it costs nothing to run.

The output is a list of findings tied to file and line, a verdict, and a 0-100 risk score with the reasons behind it.

## Install

Requires Python 3.11+.

```bash
pip install git+https://github.com/mann-uofg/codeview-mcp
```

Or run it without installing, using [uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/mann-uofg/codeview-mcp codeview review
```

## Usage

```bash
codeview review https://github.com/psf/requests/pull/6883   # a pull request
codeview review owner/repo#123                              # short form
codeview review                                             # uncommitted changes in the current repo
codeview review --staged                                    # only staged changes
codeview review --branch --base main                        # current branch vs main
git diff HEAD~3 | codeview review --diff -                  # any diff
```

Public repositories work without a token. For private repositories, or to post reviews, set `GITHUB_TOKEN`.
If you're logged in with the `gh` CLI, its token is picked up automatically.

Other useful options:

```
-f, --format text|markdown|json|sarif
-o, --output FILE
--json-output FILE / --sarif-output FILE   write extra reports in the same run
--post [--dry-run]                         publish the review to the PR as inline comments
--fail-on high                             exit 1 if any finding is high or worse (default: high)
--max-risk 60                              exit 1 if the risk score is above 60
--no-ai                                    rules only
--provider gemini --model ...              pick the AI provider/model
--focus security                           ask the AI to concentrate on something
```

`codeview rules` lists every rule, `codeview providers` shows which AI providers are configured,
and `codeview init` writes a starter config file.

## AI providers

Set any one of these. If more than one is set, they are tried in this order, falling back when one fails
or hits its rate limit.

| Provider | Environment variable | Get a key |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| Groq | `GROQ_API_KEY` | https://console.groq.com/keys |
| Cerebras | `CEREBRAS_API_KEY` | https://cloud.cerebras.ai |
| OpenRouter (free models) | `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| Ollama (local) | `CODEVIEW_OLLAMA=1` or `OLLAMA_HOST` | https://ollama.com |
| Any OpenAI-compatible API | `CODEVIEW_BASE_URL`, `CODEVIEW_MODEL`, `CODEVIEW_API_KEY` | |

Every provider has a default model that fits its free tier. `codeview providers` shows which one it is, and
`--model` or `CODEVIEW_MODEL` overrides it. The diff is trimmed to fit each provider's limits, and responses are
cached locally, so reviewing the same diff twice doesn't use your quota again.

With no provider configured, the rules still run.

## MCP server

Add this to your MCP client's config (Cursor, Windsurf, Zed, and others use this format):

```json
{
  "mcpServers": {
    "codeview": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mann-uofg/codeview-mcp", "codeview", "serve"],
      "env": { "GEMINI_API_KEY": "...", "GITHUB_TOKEN": "..." }
    }
  }
}
```

For VS Code, put the same thing in `.vscode/mcp.json` under `"servers"` with `"type": "stdio"`.
`codeview serve --http` starts a Streamable HTTP server on `127.0.0.1:8765/mcp` instead.

Tools:

- `review_pull_request`: review a PR
- `review_local_changes`: review working tree, staged, or branch changes
- `review_diff_text`: review a diff passed as text
- `get_pull_request_diff`: PR metadata plus a line-numbered diff, for the assistant to read itself
- `post_review`: post the review to GitHub. This is a dry run unless `dry_run=false` is passed, and comments
  that were already posted are skipped.
- `list_rules`, `provider_status`

It also provides prompts (`deep_review`, `security_audit`, `suggest_tests`, `review_my_changes`) and resources
(`codeview://rules`, `codeview://providers`, `codeview://config/example`).

## GitHub Action

```yaml
name: codeview
on: pull_request

permissions:
  contents: read
  pull-requests: write     # to post the review
  security-events: write   # only needed for the SARIF upload

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: mann-uofg/codeview-mcp@v2
        with:
          gemini-api-key: ${{ secrets.GEMINI_API_KEY }}   # optional
          fail-on: critical
      - uses: github/codeql-action/upload-sarif@v4
        if: always()
        with:
          sarif_file: codeview.sarif
```

The action posts one review with a summary and inline comments, writes a job summary, and sets the outputs
`risk-score`, `risk-level`, `verdict` and `findings`. Pull requests from forks get a read-only token, so the
review isn't posted there, but the job summary and SARIF still work. All inputs are listed in [action.yml](action.yml).

## Configuration

Put a `.codeview.toml` in the repository root, or a `[tool.codeview]` table in `pyproject.toml`:

```toml
provider = "auto"
min_severity = "low"          # hide findings below this
fail_on = "high"              # or "never"
max_findings = 30
exclude = ["docs/**", "**/*.generated.ts"]
disable_rules = ["CV-QUAL-006"]
focus = ["security"]
instructions = "We use SQLAlchemy 2.x. Flag raw SQL built with string formatting."

[[custom_rules]]
id = "TEAM-001"
pattern = "print\\("
message = "Use the logger instead of print()."
severity = "low"
paths = ["src/**/*.py"]
```

To silence one line, add a `codeview-ignore` comment to it, or `cv-ignore[CV-SEC-020]` for a specific rule.

When reviewing a pull request, the config is read from the base branch rather than the PR. That way a PR
can't turn off the checks that would catch it.

## Security notes

codeview reads input that other people control, so:

- The diff and PR text are passed to the model as data, with instructions not to follow anything written in them.
  The model's answer is validated, and findings that point at files or lines not in the diff are dropped.
- Text posted to GitHub has `@mentions`, issue-closing keywords, images and HTML comments neutralized.
- Local git commands run with external diff drivers, textconv, fsmonitor and pagers turned off. Refs are validated,
  and symlinks aren't followed.
- Only PR URLs on your GitHub host are accepted. API keys are never sent over plain HTTP to non-local hosts.
- The HTTP transport only listens on localhost and checks Host/Origin headers.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

```bash
git clone https://github.com/mann-uofg/codeview-mcp
cd codeview-mcp
uv sync
uv run pytest
uv run ruff check . && uv run mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

MIT
