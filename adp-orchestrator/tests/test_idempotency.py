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


def test_heartbeat_extends_exact_run_lock(tmp_path: Path) -> None:
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


def test_heartbeat_cannot_extend_same_agent_different_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.acquire_task("ADP-012", "claude", "run-1")
    assert store.heartbeat_task("ADP-012", "claude", "run-2") is False
    assert store.current_lock("ADP-012").run_id == "run-1"  # type: ignore[union-attr]


def test_release_requires_exact_agent_and_run(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.acquire_task("ADP-012", "claude", "run-1")
    assert store.release_task("ADP-012", "claude", "run-2") is False
    assert store.release_task("ADP-012", "gemini", "run-1") is False
    assert store.release_task("ADP-012", "claude", "run-1") is True
    assert store.current_lock("ADP-012") is None


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
