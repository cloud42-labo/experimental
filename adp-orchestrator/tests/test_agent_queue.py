import sqlite3
import time
from pathlib import Path

from adp_orchestrator.agent_queue import SQLiteAgentQueue
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import RouteResult


def make_event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "event-adp-014",
        "task_id": "ADP-014",
        "correlation_id": "correlation-adp-014",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Connect the durable AI handoff queue",
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def make_result(target: str = "claude") -> RouteResult:
    return RouteResult(
        kind="accepted",
        task_id="ADP-014",
        status="ready",
        message="queued",
        target_agent=target,
    )


def test_enqueue_preserves_slack_context_and_event(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    outbox = DeferredDeliveryOutbox(db_path)
    event = make_event()
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C0CONTROL",
        thread_ts="1234.5678",
        delay_seconds=60,
    )
    queue = SQLiteAgentQueue(db_path)

    queue.enqueue(event, make_result())
    handoff = queue.get(event.idempotency_key)

    assert handoff is not None
    assert handoff.target_agent == "claude"
    assert handoff.channel_id == "C0CONTROL"
    assert handoff.thread_ts == "1234.5678"
    assert HandoffEvent.model_validate_json(handoff.event_json) == event
    assert handoff.status == "pending"


def test_duplicate_event_does_not_create_second_handoff(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    DeferredDeliveryOutbox(db_path)
    queue = SQLiteAgentQueue(db_path)
    event = make_event()

    queue.enqueue(event, make_result())
    queue.enqueue(event, make_result())

    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM agent_handoffs").fetchone()[0]
    assert count == 1


def test_agents_claim_only_their_own_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    DeferredDeliveryOutbox(db_path)
    queue = SQLiteAgentQueue(db_path)
    claude = make_event(event_id="claude-event", correlation_id="claude-run")
    codex = make_event(
        event_id="codex-event",
        correlation_id="codex-run",
        to_agent="codex",
        event_type="review_requested",
        status="review",
    )
    queue.enqueue(claude, make_result("claude"))
    queue.enqueue(codex, make_result("codex"))

    claimed = queue.claim_next("codex")

    assert claimed is not None
    assert claimed.target_agent == "codex"
    assert claimed.task_id == "ADP-014"
    assert queue.claim_next("gemini") is None


def test_claimed_work_is_recovered_after_lease_expiry(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    DeferredDeliveryOutbox(db_path)
    queue = SQLiteAgentQueue(db_path)
    event = make_event()
    queue.enqueue(event, make_result())

    first = queue.claim_next("claude", lease_seconds=300)
    assert first is not None
    assert first.attempts == 1
    assert queue.claim_next("claude", lease_seconds=300) is None

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE agent_handoffs SET claimed_at = ? WHERE idempotency_key = ?",
            (time.time() - 301, event.idempotency_key),
        )

    recovered = queue.claim_next("claude", lease_seconds=300)
    assert recovered is not None
    assert recovered.idempotency_key == event.idempotency_key
    assert recovered.attempts == 2


def test_failure_requeues_and_completion_is_terminal(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    DeferredDeliveryOutbox(db_path)
    queue = SQLiteAgentQueue(db_path)
    event = make_event()
    queue.enqueue(event, make_result())

    claimed = queue.claim_next("claude")
    assert claimed is not None
    queue.fail(claimed.idempotency_key, "local runner unavailable")
    retry = queue.claim_next("claude")
    assert retry is not None
    assert retry.attempts == 2
    queue.complete(retry.idempotency_key)

    completed = queue.get(retry.idempotency_key)
    assert completed is not None
    assert completed.status == "completed"
    assert queue.claim_next("claude") is None
