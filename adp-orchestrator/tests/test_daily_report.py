import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adp_orchestrator.agent_queue import SQLiteAgentQueue
from adp_orchestrator.daily_report import DailyReportPublisher, DailyReportStore
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import RouteResult


class RecordingSlackClient:
    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.posts: list[dict[str, str]] = []

    def chat_postMessage(self, **kwargs: str) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary Slack failure")
        self.posts.append(kwargs)


def make_event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "daily-event",
        "task_id": "ADP-015",
        "correlation_id": "daily-correlation",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Build daily report",
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def initialize(db_path: Path) -> tuple[SQLiteAgentQueue, DeferredDeliveryOutbox]:
    outbox = DeferredDeliveryOutbox(db_path)
    queue = SQLiteAgentQueue(db_path)
    return queue, outbox


def test_jst_date_uses_tokyo_boundary(tmp_path: Path) -> None:
    store = DailyReportStore(tmp_path / "orchestrator.sqlite3")
    before_midnight_utc = datetime(2026, 8, 2, 14, 59, tzinfo=timezone.utc)
    after_midnight_utc = datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)

    assert store.jst_date(before_midnight_utc).isoformat() == "2026-08-02"
    assert store.jst_date(after_midnight_utc).isoformat() == "2026-08-03"


def test_report_contains_agent_outbox_and_safe_task_summaries(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    queue, outbox = initialize(db_path)
    event = make_event()
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C0CONTROL",
        thread_ts="123.456",
        delay_seconds=60,
    )
    queue.enqueue(
        event,
        RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status="ready",
            message="queued",
            target_agent="claude",
        ),
    )
    claimed = queue.claim_next("claude")
    assert claimed is not None
    queue.complete(claimed.idempotency_key)

    report = DailyReportStore(db_path).build(
        DailyReportStore.jst_date(
            datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc)
        )
    )

    assert "ADP Daily Report — 2026-08-03 JST" in report.text
    assert "Claude:.*" not in report.text
    assert "*Claude:* pending 0 / claimed 0 / completed 1" in report.text
    assert "*Outbox retries:* 1" in report.text
    assert "`ADP-015` → claude" in report.text
    assert event.summary not in report.text


def test_same_jst_date_is_posted_only_once(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    initialize(db_path)
    client = RecordingSlackClient()
    publisher = DailyReportPublisher(DailyReportStore(db_path), client, "C0DAILY")
    now = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)

    assert publisher.publish(now) is True
    assert publisher.publish(now) is False
    assert len(client.posts) == 1
    assert client.posts[0]["channel"] == "C0DAILY"


def test_failed_slack_delivery_is_retryable_without_duplicate_success(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    initialize(db_path)
    client = RecordingSlackClient(fail_once=True)
    publisher = DailyReportPublisher(DailyReportStore(db_path), client, "C0DAILY")
    now = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="temporary Slack failure"):
        publisher.publish(now)

    assert publisher.publish(now) is True
    assert publisher.publish(now) is False
    assert len(client.posts) == 1
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, attempts, last_error FROM daily_report_deliveries"
        ).fetchone()
    assert row == ("sent", 2, None)


def test_human_request_count_uses_event_flags_without_printing_body(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    _, outbox = initialize(db_path)
    event = make_event(
        event_id="human-event",
        correlation_id="human-correlation",
        to_agent="human",
        event_type="human_required",
        status="blocked",
        summary="SECRET DETAILS MUST NOT APPEAR",
        requires_human=True,
    )
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C0CONTROL",
        thread_ts=None,
        delay_seconds=60,
    )

    report = DailyReportStore(db_path).build(
        DailyReportStore.jst_date(
            datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
        )
    )

    assert "*Human Requests:* 1" in report.text
    assert "SECRET DETAILS MUST NOT APPEAR" not in report.text
