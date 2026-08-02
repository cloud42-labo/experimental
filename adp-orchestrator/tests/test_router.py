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


def start_event(
    *,
    event_id: str,
    attempt: int,
    agent: str,
) -> HandoffEvent:
    return make_event(
        event_id=event_id,
        event_type="work_started",
        status="running",
        to_agent=agent,
        attempt=attempt,
    )


def terminal_event(
    *,
    event_id: str,
    attempt: int,
    agent: str,
    event_type: str,
    status: str,
) -> HandoffEvent:
    return make_event(
        event_id=event_id,
        from_agent=agent,
        to_agent="chris",
        event_type=event_type,
        status=status,
        attempt=attempt,
    )


def test_duplicate_event_is_ignored(tmp_path: Path) -> None:
    subject = router(tmp_path)
    event = make_event()
    assert subject.route(event).kind == "accepted"
    assert subject.route(event).kind == "ignored"


def test_assignment_does_not_block_work_started(tmp_path: Path) -> None:
    subject = router(tmp_path)
    assert subject.route(make_event()).status == "ready"
    result = subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    assert result.kind == "accepted"
    assert result.status == "running"
    assert result.target_agent == "claude"


def test_same_agent_different_attempt_is_a_lock_conflict(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    result = subject.route(start_event(event_id="start-2", attempt=2, agent="claude"))
    assert result.kind == "conflict"
    assert result.target_agent == "claude"


def test_start_conflict_releases_claim_for_exact_retry(tmp_path: Path) -> None:
    subject = router(tmp_path)
    first_start = start_event(event_id="start-1", attempt=1, agent="claude")
    second_start = start_event(event_id="start-2", attempt=2, agent="gemini")
    subject.route(first_start)

    conflict = subject.route(second_start)
    assert conflict.kind == "conflict"

    completed = terminal_event(
        event_id="complete-1",
        attempt=1,
        agent="claude",
        event_type="work_completed",
        status="done",
    )
    assert subject.route(completed).kind == "accepted"

    retry = subject.route(second_start)
    assert retry.kind == "accepted"
    assert retry.target_agent == "gemini"


def test_failed_event_releases_exact_run_for_retry(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    failed = subject.route(
        terminal_event(
            event_id="fail-1",
            attempt=1,
            agent="claude",
            event_type="failed",
            status="blocked",
        )
    )
    retry = subject.route(start_event(event_id="start-2", attempt=2, agent="gemini"))
    assert failed.kind == "accepted"
    assert retry.kind == "accepted"
    assert retry.target_agent == "gemini"


def test_same_correlation_reaches_attempt_three_escalation(tmp_path: Path) -> None:
    subject = router(tmp_path)
    for attempt, agent in [(1, "claude"), (2, "gemini")]:
        subject.route(start_event(event_id=f"start-{attempt}", attempt=attempt, agent=agent))
        result = subject.route(
            terminal_event(
                event_id=f"fail-{attempt}",
                attempt=attempt,
                agent=agent,
                event_type="failed",
                status="blocked",
            )
        )
        assert result.kind == "accepted"

    subject.route(start_event(event_id="start-3", attempt=3, agent="claude"))
    result = subject.route(
        terminal_event(
            event_id="fail-3",
            attempt=3,
            agent="claude",
            event_type="failed",
            status="blocked",
        )
    )
    assert result.kind == "human_required"
    assert result.target_agent == "human"


def test_stale_same_agent_completion_cannot_release_new_attempt(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    subject.route(
        terminal_event(
            event_id="fail-1",
            attempt=1,
            agent="claude",
            event_type="failed",
            status="blocked",
        )
    )
    subject.route(start_event(event_id="start-2", attempt=2, agent="claude"))

    stale = subject.route(
        terminal_event(
            event_id="late-complete-1",
            attempt=1,
            agent="claude",
            event_type="work_completed",
            status="done",
        )
    )
    third = subject.route(start_event(event_id="start-3", attempt=3, agent="gemini"))

    assert stale.kind == "conflict"
    assert stale.target_agent == "claude"
    assert third.kind == "conflict"
    assert third.target_agent == "claude"


def test_heartbeat_renews_exact_run_and_allows_multiple_events(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))

    first = subject.route(
        make_event(
            event_id="heartbeat-1",
            from_agent="claude",
            to_agent="chris",
            event_type="work_heartbeat",
            status="running",
            attempt=1,
        )
    )
    second = subject.route(
        make_event(
            event_id="heartbeat-2",
            from_agent="claude",
            to_agent="chris",
            event_type="work_heartbeat",
            status="running",
            attempt=1,
        )
    )

    assert first.kind == "accepted"
    assert second.kind == "accepted"
    assert first.status == second.status == "running"


def test_stale_heartbeat_is_rejected(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-2", attempt=2, agent="claude"))
    stale = subject.route(
        make_event(
            event_id="heartbeat-1",
            from_agent="claude",
            to_agent="chris",
            event_type="work_heartbeat",
            status="running",
            attempt=1,
        )
    )
    assert stale.kind == "conflict"
    assert stale.target_agent == "claude"


def test_stale_worker_human_request_has_no_effect(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    subject.route(
        terminal_event(
            event_id="fail-1",
            attempt=1,
            agent="claude",
            event_type="failed",
            status="blocked",
        )
    )
    subject.route(start_event(event_id="start-2", attempt=2, agent="gemini"))

    stale = subject.route(
        make_event(
            event_id="human-1",
            from_agent="claude",
            to_agent="human",
            event_type="human_required",
            status="blocked",
            requires_human=True,
            attempt=1,
        )
    )
    assert stale.kind == "conflict"
    assert stale.target_agent == "gemini"


def test_current_worker_human_request_releases_exact_run(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    result = subject.route(
        make_event(
            event_id="human-1",
            from_agent="claude",
            to_agent="human",
            event_type="human_required",
            status="blocked",
            requires_human=True,
            attempt=1,
        )
    )
    assert result.kind == "human_required"
    resumed = subject.route(start_event(event_id="start-2", attempt=2, agent="gemini"))
    assert resumed.kind == "accepted"


def test_controller_human_request_does_not_unlock_worker(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    result = subject.route(
        make_event(
            event_id="controller-human",
            correlation_id="controller-correlation",
            event_type="human_required",
            status="blocked",
            to_agent="human",
            requires_human=True,
        )
    )
    assert result.kind == "human_required"
    resumed = subject.route(start_event(event_id="start-2", attempt=2, agent="gemini"))
    assert resumed.kind == "conflict"
    assert resumed.target_agent == "claude"
