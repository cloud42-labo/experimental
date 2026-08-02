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


class DeferredThenAcceptedService:
    def __init__(self) -> None:
        self.calls = 0
        self.finalized = threading.Event()
        self.rolled_back: list[HandoffEvent] = []

    def handle(self, event: HandoffEvent) -> RouteResult:
        self.calls += 1
        if self.calls == 1:
            return RouteResult(
                kind="deferred",
                task_id=event.task_id,
                status="running",
                message="Waiting for prior runtime owner.",
                target_agent=event.from_agent,
            )
        return RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status="done",
            message="Recovered delivery accepted.",
            target_agent=event.to_agent,
        )

    def ensure_delivery(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result
        self.finalized.set()

    def rollback(self, event: HandoffEvent) -> None:
        self.rolled_back.append(event)


class AcceptedService(DeferredThenAcceptedService):
    def handle(self, event: HandoffEvent) -> RouteResult:
        self.calls += 1
        return RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status="done",
            message="Persisted delivery accepted.",
            target_agent=event.to_agent,
        )


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


def terminal_event() -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "complete-redelivery",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "claude",
            "to_agent": "chris",
            "event_type": "work_completed",
            "status": "done",
            "summary": "Completed",
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def scheduler(
    *,
    tmp_path: Path,
    service: DeferredThenAcceptedService,
    client: RecordingClient,
    outbox: DeferredDeliveryOutbox,
) -> DeferredDeliveryScheduler:
    return DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        settings=settings(tmp_path),
        client=client,
        outbox=outbox,
        retry_seconds=0.01,
        poll_seconds=0.01,
        claim_seconds=0.05,
    )


def wait_until_empty(outbox: DeferredDeliveryOutbox, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if outbox.count() == 0:
            return True
        time.sleep(0.01)
    return outbox.count() == 0


def test_deferred_redelivery_is_persisted_and_retried_automatically(
    tmp_path: Path,
) -> None:
    service = DeferredThenAcceptedService()
    client = RecordingClient()
    outbox = DeferredDeliveryOutbox(tmp_path / "orchestrator.sqlite3")
    subject = scheduler(
        tmp_path=tmp_path,
        service=service,
        client=client,
        outbox=outbox,
    )
    event = terminal_event()

    # Persist duplicate Slack deliveries before processing starts. They must
    # collapse to one durable row and one delivery lifecycle.
    subject.defer(
        handoff=event,
        channel="C_CONTROL",
        thread_ts="123.45",
    )
    subject.defer(
        handoff=event,
        channel="C_CONTROL",
        thread_ts="123.45",
    )
    assert outbox.count() == 1

    subject.start()
    assert service.finalized.wait(timeout=1.0) is True
    assert wait_until_empty(outbox) is True
    subject.stop()

    assert service.calls == 2
    assert service.rolled_back == []
    assert len(client.messages) == 1
    assert client.messages[0]["channel"] == "C_CONTROL"
    assert client.messages[0]["thread_ts"] == "123.45"
    assert "Recovered delivery accepted" in str(client.messages[0]["text"])


def test_new_scheduler_resumes_delivery_persisted_before_restart(
    tmp_path: Path,
) -> None:
    event = terminal_event()
    outbox = DeferredDeliveryOutbox(tmp_path / "orchestrator.sqlite3")
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C_CONTROL",
        thread_ts="123.45",
        delay_seconds=0.001,
    )

    service = AcceptedService()
    client = RecordingClient()
    replacement = scheduler(
        tmp_path=tmp_path,
        service=service,
        client=client,
        outbox=DeferredDeliveryOutbox(tmp_path / "orchestrator.sqlite3"),
    )
    replacement.start()

    assert service.finalized.wait(timeout=1.0) is True
    assert wait_until_empty(outbox) is True
    replacement.stop()

    assert service.calls == 1
    assert len(client.messages) == 1
    assert "Persisted delivery accepted" in str(client.messages[0]["text"])
