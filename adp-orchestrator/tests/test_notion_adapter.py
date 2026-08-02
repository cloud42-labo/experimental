import json

import httpx
import pytest
from pydantic import SecretStr

from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.notion_adapter import (
    NotionAdapterConfig,
    NotionAdapterError,
    NotionTaskRepository,
    page_id_from_url,
)
from adp_orchestrator.router import RouteResult

_PAGE_ID = "3b0fbd826f3b81f9bf00dcac663cf86e"
_PAGE_URL = f"https://app.notion.com/p/{_PAGE_ID}"


def event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "event-1",
        "task_id": "ADP-012-D",
        "correlation_id": "correlation-1",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "work_started",
        "status": "running",
        "summary": "Implement the adapter",
        "notion_url": _PAGE_URL,
        "requires_human": False,
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def config(token: str = "secret_test_token") -> NotionAdapterConfig:
    return NotionAdapterConfig(token=SecretStr(token))


def success_repository(
    captured: list[httpx.Request] | None = None,
) -> NotionTaskRepository:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(200, json={"object": "page"})

    return NotionTaskRepository(
        config(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_extracts_page_id_from_notion_url() -> None:
    assert page_id_from_url(_PAGE_URL) == _PAGE_ID


def test_invalid_page_url_raises_safe_error() -> None:
    with pytest.raises(NotionAdapterError):
        page_id_from_url("https://app.notion.com/p/not-a-page-id")


def test_updates_select_and_rich_text_properties() -> None:
    captured: list[httpx.Request] = []
    repository = success_repository(captured)
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012-D",
        status="running",
        message="work_started accepted",
        target_agent="claude",
    )

    repository.record(event(), result)

    request = captured[0]
    assert request.url.path == f"/v1/pages/{_PAGE_ID}"
    assert request.headers["notion-version"] == "2026-03-11"
    assert request.headers["authorization"] == "Bearer secret_test_token"
    properties = json.loads(request.content)["properties"]
    assert properties["Status"] == {"select": {"name": "In Progress"}}
    assert properties["Assigned Agent"] == {
        "select": {"name": "Claude Opus"}
    }
    assert properties["Result"]["rich_text"][0]["text"]["content"] == (
        "work_started accepted"
    )
    assert properties["Blocker"] == {"rich_text": []}
    assert properties["Environment Help"] == {"checkbox": False}


def test_codex_assignment_updates_assigned_agent() -> None:
    captured: list[httpx.Request] = []
    repository = success_repository(captured)
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012-D",
        status="review",
        message="review requested",
        target_agent="codex",
    )

    repository.record(
        event(
            event_type="review_requested",
            status="review",
            to_agent="codex",
        ),
        result,
    )

    properties = json.loads(captured[0].content)["properties"]
    assert properties["Assigned Agent"] == {"select": {"name": "Codex"}}


def test_human_request_sets_blocker_and_environment_help() -> None:
    captured: list[httpx.Request] = []
    repository = success_repository(captured)
    result = RouteResult(
        kind="human_required",
        task_id="ADP-012-D",
        status="blocked",
        message="Token setup is required",
        target_agent="human",
    )

    repository.record(
        event(
            event_type="human_required",
            status="blocked",
            to_agent="human",
            requires_human=True,
        ),
        result,
    )

    properties = json.loads(captured[0].content)["properties"]
    assert properties["Environment Help"] == {"checkbox": True}
    assert properties["Blocker"]["rich_text"][0]["text"]["content"] == (
        "Token setup is required"
    )


def test_missing_notion_url_is_rejected() -> None:
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012-D",
        status="running",
        message="started",
        target_agent="claude",
    )
    with pytest.raises(NotionAdapterError):
        success_repository().record(event(notion_url=None), result)


def test_http_error_does_not_expose_token_or_response_body() -> None:
    secret = "secret_do_not_leak"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=f"denied {secret}")

    repository = NotionTaskRepository(
        config(secret), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012-D",
        status="running",
        message="started",
        target_agent="claude",
    )

    with pytest.raises(NotionAdapterError) as exc_info:
        repository.record(event(), result)

    error_text = str(exc_info.value)
    assert "HTTP 403" in error_text
    assert secret not in error_text
    assert "denied" not in error_text


def test_transport_error_is_normalized_without_secret_details() -> None:
    secret = "proxy_secret_do_not_leak"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection failed {secret}", request=request)

    repository = NotionTaskRepository(
        config(secret), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012-D",
        status="running",
        message="started",
        target_agent="claude",
    )

    with pytest.raises(NotionAdapterError) as exc_info:
        repository.record(event(), result)

    error_text = str(exc_info.value)
    assert error_text == "Notion page update transport failed"
    assert secret not in error_text
    assert "connection failed" not in error_text
