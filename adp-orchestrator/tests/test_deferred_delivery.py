import threading
from pathlib import Path

from adp_orchestrator.app import DeferredDeliveryScheduler
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
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

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result
        self.finalized.set()

    def rollback(self, event: HandoffEvent) -> None:
        self.rolled_back.append(event)


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


def test_deferred_redelivery_is_retained_and_retried_automatically(
    tmp_path: Path,
) -> None:
    service = DeferredThenAcceptedService()
    client = RecordingClient()
    scheduler = DeferredDeliveryScheduler(
        runtime=ActiveRuntime(),  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        settings=settings(tmp_path),
        retry_seconds=0.01,
    )
    event = terminal_event()

    assert scheduler.schedule(
        handoff=event,
        channel="C_CONTROL",
        thread_ts="123.45",
        client=client,
    ) is True
    assert scheduler.schedule(
        handoff=event,
        channel="C_CONTROL",
        thread_ts="123.45",
        client=client,
    ) is False

    assert service.finalized.wait(timeout=1.0) is True
    scheduler.stop()

    assert service.calls == 2
    assert service.rolled_back == []
    assert len(client.messages) == 1
    assert client.messages[0]["channel"] == "C_CONTROL"
    assert client.messages[0]["thread_ts"] == "123.45"
    assert "Recovered delivery accepted" in str(client.messages[0]["text"])
