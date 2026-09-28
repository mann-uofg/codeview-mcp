"""Free-tier, OpenAI-compatible LLM providers.

Every provider here can be used at no cost: either through a free API tier or by running the
model locally with Ollama. Defaults can be overridden with ``CODEVIEW_MODEL`` / ``model =``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    label: str
    base_url: str
    key_envs: tuple[str, ...]
    default_model: str
    budget_chars: int
    """Approximate maximum diff characters to send, sized to the free tier's per-minute token limit."""
    signup_url: str
    local: bool = False
    json_mode: bool = True

    def api_key(self) -> str | None:
        for env in self.key_envs:
            if value := os.environ.get(env, "").strip():
                return value
        return None

    def is_configured(self) -> bool:
        if self.local:
            return os.environ.get("CODEVIEW_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"} or bool(
                os.environ.get("OLLAMA_HOST")
            )
        return self.api_key() is not None


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in [
        Provider(
            name="gemini",
            label="Google Gemini (free tier)",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            key_envs=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            default_model="gemini-3.8-flash",
            budget_chars=180_000,
            signup_url="https://aistudio.google.com/apikey",
        ),
        Provider(
            name="groq",
            label="Groq (free tier)",
            base_url="https://api.groq.com/openai/v1",
            key_envs=("GROQ_API_KEY",),
            default_model="openai/gpt-oss-120b",
            budget_chars=18_000,  # free tier: 8K tokens/minute including the response
            signup_url="https://console.groq.com/keys",
        ),
        Provider(
            name="cerebras",
            label="Cerebras (free tier)",
            base_url="https://api.cerebras.ai/v1",
            key_envs=("CEREBRAS_API_KEY",),
            default_model="gpt-oss-120b",
            budget_chars=120_000,
            signup_url="https://cloud.cerebras.ai",
        ),
        Provider(
            name="openrouter",
            label="OpenRouter (free models)",
            base_url="https://openrouter.ai/api/v1",
            key_envs=("OPENROUTER_API_KEY",),
            default_model="openrouter/free",
            budget_chars=100_000,
            signup_url="https://openrouter.ai/keys",
        ),
        Provider(
            name="ollama",
            label="Ollama (local, offline)",
            base_url="http://localhost:11434/v1",
            key_envs=(),
            default_model="qwen3.8",
            budget_chars=60_000,
            signup_url="https://ollama.com/download",
            local=True,
        ),
        Provider(
            name="openai-compatible",
            label="Any OpenAI-compatible endpoint",
            base_url="",
            key_envs=("CODEVIEW_API_KEY",),
            default_model="",
            budget_chars=80_000,
            signup_url="",
        ),
    ]
}

AUTO_ORDER = ("gemini", "groq", "cerebras", "openrouter", "ollama", "openai-compatible")


def resolve_base_url(provider: Provider) -> str:
    if provider.name == "ollama":
        host = os.environ.get("OLLAMA_HOST", "").strip()
        if host:
            host = host if host.startswith(("http://", "https://")) else f"http://{host}"
            return host.rstrip("/") + "/v1"
    if provider.name == "openai-compatible":
        return os.environ.get("CODEVIEW_BASE_URL", "").strip().rstrip("/")
    return provider.base_url


def custom_endpoint_configured() -> bool:
    return bool(os.environ.get("CODEVIEW_BASE_URL", "").strip() and os.environ.get("CODEVIEW_MODEL", "").strip())


def candidate_providers(name: str) -> list[Provider]:
    """Providers to try, in order. ``auto`` returns every configured provider (for fallback)."""
    name = (name or "auto").strip().lower()
    if name in {"none", "off", "false"}:
        return []
    if name != "auto":
        if name not in PROVIDERS:
            raise ValueError(f"unknown provider {name!r}; choose one of: auto, none, {', '.join(PROVIDERS)}")
        return [PROVIDERS[name]]
    out: list[Provider] = []
    for pname in AUTO_ORDER:
        p = PROVIDERS[pname]
        if pname == "openai-compatible":
            if custom_endpoint_configured():
                out.append(p)
        elif p.is_configured():
            out.append(p)
    return out
