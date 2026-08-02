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


def test_adapter_failure_allows_same_event_to_retry(tmp_path: Path) -> None:
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
