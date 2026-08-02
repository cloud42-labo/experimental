from pathlib import Path

import pytest

from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.router import EventRouter, RouteResult
from adp_orchestrator.service import OrchestrationService


class RecordingTaskRepository:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))


class FailsOnceTaskRepository(RecordingTaskRepository):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("temporary adapter failure")
        super().record(event, result)


class FailsNextTaskRepository(RecordingTaskRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("temporary terminal adapter failure")
        super().record(event, result)


class RecordingAgentActivator:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))


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


def service(tmp_path: Path) -> tuple[
    OrchestrationService, RecordingTaskRepository, RecordingAgentActivator
]:
    task_repository = RecordingTaskRepository()
    agent_activator = RecordingAgentActivator()
    subject = OrchestrationService(
        router=EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3")),
        task_repository=task_repository,
        agent_activator=agent_activator,
    )
    return subject, task_repository, agent_activator


def test_assignment_records_task_and_enqueues_agent(tmp_path: Path) -> None:
    subject, tasks, agents = service(tmp_path)
    result = subject.handle(make_event())
    assert result.kind == "accepted"
    assert len(tasks.records) == 1
    assert len(agents.records) == 1


def test_duplicate_has_no_external_side_effects(tmp_path: Path) -> None:
    subject, tasks, agents = service(tmp_path)
    event = make_event()
    subject.handle(event)
    result = subject.handle(event)
    assert result.kind == "ignored"
    assert len(tasks.records) == 1
    assert len(agents.records) == 1


def test_human_request_is_recorded_but_never_auto_activated(tmp_path: Path) -> None:
    subject, tasks, agents = service(tmp_path)
    result = subject.handle(
        make_event(
            event_type="human_required",
            status="blocked",
            to_agent="human",
            requires_human=True,
        )
    )
    assert result.kind == "human_required"
    assert len(tasks.records) == 1
    assert agents.records == []


def test_start_adapter_failure_allows_same_event_to_retry(tmp_path: Path) -> None:
    tasks = FailsOnceTaskRepository()
    agents = RecordingAgentActivator()
    subject = OrchestrationService(
        router=EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3")),
        task_repository=tasks,
        agent_activator=agents,
    )
    event = make_event(event_type="work_started", status="running")

    with pytest.raises(RuntimeError):
        subject.handle(event)

    result = subject.handle(event)
    assert result.kind == "accepted"
    assert result.status == "running"
    assert len(tasks.records) == 1


def test_terminal_adapter_failure_keeps_run_and_allows_exact_retry(
    tmp_path: Path,
) -> None:
    tasks = FailsNextTaskRepository()
    agents = RecordingAgentActivator()
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    subject = OrchestrationService(
        router=EventRouter(store),
        task_repository=tasks,
        agent_activator=agents,
    )
    started = make_event(event_type="work_started", status="running")
    subject.handle(started)

    completed = make_event(
        event_id="complete-1",
        from_agent="claude",
        to_agent="chris",
        event_type="work_completed",
        status="done",
    )
    tasks.fail_next = True
    with pytest.raises(RuntimeError):
        subject.handle(completed)

    lock_after_failure = store.current_lock("ADP-012")
    assert lock_after_failure is not None
    assert lock_after_failure.run_id == completed.run_id
    assert lock_after_failure.terminal_event_id is None

    result = subject.handle(completed)
    assert result.kind == "accepted"
    reserved_lock = store.current_lock("ADP-012")
    assert reserved_lock is not None
    assert reserved_lock.terminal_event_id == completed.event_id

    subject.finalize(completed, result)
    assert store.current_lock("ADP-012") is None


def test_stale_terminal_conflict_has_no_external_side_effects(
    tmp_path: Path,
) -> None:
    subject, tasks, agents = service(tmp_path)
    subject.handle(make_event(event_type="work_started", status="running"))
    tasks.records.clear()
    agents.records.clear()

    result = subject.handle(
        make_event(
            event_id="late-complete",
            from_agent="gemini",
            to_agent="chris",
            event_type="work_completed",
            status="done",
        )
    )

    assert result.kind == "conflict"
    assert tasks.records == []
    assert agents.records == []


def test_heartbeat_renews_lease_without_external_side_effects(
    tmp_path: Path,
) -> None:
    subject, tasks, agents = service(tmp_path)
    subject.handle(make_event(event_type="work_started", status="running"))
    tasks.records.clear()
    agents.records.clear()

    result = subject.handle(
        make_event(
            event_id="heartbeat-1",
            from_agent="claude",
            to_agent="chris",
            event_type="work_heartbeat",
            status="running",
        )
    )

    assert result.kind == "accepted"
    assert result.status == "running"
    assert tasks.records == []
    assert agents.records == []
