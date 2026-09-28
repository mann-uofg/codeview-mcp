"""GitHub REST access: pull request metadata, diffs, base-branch config and review publishing."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from codeview import __version__

log = logging.getLogger(__name__)

MAX_DIFF_BYTES = 8 * 1024 * 1024
REVIEW_MARKER = "<!-- codeview -->"
_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_REPO = r"[A-Za-z0-9._-]{1,100}"
_SHORT_RE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repo>{_REPO})#(?P<number>\d{{1,9}})$")
_PATH_RE = re.compile(rf"^/(?P<owner>{_OWNER})/(?P<repo>{_REPO})/pulls?/(?P<number>\d{{1,9}})(?:/[\w./-]*)?$")


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class PRRef:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass(slots=True)
class PullRequest:
    ref: PRRef
    title: str
    body: str
    author: str
    state: str
    draft: bool
    html_url: str
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    additions: int
    deletions: int
    changed_files: int


def web_host() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return (urlsplit(server).hostname or "github.com").lower()


def api_base() -> str:
    url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if urlsplit(url).scheme != "https":
        raise GitHubError("GITHUB_API_URL must use https")
    return url


def parse_pr_ref(value: str) -> PRRef:
    """Parse a PR URL (or ``owner/repo#123``) strictly; anything else is rejected.

    Only the configured GitHub host is accepted, so a crafted URL can never redirect requests
    (and the token) to another server.
    """
    text = (value or "").strip()
    if m := _SHORT_RE.match(text):
        return _ref(m)
    if text.startswith(web_host() + "/"):
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in {web_host(), f"www.{web_host()}"}:
        raise ValueError(f"not a pull request URL on {web_host()}: {value!r}")
    if parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("pull request URL must not contain credentials or a custom port")
    m = _PATH_RE.match(parts.path.rstrip("/"))
    if not m:
        raise ValueError(f"not a pull request URL: {value!r} (expected https://{web_host()}/OWNER/REPO/pull/NUMBER)")
    return _ref(m)


def _ref(m: re.Match[str]) -> PRRef:
    repo = m.group("repo")
    if repo in {".", ".."} or repo.endswith(".git"):
        repo = repo.removesuffix(".git")
        if repo in {"", ".", ".."}:
            raise ValueError("invalid repository name")
    number = int(m.group("number"))
    if number < 1:
        raise ValueError("invalid pull request number")
    return PRRef(m.group("owner"), repo, number)


def resolve_token() -> str | None:
    for env in ("GITHUB_TOKEN", "GH_TOKEN"):
        if token := os.environ.get(env, "").strip():
            return token
    gh = shutil.which("gh")
    if gh and os.environ.get("CODEVIEW_NO_GH_CLI") is None:
        try:
            out = subprocess.run(  # nosec B603
                [gh, "auth", "token", "--hostname", web_host()],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            token = out.stdout.strip()
            if out.returncode == 0 and token:
                return token
        except (OSError, subprocess.SubprocessError):
            pass
    return None


_CODE_RE = re.compile(r"(```.*?(?:```|$)|`[^`\n]*`)", re.S)


def neutralize_mentions(text: str) -> str:
    """Stop generated text from pinging users/teams or closing issues when posted to GitHub.

    Code spans and fenced blocks are left untouched: GitHub doesn't act on mentions there, and
    rewriting them would corrupt suggested code such as ``@decorator`` lines.
    """
    parts = _CODE_RE.split(text)
    for i in range(0, len(parts), 2):  # even indexes are prose, odd are code
        prose = re.sub(r"(?<![\w`])@(?=[A-Za-z0-9][\w-]*)", "@\u200b", parts[i])
        parts[i] = re.sub(r"(?i)\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)(\s+)#(\d+)", "\\1\\2#\u200b\\3", prose)
    return "".join(parts)


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.token = token if token is not None else resolve_token()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"codeview/{__version__}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._http = httpx.AsyncClient(
            base_url=api_base(), headers=headers, timeout=timeout, transport=transport, follow_redirects=True
        )

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            resp = await self._http.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise GitHubError(self._describe(resp), resp.status_code)
        return resp

    def _describe(self, resp: httpx.Response) -> str:
        try:
            msg = resp.json().get("message", "")
        except ValueError:
            msg = resp.text[:200]
        hint = ""
        if resp.status_code == 401:
            hint = " (token invalid or expired)"
        elif resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
            hint = " (rate limited; set GITHUB_TOKEN for higher limits)" if not self.token else " (rate limited)"
        elif resp.status_code == 404 and not self.token:
            hint = " (check the URL; if the repository is private, set GITHUB_TOKEN)"
        return f"GitHub API {resp.status_code}: {msg}{hint}"

    @staticmethod
    def _repo_path(ref: PRRef) -> str:
        return f"/repos/{quote(ref.owner, safe='')}/{quote(ref.repo, safe='')}"

    async def get_pull(self, ref: PRRef) -> PullRequest:
        data = (await self._request("GET", f"{self._repo_path(ref)}/pulls/{ref.number}")).json()
        return PullRequest(
            ref=ref,
            title=data.get("title") or "",
            body=data.get("body") or "",
            author=(data.get("user") or {}).get("login", ""),
            state="merged" if data.get("merged") else data.get("state", ""),
            draft=bool(data.get("draft")),
            html_url=data.get("html_url", ""),
            base_ref=data["base"]["ref"],
            base_sha=data["base"]["sha"],
            head_ref=data["head"]["ref"],
            head_sha=data["head"]["sha"],
            additions=int(data.get("additions") or 0),
            deletions=int(data.get("deletions") or 0),
            changed_files=int(data.get("changed_files") or 0),
        )

    async def get_diff(self, ref: PRRef) -> str:
        url = f"{self._repo_path(ref)}/pulls/{ref.number}"
        try:
            async with self._http.stream("GET", url, headers={"Accept": "application/vnd.github.diff"}) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise GitHubError(self._describe(resp), resp.status_code)
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_DIFF_BYTES:
                        raise GitHubError("diff is larger than 8 MB; review it in smaller pieces", 413)
                return buf.decode("utf-8", errors="replace")
        except GitHubError as exc:
            if exc.status in (406, 422):  # "diff too large" -> assemble from the files API
                return await self._diff_from_files(ref)
            raise
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed ({type(exc).__name__})") from exc

    async def _diff_from_files(self, ref: PRRef) -> str:
        parts: list[str] = []
        size = 0
        for page in range(1, 31):  # the API returns at most 3000 files
            resp = await self._request(
                "GET",
                f"{self._repo_path(ref)}/pulls/{ref.number}/files",
                params={"per_page": 100, "page": page},
            )
            items = resp.json()
            for item in items:
                name, patch = item.get("filename", ""), item.get("patch")
                old = item.get("previous_filename") or name
                status = item.get("status")
                header = f"diff --git a/{old} b/{name}\n"
                if status == "added":
                    header += f"new file mode 100644\n--- /dev/null\n+++ b/{name}\n"
                elif status == "removed":
                    header += f"deleted file mode 100644\n--- a/{old}\n+++ /dev/null\n"
                else:
                    header += f"--- a/{old}\n+++ b/{name}\n"
                block = header + (patch + "\n" if patch else "Binary files differ\n")
                size += len(block)
                if size > MAX_DIFF_BYTES:
                    return "".join(parts)
                parts.append(block)
            if len(items) < 100:
                break
        return "".join(parts)

    async def get_file(self, ref: PRRef, path: str, git_ref: str) -> str | None:
        url = f"{self._repo_path(ref)}/contents/{quote(path)}"
        try:
            resp = await self._request(
                "GET", url, params={"ref": git_ref}, headers={"Accept": "application/vnd.github.raw+json"}
            )
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        if len(resp.content) > 256 * 1024:
            return None
        return resp.text

    async def existing_comment_keys(self, ref: PRRef) -> set[str]:
        """Fingerprints of inline comments codeview already posted, to avoid duplicates on re-runs."""
        keys: set[str] = set()
        for page in range(1, 11):
            resp = await self._request(
                "GET",
                f"{self._repo_path(ref)}/pulls/{ref.number}/comments",
                params={"per_page": 100, "page": page},
            )
            items = resp.json()
            for c in items:
                body = c.get("body") or ""
                if REVIEW_MARKER in body:
                    m = re.search(r"<!-- cv:(\S+) -->", body)
                    if m:
                        keys.add(m.group(1))
            if len(items) < 100:
                break
        return keys

    async def create_review(
        self, ref: PRRef, *, commit_id: str, body: str, event: str, comments: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"commit_id": commit_id, "body": body, "event": event}
        if comments:
            payload["comments"] = comments
        url = f"{self._repo_path(ref)}/pulls/{ref.number}/reviews"
        while True:
            try:
                return dict((await self._request("POST", url, json=payload)).json())
            except GitHubError as exc:
                if exc.status != 422:
                    raise
                if payload.get("event") != "COMMENT":
                    # Authors cannot request changes on / approve their own PR: downgrade to a comment.
                    log.warning("review event %s rejected (%s); retrying as COMMENT", payload["event"], exc)
                    payload["event"] = "COMMENT"
                elif "comments" in payload:
                    # A line could not be resolved (e.g. new commits were pushed). Post the summary only.
                    log.warning("inline comments rejected (%s); posting summary only", exc)
                    payload.pop("comments")
                else:
                    raise
