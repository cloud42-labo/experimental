from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import SecretStr

_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/(?:issues|pull)/(?P<number>[1-9][0-9]*)/?$"
)


class GitHubAdapterError(RuntimeError):
    """Safe GitHub integration error without token or response body leakage."""


@dataclass(frozen=True)
class GitHubAdapterConfig:
    token: SecretStr | None = None
    api_version: str = "2026-03-10"
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class GitHubReference:
    kind: Literal["issue", "pull_request"]
    owner: str
    repository: str
    number: int
    title: str
    state: str
    html_url: str
    draft: bool | None = None
    merged: bool | None = None
    head_sha: str | None = None
    base_branch: str | None = None


@dataclass(frozen=True)
class ParsedGitHubUrl:
    kind: Literal["issue", "pull_request"]
    owner: str
    repository: str
    number: int


def parse_github_reference_url(url: str) -> ParsedGitHubUrl:
    match = _GITHUB_URL_PATTERN.fullmatch(url.strip())
    if match is None:
        raise GitHubAdapterError("GitHub URL must point to one issue or pull request")
    kind: Literal["issue", "pull_request"] = (
        "pull_request" if "/pull/" in url else "issue"
    )
    return ParsedGitHubUrl(
        kind=kind,
        owner=match.group("owner"),
        repository=match.group("repo"),
        number=int(match.group("number")),
    )


class GitHubReferenceClient:
    """Reads issue or pull-request metadata without mutating GitHub."""

    def __init__(
        self,
        config: GitHubAdapterConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch(self, url: str) -> GitHubReference:
        parsed = parse_github_reference_url(url)
        endpoint_name = "pulls" if parsed.kind == "pull_request" else "issues"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.config.api_version,
            "User-Agent": "cloud42-labo-adp-orchestrator",
        }
        if self.config.token is not None:
            headers["Authorization"] = (
                f"Bearer {self.config.token.get_secret_value()}"
            )

        try:
            response = self.client.get(
                f"{_GITHUB_API_BASE}/repos/{parsed.owner}/"
                f"{parsed.repository}/{endpoint_name}/{parsed.number}",
                headers=headers,
            )
        except httpx.RequestError:
            # Suppress the original transport exception because its traceback can
            # contain proxy credentials, URLs, or user-controlled diagnostics.
            raise GitHubAdapterError(
                "GitHub reference fetch transport failed"
            ) from None

        if response.is_error:
            raise GitHubAdapterError(
                f"GitHub reference fetch failed with HTTP {response.status_code}"
            )

        try:
            payload = response.json()
            title = str(payload["title"])
            state = str(payload["state"])
            html_url = str(payload["html_url"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubAdapterError("GitHub response is missing required fields") from exc

        if parsed.kind == "issue":
            return GitHubReference(
                kind="issue",
                owner=parsed.owner,
                repository=parsed.repository,
                number=parsed.number,
                title=title,
                state=state,
                html_url=html_url,
            )

        head = payload.get("head") or {}
        base = payload.get("base") or {}
        return GitHubReference(
            kind="pull_request",
            owner=parsed.owner,
            repository=parsed.repository,
            number=parsed.number,
            title=title,
            state=state,
            html_url=html_url,
            draft=bool(payload.get("draft", False)),
            merged=bool(payload.get("merged", False)),
            head_sha=str(head["sha"]) if head.get("sha") else None,
            base_branch=str(base["ref"]) if base.get("ref") else None,
        )
