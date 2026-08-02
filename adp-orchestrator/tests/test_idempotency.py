import sqlite3
from pathlib import Path

from adp_orchestrator.idempotency import IdempotencyStore


def register_owner(
    store: IdempotencyStore,
    owner_id: str,
    lease_seconds: int = 60,
) -> str:
    store.register_runtime(owner_id, lease_seconds)
    return owner_id


def expire_runtime(db_path: Path, owner_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE runtime_instances
            SET lease_expires_at = datetime('now', '-1 second')
            WHERE instance_id = ?
            """,
            (owner_id,),
        )


def test_fresh_lock_blocks_second_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.acquire_task("ADP-012", "claude", "run-2") is False
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.agent == "claude"
    assert lock.run_id == "run-1"


def test_expired_non_terminal_lock_is_reclaimed(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '-1 second')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    assert store.acquire_task("ADP-012", "gemini", "run-2") is True
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.agent == "gemini"
    assert lock.run_id == "run-2"


def test_heartbeat_extends_exact_non_terminal_run(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '+1 second')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    assert store.heartbeat_task("ADP-012", "claude", "run-1") is True
    assert store.heartbeat_task("ADP-012", "claude", "run-2") is False


def test_release_requires_exact_non_terminal_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.release_task("ADP-012", "claude", "run-2") is False
    assert store.release_task("ADP-012", "gemini", "run-1") is False
    assert store.release_task("ADP-012", "claude", "run-1") is True
    assert store.current_lock("ADP-012") is None


def test_start_claim_and_lock_are_atomic_and_conflict_is_retryable(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "duplicate"
    assert store.claim_started_event(
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
    ) == "conflict"

    assert store.release_task("ADP-012", "claude", "run-1") is True
    assert store.claim_started_event(
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
    ) == "accepted"


def test_terminal_claim_requires_an_active_runtime_owner(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True

    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        "missing-runtime",
    ) == "conflict"


def test_terminal_claim_reserves_exact_live_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    owner = register_owner(store, "runtime-1")
    assert store.acquire_task("ADP-012", "claude", "run-1") is True

    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.terminal_event_id == "complete-1"
    assert lock.terminal_owner_id == owner
    assert store.heartbeat_task("ADP-012", "claude", "run-1") is False
    assert store.release_task("ADP-012", "claude", "run-1") is False


def test_active_terminal_owner_defers_delivery_takeover(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    first_owner = register_owner(store, "runtime-1")
    second_owner = register_owner(store, "runtime-2")
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        first_owner,
    ) == "accepted"

    assert store.claim_terminal_event(
        "complete-redelivery",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        second_owner,
    ) == "deferred"
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.terminal_event_id == "complete-1"
    assert lock.terminal_owner_id == first_owner


def test_stale_terminal_owner_can_be_recovered_by_new_runtime(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    first_owner = register_owner(store, "runtime-1")
    second_owner = register_owner(store, "runtime-2")
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        first_owner,
    ) == "accepted"

    expire_runtime(db_path, first_owner)

    assert store.claim_terminal_event(
        "complete-redelivery",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        second_owner,
    ) == "accepted"
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.terminal_event_id == "complete-redelivery"
    assert lock.terminal_owner_id == second_owner
    assert store.finalize_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        first_owner,
    ) is False
    assert store.finalize_terminal_event(
        "complete-redelivery",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        second_owner,
    ) is True
    assert store.current_lock("ADP-012") is None


def test_stale_owner_cannot_change_terminal_outcome(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    first_owner = register_owner(store, "runtime-1")
    second_owner = register_owner(store, "runtime-2")
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        first_owner,
    ) == "accepted"
    expire_runtime(db_path, first_owner)

    assert store.claim_terminal_event(
        "failed-1",
        "failed-key-1",
        "ADP-012",
        "claude",
        "run-1",
        second_owner,
    ) == "conflict"


def test_terminal_rollback_keeps_run_and_allows_exact_retry(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    owner = register_owner(store, "runtime-1")
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"

    assert store.rollback_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) is True
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.run_id == "run-1"
    assert lock.terminal_event_id is None
    assert store.claim_terminal_event(
        "complete-redelivery",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"


def test_successor_waits_until_terminal_delivery_finalizes(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    owner = register_owner(store, "runtime-1")
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"

    assert store.claim_started_event(
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
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
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
    ) == "accepted"


def test_terminal_finalize_keeps_event_deduplicated(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    owner = register_owner(store, "runtime-1")
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "accepted"
    assert store.finalize_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) is True

    assert store.claim_terminal_event(
        "complete-1",
        "complete-key-1",
        "ADP-012",
        "claude",
        "run-1",
        owner,
    ) == "conflict"


def test_runtime_registration_heartbeat_and_unregister(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.register_runtime("runtime-1", 60)
    assert store.heartbeat_runtime("runtime-1", 60) is True
    store.unregister_runtime("runtime-1")
    assert store.heartbeat_runtime("runtime-1", 60) is False


def test_legacy_lock_without_run_or_lease_is_recovered(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE processed_events (
                event_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE task_locks (
                task_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO task_locks(task_id, agent) VALUES ('ADP-012', 'claude');
            """
        )

    store = IdempotencyStore(db_path, 3600)

    assert store.current_lock("ADP-012") is None
    assert store.acquire_task("ADP-012", "gemini", "run-2") is True
