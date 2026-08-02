import threading
import time
from pathlib import Path

from adp_orchestrator.adapters import NoopAgentActivator, NoopTaskRepository
from adp_orchestrator.app import DeferredDeliveryScheduler
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import EventRouter
from adp_orchestrator.service import OrchestrationService


class ActiveRuntime:
    def ensure_active(self) -> None:
        return None


class RecordingClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.sent = threading.Event()

    def chat_postMessage(self, **kwargs: object) -> None:
        self.messages.append(kwargs)
        self.sent.set()


def settings(tmp_path: Path) -> Settings:
    return Settings(
        slack_bot_token="xoxb-valid-placeholder",
        slack_app_token="xapp-valid-placeholder",
        adp_control_channel_id="C_CONTROL",
        adp_human_requests_channel_id="C_HUMAN",
        adp_daily_channel_id="C_DAILY",
        adp_db_path=tmp_path / "orchestrator.sqlite3",
    )


def start_event(*, event_id: str, attempt: int, agent: str) -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": event_id,
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "chris",
            "to_agent": agent,
            "event_type": "work_started",
            "status": "running",
            "summary": f"Start attempt {attempt}",
            "attempt": attempt,
            "max_attempts": 3,
        }
    )


def completed_event() -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "complete-1",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "claude",
            "to_agent": "chris",
            "event_type": "work_completed",
            "status": "done",
            "summary": "Completed attempt 1",
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def wait_until(predicate: object, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.01)
    return bool(predicate())  # type: ignore[operator]


def test_transient_start_conflict_stays_queued_until_lock_is_released(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path)
    owner = "runtime-test"
    store.register_runtime(owner, 60)
    router = EventRouter(store, delivery_owner_id=owner)
    service = OrchestrationService(
        router=router,
        task_repository=NoopTaskRepository(),
        agent_activator=NoopAgentActivator(),
    )
    first = start_event(event_id="start-1", attempt=1, agent="claude")
    queued = start_event(event_id="start-2", attempt=2, agent="gemini")
    assert router.route(first).kind == "accepted"

    outbox = DeferredDeliveryOutbox(db_path)
    outbox.defer(
        idempotency_key=queued.idempotency_key,
        event_json=queued.model_dump_json(),
        channel_id="C_CONTROL",
        thread_ts="123.45",
        delay_seconds=0.001,
    )
    client = RecordingClient()
    scheduler = DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=service,
        settings=settings(tmp_path),
        client=client,
        outbox=outbox,
        retry_seconds=0.02,
        poll_seconds=0.01,
        claim_seconds=0.05,
    )
    scheduler.start()

    time.sleep(0.1)
    assert outbox.count() == 1
    assert client.messages == []

    assert store.release_task("ADP-012", "claude", first.run_id) is True
    assert client.sent.wait(timeout=1.0) is True
    assert wait_until(lambda: outbox.count() == 0) is True
    scheduler.stop()

    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.agent == "gemini"
    assert lock.run_id == queued.run_id


def test_start_replay_does_not_restore_running_after_terminal_selection(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    owner = "runtime-test"
    store.register_runtime(owner, 60)
    router = EventRouter(store, delivery_owner_id=owner)
    started = start_event(event_id="start-1", attempt=1, agent="claude")
    completed = completed_event()

    assert router.route(started).kind == "accepted"
    assert router.route(completed).kind == "accepted"
    router.rollback(completed)

    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.terminal_event_id is None

    replay = router.replay_claimed(started)
    assert replay.kind == "accepted"
    assert replay.status == "running"
    assert replay.apply_external_side_effects is False
