# Configuration

| Env-Var / Keyring | Default | Description |
|-------------------|---------|-------------|
| `GH_TOKEN` | — | Fine-grained GitHub PAT used by PyGitHub |
| `OPENAI_API_KEY` | — | Groq key (or OpenAI key) |
| `OPENAI_BASE_URL` | — | e.g. `https://api.groq.com/openai/v1` |
| `CODEVIEW_LOCAL_TIMEOUT` | 45 s | Max wait for local Ollama LLM |
| `RG_RISK_THRESHOLD` | 0.6 | Used by `reviewgenie check` & CI job |

### `.reviewgenie.yml` (optional)

```yaml
style: security
max_comments: 10
risk_threshold: 0.7
