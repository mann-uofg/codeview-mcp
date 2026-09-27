"""Minimal async client for OpenAI-compatible ``/chat/completions`` endpoints."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
from urllib.parse import urlsplit

import httpx

from reviewgenie import __version__
from reviewgenie.llm.providers import Provider, resolve_base_url

log = logging.getLogger(__name__)

_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "host.docker.internal"}


class LLMError(RuntimeError):
    """Raised when a provider cannot produce a completion. Messages never include credentials."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _check_url(url: str, provider: Provider) -> str:
    if not url:
        raise LLMError(f"{provider.name}: no base URL configured (set RG_BASE_URL)")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise LLMError(f"{provider.name}: invalid base URL")
    if parts.scheme == "http" and parts.hostname not in _LOCAL_HOSTS and not parts.hostname.endswith(".local"):
        # Never send an API key in clear text over the network.
        raise LLMError(f"{provider.name}: refusing plain-http endpoint {parts.hostname}; use https")
    return url.rstrip("/")


class ChatClient:
    def __init__(
        self,
        provider: Provider,
        model: str,
        *,
        timeout: float = 120.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.max_retries = max_retries
        self._base = _check_url(resolve_base_url(provider), provider)
        headers = {"User-Agent": f"reviewgenie/{__version__}", "Content-Type": "application/json"}
        key = provider.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        elif not provider.local and provider.name != "openai-compatible":
            raise LLMError(f"{provider.name}: missing API key (set {' or '.join(provider.key_envs)})")
        if provider.name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/mann-uofg/codeview-mcp"
            headers["X-Title"] = "ReviewGenie"
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers=headers,
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> ChatClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        json_mode: bool = True,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        use_json = json_mode and self.provider.json_mode
        if use_json:
            payload["response_format"] = {"type": "json_object"}

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await self._http.post(f"{self._base}/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                err = LLMError(f"{self.provider.name}: request timed out", retryable=True)
                if attempt > self.max_retries:
                    raise err from exc
                await asyncio.sleep(self._backoff(attempt, None))
                continue
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"{self.provider.name}: connection failed ({type(exc).__name__})", retryable=True
                ) from exc

            if resp.status_code == 400 and use_json and "response_format" in payload:
                # Some models reject JSON mode; retry once without it (the prompt still asks for JSON).
                payload.pop("response_format")
                continue
            if resp.status_code in _RETRY_STATUS and attempt <= self.max_retries:
                delay = self._backoff(attempt, resp.headers.get("retry-after"))
                log.info("%s returned %s; retrying in %.1fs", self.provider.name, resp.status_code, delay)
                await asyncio.sleep(delay)
                continue
            if resp.status_code >= 400:
                hint = ""
                if self.provider.local and resp.status_code == 404:
                    hint = f" (run `ollama pull {self.model}` or set RG_MODEL to an installed model)"
                raise LLMError(
                    f"{self.provider.name}: HTTP {resp.status_code}: {_error_text(resp)}{hint}",
                    retryable=resp.status_code in _RETRY_STATUS or resp.status_code in {401, 403, 404},
                )
            return _extract_content(resp, self.provider.name)

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(60.0, max(0.5, float(retry_after)))
            except ValueError:
                pass
        return min(30.0, float(2 ** (attempt - 1)) + random.uniform(0, 0.5))  # noqa: S311  # nosec B311


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = resp.text
    return (msg or "").strip().replace("\n", " ")[:300]


def _extract_content(resp: httpx.Response, name: str) -> str:
    try:
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"].get("content")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"{name}: unexpected response shape") from exc
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not content:
        raise LLMError(f"{name}: empty completion (finish_reason={choice.get('finish_reason')})", retryable=True)
    return str(content)
