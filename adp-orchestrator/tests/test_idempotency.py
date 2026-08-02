import sqlite3
from pathlib import Path

from adp_orchestrator.idempotency import IdempotencyStore


def test_fresh_lock_blocks_second_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True
    assert store.acquire_task("ADP-012", "claude", "run-2") is False
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.agent == "claude"
    assert lock.run_id == "run-1"


def test_expired_lock_is_reclaimed(tmp_path: Path) -> None:
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
    with sqlite3.connect(db_path) as connection:
        extended = connection.execute(
            """
            SELECT datetime(lease_expires_at) > datetime('now', '+30 minutes')
            FROM task_locks
            WHERE task_id = ?
            """,
            ("ADP-012",),
        ).fetchone()
    assert extended == (1,)


def test_heartbeat_rejects_wrong_or_terminal_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.acquire_task("ADP-012", "claude", "run-1")
    assert store.heartbeat_task("ADP-012", "claude", "run-2") is False
    assert store.claim_terminal_event(
        "terminal-1", "terminal-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.heartbeat_task("ADP-012", "claude", "run-1") is False


def test_release_requires_exact_agent_and_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.acquire_task("ADP-012", "claude", "run-1")
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


def test_terminal_claim_reserves_exact_live_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude", "run-1") is True

    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.terminal_event_id == "complete-1"
    assert store.claim_terminal_event(
        "fail-1", "fail-key-1", "ADP-012", "claude", "run-1"
    ) == "conflict"


def test_start_rollback_releases_claim_only_with_live_non_terminal_lock(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"

    assert store.rollback_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) is True
    assert store.current_lock("ADP-012") is None
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"


def test_start_rollback_cannot_resurrect_completed_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"

    assert store.rollback_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) is False
    assert store.finalize_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) is True
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "duplicate"
    assert store.current_lock("ADP-012") is None


def test_terminal_rollback_keeps_lock_and_allows_exact_retry(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"

    assert store.rollback_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) is True
    lock = store.current_lock("ADP-012")
    assert lock is not None
    assert lock.run_id == "run-1"
    assert lock.terminal_event_id is None
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"


def test_successor_cannot_start_until_terminal_delivery_finalizes(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"

    assert store.claim_started_event(
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
    ) == "conflict"
    assert store.finalize_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) is True
    assert store.claim_started_event(
        "start-2", "start-key-2", "ADP-012", "gemini", "run-2"
    ) == "accepted"


def test_terminal_finalize_keeps_claim_deduplicated(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.claim_started_event(
        "start-1", "start-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "accepted"
    assert store.finalize_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) is True

    assert store.current_lock("ADP-012") is None
    assert store.claim_terminal_event(
        "complete-1", "complete-key-1", "ADP-012", "claude", "run-1"
    ) == "duplicate"


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
