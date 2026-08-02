import httpx
import pytest
from pydantic import SecretStr

from adp_orchestrator.github_adapter import (
    GitHubAdapterConfig,
    GitHubAdapterError,
    GitHubReferenceClient,
    parse_github_reference_url,
)


def test_parses_issue_url() -> None:
    parsed = parse_github_reference_url(
        "https://github.com/cloud42-labo/experimental/issues/12"
    )
    assert parsed.kind == "issue"
    assert parsed.owner == "cloud42-labo"
    assert parsed.repository == "experimental"
    assert parsed.number == 12


def test_parses_pull_request_url() -> None:
    parsed = parse_github_reference_url(
        "https://github.com/cloud42-labo/experimental/pull/57"
    )
    assert parsed.kind == "pull_request"
    assert parsed.number == 57


def test_rejects_non_issue_or_pull_url() -> None:
    with pytest.raises(GitHubAdapterError):
        parse_github_reference_url(
            "https://github.com/cloud42-labo/experimental/actions"
        )


def test_fetches_public_issue_without_authorization() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "title": "Track the MVP",
                "state": "open",
                "html_url": (
                    "https://github.com/cloud42-labo/experimental/issues/12"
                ),
            },
        )

    client = GitHubReferenceClient(
        GitHubAdapterConfig(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch(
        "https://github.com/cloud42-labo/experimental/issues/12"
    )

    assert result.kind == "issue"
    assert result.title == "Track the MVP"
    assert result.state == "open"
    request = captured[0]
    assert request.url.path == "/repos/cloud42-labo/experimental/issues/12"
    assert request.headers["x-github-api-version"] == "2026-03-10"
    assert "authorization" not in request.headers


def test_fetches_private_pull_request_with_bearer_token() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "title": "ADP Orchestrator MVP",
                "state": "open",
                "html_url": (
                    "https://github.com/cloud42-labo/experimental/pull/57"
                ),
                "draft": False,
                "merged": False,
                "head": {"sha": "abc123"},
                "base": {"ref": "main"},
            },
        )

    client = GitHubReferenceClient(
        GitHubAdapterConfig(token=SecretStr("github_secret_token")),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.fetch(
        "https://github.com/cloud42-labo/experimental/pull/57"
    )

    assert result.kind == "pull_request"
    assert result.draft is False
    assert result.merged is False
    assert result.head_sha == "abc123"
    assert result.base_branch == "main"
    request = captured[0]
    assert request.url.path == "/repos/cloud42-labo/experimental/pulls/57"
    assert request.headers["authorization"] == "Bearer github_secret_token"


def test_http_error_does_not_expose_token_or_body() -> None:
    secret = "github_secret_do_not_leak"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=f"not found {secret}")

    client = GitHubReferenceClient(
        GitHubAdapterConfig(token=SecretStr(secret)),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(GitHubAdapterError) as exc_info:
        client.fetch("https://github.com/cloud42-labo/experimental/pull/57")

    error_text = str(exc_info.value)
    assert "HTTP 404" in error_text
    assert secret not in error_text
    assert "not found" not in error_text


def test_missing_required_fields_is_safe() -> None:
    client = GitHubReferenceClient(
        GitHubAdapterConfig(),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"state": "open"})
            )
        ),
    )

    with pytest.raises(GitHubAdapterError) as exc_info:
        client.fetch("https://github.com/cloud42-labo/experimental/issues/12")

    assert "missing required fields" in str(exc_info.value)
