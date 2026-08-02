import sqlite3
from pathlib import Path

from adp_orchestrator.idempotency import IdempotencyStore


def test_fresh_lock_blocks_second_agent(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    assert store.acquire_task("ADP-012", "claude") is True
    assert store.acquire_task("ADP-012", "gemini") is False
    assert store.current_agent("ADP-012") == "claude"


def test_expired_lock_is_reclaimed(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    assert store.acquire_task("ADP-012", "claude") is True

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '-1 second')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    assert store.acquire_task("ADP-012", "gemini") is True
    assert store.current_agent("ADP-012") == "gemini"


def test_heartbeat_extends_owned_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"
    store = IdempotencyStore(db_path, 3600)
    assert store.acquire_task("ADP-012", "claude") is True

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE task_locks
            SET lease_expires_at = datetime('now', '+1 second')
            WHERE task_id = ?
            """,
            ("ADP-012",),
        )

    assert store.heartbeat_task("ADP-012", "claude") is True
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


def test_heartbeat_cannot_take_over_another_agent_lock(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3", 3600)
    store.acquire_task("ADP-012", "claude")
    assert store.heartbeat_task("ADP-012", "gemini") is False
    assert store.current_agent("ADP-012") == "claude"


def test_legacy_lock_without_lease_is_recovered_on_startup(tmp_path: Path) -> None:
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

    assert store.current_agent("ADP-012") is None
    assert store.acquire_task("ADP-012", "gemini") is True
