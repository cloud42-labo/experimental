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


def test_failed_event_releases_owned_task_for_retry(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(make_event(event_type="work_started", status="running"))
    failed = subject.route(
        make_event(
            event_id="event-2",
            from_agent="claude",
            to_agent="chris",
            event_type="failed",
            status="blocked",
            attempt=1,
        )
    )
    retry = make_event(
        event_id="event-3",
        event_type="work_started",
        status="running",
        to_agent="gemini",
        attempt=2,
    )

    result = subject.route(retry)

    assert failed.kind == "accepted"
    assert result.kind == "accepted"
    assert result.target_agent == "gemini"


def test_same_correlation_reaches_attempt_three_escalation(tmp_path: Path) -> None:
    subject = router(tmp_path)

    for attempt, agent in [(1, "claude"), (2, "gemini")]:
        subject.route(
            make_event(
                event_id=f"start-{attempt}",
                event_type="work_started",
                status="running",
                to_agent=agent,
                attempt=attempt,
            )
        )
        result = subject.route(
            make_event(
                event_id=f"fail-{attempt}",
                from_agent=agent,
                to_agent="chris",
                event_type="failed",
                status="blocked",
                attempt=attempt,
            )
        )
        assert result.kind == "accepted"

    subject.route(
        make_event(
            event_id="start-3",
            event_type="work_started",
            status="running",
            to_agent="claude",
            attempt=3,
        )
    )
    result = subject.route(
        make_event(
            event_id="fail-3",
            from_agent="claude",
            to_agent="chris",
            event_type="failed",
            status="blocked",
            attempt=3,
            max_attempts=3,
        )
    )

    assert result.kind == "human_required"
    assert result.status == "blocked"
    assert result.target_agent == "human"


def test_stale_completion_cannot_release_new_agent_lock(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(make_event(event_type="work_started", status="running"))
    subject.route(
        make_event(
            event_id="fail-1",
            from_agent="claude",
            to_agent="chris",
            event_type="failed",
            status="blocked",
        )
    )
    subject.route(
        make_event(
            event_id="start-2",
            event_type="work_started",
            status="running",
            to_agent="gemini",
            attempt=2,
        )
    )

    stale = subject.route(
        make_event(
            event_id="late-complete",
            from_agent="claude",
            to_agent="chris",
            event_type="work_completed",
            status="done",
            attempt=1,
        )
    )
    third_start = subject.route(
        make_event(
            event_id="start-3",
            event_type="work_started",
            status="running",
            to_agent="codex",
            attempt=3,
        )
    )

    assert stale.kind == "conflict"
    assert stale.target_agent == "gemini"
    assert third_start.kind == "conflict"
    assert third_start.target_agent == "gemini"


def test_human_request_from_controller_does_not_unlock_worker(tmp_path: Path) -> None:
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

    assert resumed.kind == "conflict"
    assert resumed.target_agent == "claude"
