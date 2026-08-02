from pathlib import Path

from adp_orchestrator.events import HandoffEvent
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


def router(tmp_path: Path) -> EventRouter:
    return EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3"))


def test_duplicate_event_is_ignored(tmp_path: Path) -> None:
    subject = router(tmp_path)
    event = make_event()

    first = subject.route(event)
    second = subject.route(event)

    assert first.kind == "accepted"
    assert second.kind == "ignored"


def test_assignment_does_not_block_work_started(tmp_path: Path) -> None:
    subject = router(tmp_path)
    assignment = make_event()
    started = make_event(
        event_id="event-2",
        event_type="work_started",
        status="running",
    )

    assert subject.route(assignment).status == "ready"
    result = subject.route(started)

    assert result.kind == "accepted"
    assert result.status == "running"
    assert result.target_agent == "claude"


def test_task_cannot_run_with_two_agents(tmp_path: Path) -> None:
    subject = router(tmp_path)
    first = make_event(event_type="work_started", status="running")
    second = make_event(
        event_id="event-2",
        correlation_id="correlation-2",
        event_type="work_started",
        status="running",
        to_agent="gemini",
    )

    subject.route(first)
    result = subject.route(second)

    assert result.kind == "conflict"
    assert result.target_agent == "claude"


def test_failed_event_releases_task_for_retry(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(make_event(event_type="work_started", status="running"))
    subject.route(
        make_event(
            event_id="event-2",
            correlation_id="correlation-2",
            event_type="failed",
            status="blocked",
            attempt=1,
        )
    )
    retry = make_event(
        event_id="event-3",
        correlation_id="correlation-3",
        event_type="work_started",
        status="running",
        to_agent="gemini",
    )

    result = subject.route(retry)

    assert result.kind == "accepted"
    assert result.target_agent == "gemini"


def test_failed_event_at_attempt_limit_requires_human(tmp_path: Path) -> None:
    subject = router(tmp_path)
    event = make_event(
        event_type="failed",
        status="blocked",
        attempt=3,
        max_attempts=3,
    )

    result = subject.route(event)

    assert result.kind == "human_required"
    assert result.status == "blocked"
    assert result.target_agent == "human"


def test_explicit_human_request_releases_task(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(make_event(event_type="work_started", status="running"))
    human_event = make_event(
        event_id="event-2",
        correlation_id="correlation-2",
        event_type="human_required",
        status="blocked",
        to_agent="human",
        requires_human=True,
    )
    subject.route(human_event)

    resumed = subject.route(
        make_event(
            event_id="event-3",
            correlation_id="correlation-3",
            event_type="work_started",
            status="running",
            to_agent="gemini",
        )
    )

    assert resumed.kind == "accepted"
    assert resumed.target_agent == "gemini"
