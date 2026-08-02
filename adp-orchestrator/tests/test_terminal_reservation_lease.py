import sqlite3
from pathlib import Path

from adp_orchestrator.idempotency import IdempotencyStore


def test_expired_worker_lease_does_not_remove_terminal_reservation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, lock_lease_seconds=1)
    owner = "runtime-1"
    store.register_runtime(owner, 60)

    assert store.claim_started_event(
        "start-1",
        "start-key-1",
        "ADP-012",
        "claude",
        "run-1",
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '-1 hour')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.run_id == "run-1"
    assert lock.terminal_event_id == "complete-1"
    assert store.claim_started_event(
        "start-2",
        "start-key-2",
        "ADP-012",
        "gemini",
        "run-2",
    ) == "conflict"

    assert store.finalize_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) is True
    assert store.claim_started_event(
        "start-2",
        "start-key-2",
        "ADP-012",
        "gemini",
        "run-2",
    ) == "accepted"


def test_terminal_rollback_restores_a_fresh_worker_lease(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, lock_lease_seconds=3600)
    owner = "runtime-1"
    store.register_runtime(owner, 60)

    assert store.claim_started_event(
        "start-1",
        "start-key-1",
        "ADP-012",
        "claude",
        "run-1",
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '-1 hour')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    assert store.rollback_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) is True

    with sqlite3.connect(db_path) as connection:
        live = connection.execute(
            """
            SELECT terminal_event_id IS NULL,
                   datetime(lease_expires_at) > CURRENT_TIMESTAMP
            FROM task_locks
            WHERE task_id = ?
            """,
            ("ADP-012",),
        ).fetchone()
    assert live == (1, 1)
