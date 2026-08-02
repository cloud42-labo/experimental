import json
import traceback
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from adp_orchestrator.app import extract_event_payload
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.github_adapter import (
    GitHubAdapterConfig,
    GitHubAdapterError,
    GitHubReferenceClient,
)
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.router import EventRouter


def make_event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "event-1",
        "task_id": "ADP-012",
        "correlation_id": "correlation-1",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Implement the MVP",
        "requires_human": False,
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def test_terminal_event_conflicts_when_exact_release_loses_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    first_start = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    next_start = make_event(
        event_id="start-2",
        event_type="work_started",
        status="running",
        to_agent="gemini",
        attempt=2,
    )
    assert subject.route(first_start).kind == "accepted"

    original_release = subject.store.release_task

    def lose_release_race(
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> bool:
        assert original_release(task_id, expected_agent, expected_run_id)
        assert subject.store.acquire_task(task_id, "gemini", next_start.run_id)
        return False

    monkeypatch.setattr(subject.store, "release_task", lose_release_race)
    completion = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )

    result = subject.route(completion)

    assert result.kind == "conflict"
    assert result.status == "running"
    assert result.target_agent == "gemini"


def test_wrong_worker_does_not_claim_real_owners_terminal_event(
    tmp_path: Path,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    start = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    assert subject.route(start).kind == "accepted"

    wrong_owner = make_event(
        event_id="wrong-complete",
        from_agent="gemini",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )
    real_owner = make_event(
        event_id="real-complete",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )

    assert subject.route(wrong_owner).kind == "conflict"
    assert subject.route(real_owner).kind == "accepted"


def test_terminal_rollback_cannot_restore_run_after_successor_completed(
    tmp_path: Path,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    first_start = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    first_complete = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )
    second_start = make_event(
        event_id="start-2",
        event_type="work_started",
        status="running",
        to_agent="gemini",
        attempt=2,
    )
    second_complete = make_event(
        event_id="complete-2",
        from_agent="gemini",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=2,
    )
    third_start = make_event(
        event_id="start-3",
        event_type="work_started",
        status="running",
        to_agent="codex",
        attempt=3,
    )

    assert subject.route(first_start).kind == "accepted"
    assert subject.route(first_complete).kind == "accepted"
    assert subject.route(second_start).kind == "accepted"
    assert subject.route(second_complete).kind == "accepted"

    subject.rollback(first_complete)

    result = subject.route(third_start)
    assert result.kind == "accepted"
    assert result.target_agent == "codex"


def test_fenced_json_keeps_closing_braces_inside_strings() -> None:
    payload = {
        "event_id": "event-1",
        "summary": "Example code: if x: return {}",
    }
    text = f"<@U123ABC> ```json\n{json.dumps(payload)}\n```"

    assert extract_event_payload(text) == payload


def test_github_transport_error_does_not_expose_secret() -> None:
    secret = "github_transport_secret_do_not_leak"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"connection failed with {secret}",
            request=request,
        )

    client = GitHubReferenceClient(
        GitHubAdapterConfig(token=SecretStr(secret)),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(GitHubAdapterError) as exc_info:
        client.fetch("https://github.com/cloud42-labo/experimental/pull/57")

    error_text = str(exc_info.value)
    rendered_traceback = "".join(
        traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb)
    )
    assert error_text == "GitHub reference fetch transport failed"
    assert secret not in error_text
    assert secret not in rendered_traceback
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
