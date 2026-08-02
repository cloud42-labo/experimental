import threading
import time
from pathlib import Path

from adp_orchestrator.app import DeferredDeliveryScheduler
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import EventRouter, RouteResult
from adp_orchestrator.service import OrchestrationService


class ActiveRuntime:
    def ensure_active(self) -> None:
        return None


class RecordingTaskRepository:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []
        self.recorded = threading.Event()

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))
        self.recorded.set()


class RecordingAgentActivator:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))


class RecordingClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def chat_postMessage(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        slack_bot_token="xoxb-valid-placeholder",
        slack_app_token="xapp-valid-placeholder",
        adp_control_channel_id="C_CONTROL",
        adp_human_requests_channel_id="C_HUMAN",
        adp_daily_channel_id="C_DAILY",
        adp_db_path=tmp_path / "orchestrator.sqlite3",
    )


def assignment() -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "assigned-1",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "chris",
            "to_agent": "claude",
            "event_type": "task_assigned",
            "status": "ready",
            "summary": "Assign work",
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def work_started() -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "started-1",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "chris",
            "to_agent": "claude",
            "event_type": "work_started",
            "status": "running",
            "summary": "Start work",
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def wait_until_empty(outbox: DeferredDeliveryOutbox, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if outbox.count() == 0:
            return True
        time.sleep(0.01)
    return outbox.count() == 0


def run_claimed_recovery(
    tmp_path: Path,
    event: HandoffEvent,
) -> tuple[
    RecordingTaskRepository,
    RecordingAgentActivator,
    RecordingClient,
    DeferredDeliveryOutbox,
]:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path)
    owner = "runtime-test"
    store.register_runtime(owner, 60)
    router = EventRouter(store, delivery_owner_id=owner)

    # Simulate a process exit after the routing transaction committed but before
    # Notion, agent activation, or Slack delivery completed.
    assert router.route(event).kind == "accepted"

    outbox = DeferredDeliveryOutbox(db_path)
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C_CONTROL",
        thread_ts="123.45",
        delay_seconds=0.001,
    )

    tasks = RecordingTaskRepository()
    agents = RecordingAgentActivator()
    client = RecordingClient()
    service = OrchestrationService(
        router=router,
        task_repository=tasks,
        agent_activator=agents,
    )
    scheduler = DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=service,
        settings=settings(tmp_path),
        client=client,
        outbox=outbox,
        retry_seconds=0.01,
        poll_seconds=0.01,
        claim_seconds=0.05,
    )
    scheduler.start()

    assert tasks.recorded.wait(timeout=1.0) is True
    assert wait_until_empty(outbox) is True
    scheduler.stop()
    return tasks, agents, client, outbox


def test_claimed_assignment_outbox_replays_unfinished_side_effects(
    tmp_path: Path,
) -> None:
    tasks, agents, client, outbox = run_claimed_recovery(
        tmp_path,
        assignment(),
    )

    assert len(tasks.records) == 1
    assert tasks.records[0][1].kind == "accepted"
    assert len(agents.records) == 1
    assert len(client.messages) == 1
    assert outbox.count() == 0


def test_claimed_work_started_outbox_replays_without_waiting_for_lease(
    tmp_path: Path,
) -> None:
    tasks, agents, client, outbox = run_claimed_recovery(
        tmp_path,
        work_started(),
    )

    assert len(tasks.records) == 1
    assert tasks.records[0][1].status == "running"
    assert agents.records == []
    assert len(client.messages) == 1
    assert outbox.count() == 0
