import threading
import time
from pathlib import Path

from adp_orchestrator.app import DeferredDeliveryScheduler
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import RouteResult


class ActiveRuntime:
    def ensure_active(self) -> None:
        return None


class RecordingService:
    def __init__(self) -> None:
        self.calls = 0
        self.finalized = threading.Event()

    def handle(self, event: HandoffEvent) -> RouteResult:
        self.calls += 1
        return RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status="ready",
            message="Recovered",
            target_agent=event.to_agent,
        )

    def ensure_delivery(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result
        self.finalized.set()

    def rollback(self, event: HandoffEvent) -> None:
        del event


class RecordingClient:
    def chat_postMessage(self, **kwargs: object) -> None:
        del kwargs


def settings(tmp_path: Path) -> Settings:
    return Settings(
        slack_bot_token="xoxb-valid-placeholder",
        slack_app_token="xapp-valid-placeholder",
        adp_control_channel_id="C_CONTROL",
        adp_human_requests_channel_id="C_HUMAN",
        adp_daily_channel_id="C_DAILY",
        adp_db_path=tmp_path / "orchestrator.sqlite3",
    )


def event() -> HandoffEvent:
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


def wait_until(predicate: object, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.01)
    return bool(predicate())  # type: ignore[operator]


def test_active_listener_prevents_outbox_from_processing_same_event(
    tmp_path: Path,
) -> None:
    outbox = DeferredDeliveryOutbox(tmp_path / "orchestrator.sqlite3")
    service = RecordingService()
    subject = DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        settings=settings(tmp_path),
        client=RecordingClient(),
        outbox=outbox,
        retry_seconds=0.01,
        poll_seconds=0.01,
        claim_seconds=0.05,
    )
    subject.start()
    handoff = event()

    subject.defer(
        handoff=handoff,
        channel="C_CONTROL",
        thread_ts="123.45",
        mark_active=True,
    )
    time.sleep(0.1)

    assert service.calls == 0
    assert outbox.count() == 1

    subject.finish_direct(handoff.idempotency_key, delivered=False)
    assert service.finalized.wait(timeout=1.0) is True
    assert wait_until(lambda: outbox.count() == 0) is True
    subject.stop()


def test_successful_direct_delivery_removes_persisted_event(
    tmp_path: Path,
) -> None:
    outbox = DeferredDeliveryOutbox(tmp_path / "orchestrator.sqlite3")
    subject = DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=RecordingService(),  # type: ignore[arg-type]
        settings=settings(tmp_path),
        client=RecordingClient(),
        outbox=outbox,
        retry_seconds=60,
    )
    handoff = event()

    subject.defer(
        handoff=handoff,
        channel="C_CONTROL",
        thread_ts="123.45",
        mark_active=True,
    )
    subject.finish_direct(handoff.idempotency_key, delivered=True)

    assert outbox.count() == 0
