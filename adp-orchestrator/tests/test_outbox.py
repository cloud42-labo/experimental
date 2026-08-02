import sqlite3
from pathlib import Path

from adp_orchestrator.outbox import DeferredDeliveryOutbox


def available_at(db_path: Path, key: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT available_at
            FROM deferred_deliveries
            WHERE idempotency_key = ?
            """,
            (key,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_duplicate_defer_does_not_pull_claimed_schedule_forward(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    outbox = DeferredDeliveryOutbox(db_path)

    outbox.defer(
        idempotency_key="event-key",
        event_json='{"event_id":"first"}',
        channel_id="C_CONTROL",
        thread_ts="123.45",
        delay_seconds=60,
    )
    first_schedule = available_at(db_path, "event-key")

    outbox.defer(
        idempotency_key="event-key",
        event_json='{"event_id":"redelivery"}',
        channel_id="C_CONTROL",
        thread_ts="123.45",
        delay_seconds=0.001,
    )

    assert outbox.count() == 1
    assert available_at(db_path, "event-key") == first_schedule
