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
    real_result = subject.route(real_owner)
    assert real_result.kind == "accepted"
    subject.finalize(real_owner, real_result)


def test_late_start_rollback_retains_claim_after_terminal_reservation(
    tmp_path: Path,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    started = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    completed = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )

    assert subject.route(started).kind == "accepted"
    completed_result = subject.route(completed)
    assert completed_result.kind == "accepted"

    subject.rollback(started)
    subject.finalize(completed, completed_result)

    assert subject.route(started).kind == "ignored"
    assert subject.store.current_lock("ADP-012") is None


def test_terminal_delivery_failure_blocks_successor_and_remains_retryable(
    tmp_path: Path,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    started = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    completed = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )
    successor = make_event(
        event_id="start-2",
        event_type="work_started",
        status="running",
        to_agent="gemini",
        attempt=2,
    )

    assert subject.route(started).kind == "accepted"
    assert subject.route(completed).kind == "accepted"
    assert subject.route(successor).kind == "conflict"

    subject.rollback(completed)

    lock = subject.store.current_lock("ADP-012")
    assert lock is not None
    assert lock.run_id == completed.run_id
    assert lock.terminal_event_id is None
    assert subject.route(successor).kind == "conflict"

    retry_result = subject.route(completed)
    assert retry_result.kind == "accepted"
    subject.finalize(completed, retry_result)
    assert subject.route(successor).kind == "accepted"


def test_first_terminal_reservation_rejects_contradictory_terminal(
    tmp_path: Path,
) -> None:
    subject = EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))
    started = make_event(
        event_id="start-1",
        event_type="work_started",
        status="running",
        to_agent="claude",
        attempt=1,
    )
    completed = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
        attempt=1,
    )
    failed = make_event(
        event_id="failed-1",
        from_agent="claude",
        to_agent="chris",
        event_type="failed",
        status="blocked",
        attempt=1,
    )

    assert subject.route(started).kind == "accepted"
    completed_result = subject.route(completed)
    assert completed_result.kind == "accepted"
    assert subject.route(failed).kind == "conflict"
    subject.finalize(completed, completed_result)


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
