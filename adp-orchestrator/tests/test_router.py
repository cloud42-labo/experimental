from pathlib import Path

from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.router import EventRouter, RouteResult


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


def finalize(
    subject: EventRouter,
    event: HandoffEvent,
    result: RouteResult,
) -> None:
    subject.finalize(event, result)


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


def test_successor_waits_for_terminal_delivery_then_exact_retry_starts(
    tmp_path: Path,
) -> None:
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
    completion_result = subject.route(completed)
    assert completion_result.kind == "accepted"

    before_delivery_commit = subject.route(second_start)
    assert before_delivery_commit.kind == "conflict"

    finalize(subject, completed, completion_result)
    retry = subject.route(second_start)
    assert retry.kind == "accepted"
    assert retry.target_agent == "gemini"


def test_failed_event_releases_exact_run_only_after_finalize(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    failed_event = terminal_event(
        event_id="fail-1",
        attempt=1,
        agent="claude",
        event_type="failed",
        status="blocked",
    )
    failed = subject.route(failed_event)
    retry_event = start_event(event_id="start-2", attempt=2, agent="gemini")

    assert failed.kind == "accepted"
    assert subject.route(retry_event).kind == "conflict"

    finalize(subject, failed_event, failed)
    retry = subject.route(retry_event)
    assert retry.kind == "accepted"
    assert retry.target_agent == "gemini"


def test_same_correlation_reaches_attempt_three_escalation(tmp_path: Path) -> None:
    subject = router(tmp_path)
    for attempt, agent in [(1, "claude"), (2, "gemini")]:
        subject.route(start_event(event_id=f"start-{attempt}", attempt=attempt, agent=agent))
        failed_event = terminal_event(
            event_id=f"fail-{attempt}",
            attempt=attempt,
            agent=agent,
            event_type="failed",
            status="blocked",
        )
        result = subject.route(failed_event)
        assert result.kind == "accepted"
        finalize(subject, failed_event, result)

    subject.route(start_event(event_id="start-3", attempt=3, agent="claude"))
    failed_event = terminal_event(
        event_id="fail-3",
        attempt=3,
        agent="claude",
        event_type="failed",
        status="blocked",
    )
    result = subject.route(failed_event)
    assert result.kind == "human_required"
    assert result.target_agent == "human"
    finalize(subject, failed_event, result)


def test_stale_same_agent_completion_cannot_release_new_attempt(tmp_path: Path) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    failed_event = terminal_event(
        event_id="fail-1",
        attempt=1,
        agent="claude",
        event_type="failed",
        status="blocked",
    )
    failed_result = subject.route(failed_event)
    finalize(subject, failed_event, failed_result)
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
    failed_event = terminal_event(
        event_id="fail-1",
        attempt=1,
        agent="claude",
        event_type="failed",
        status="blocked",
    )
    failed_result = subject.route(failed_event)
    finalize(subject, failed_event, failed_result)
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


def test_current_worker_human_request_waits_for_delivery_finalize(
    tmp_path: Path,
) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    human_event = make_event(
        event_id="human-1",
        from_agent="claude",
        to_agent="human",
        event_type="human_required",
        status="blocked",
        requires_human=True,
        attempt=1,
    )
    result = subject.route(human_event)
    assert result.kind == "human_required"

    resumed_event = start_event(event_id="start-2", attempt=2, agent="gemini")
    assert subject.route(resumed_event).kind == "conflict"

    finalize(subject, human_event, result)
    resumed = subject.route(resumed_event)
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


def test_terminal_delivery_rollback_keeps_run_and_allows_exact_retry(
    tmp_path: Path,
) -> None:
    subject = router(tmp_path)
    subject.route(start_event(event_id="start-1", attempt=1, agent="claude"))
    completed = terminal_event(
        event_id="complete-1",
        attempt=1,
        agent="claude",
        event_type="work_completed",
        status="done",
    )
    first_result = subject.route(completed)
    assert first_result.kind == "accepted"

    successor = start_event(event_id="start-2", attempt=2, agent="gemini")
    assert subject.route(successor).kind == "conflict"

    subject.rollback(completed)
    lock = subject.store.current_lock("ADP-012")
    assert lock is not None
    assert lock.run_id == completed.run_id
    assert lock.terminal_event_id is None

    retry_result = subject.route(completed)
    assert retry_result.kind == "accepted"
    finalize(subject, completed, retry_result)
    assert subject.route(successor).kind == "accepted"


def test_late_start_delivery_rollback_cannot_resurrect_completed_run(
    tmp_path: Path,
) -> None:
    subject = router(tmp_path)
    started = start_event(event_id="start-1", attempt=1, agent="claude")
    assert subject.route(started).kind == "accepted"

    completed = terminal_event(
        event_id="complete-1",
        attempt=1,
        agent="claude",
        event_type="work_completed",
        status="done",
    )
    completion_result = subject.route(completed)
    assert completion_result.kind == "accepted"

    subject.rollback(started)
    finalize(subject, completed, completion_result)

    assert subject.route(started).kind == "ignored"
    assert subject.store.current_lock("ADP-012") is None
