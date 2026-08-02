from __future__ import annotations

import sqlite3
from pathlib import Path


class IdempotencyStore:
    """SQLite-backed processed-event store and single-agent task lock."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS task_locks (
                    task_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def claim_event(self, event_id: str, idempotency_key: str) -> bool:
        """Atomically claim an event before processing side effects."""

        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO processed_events(event_id, idempotency_key)
                    VALUES (?, ?)
                    """,
                    (event_id, idempotency_key),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_event(self, event_id: str, idempotency_key: str) -> None:
        """Release a claim when an external side effect failed and retry is safe."""

        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM processed_events
                WHERE event_id = ? AND idempotency_key = ?
                """,
                (event_id, idempotency_key),
            )

    def is_processed(self, event_id: str, idempotency_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM processed_events
                WHERE event_id = ? OR idempotency_key = ?
                LIMIT 1
                """,
                (event_id, idempotency_key),
            ).fetchone()
        return row is not None

    def acquire_task(self, task_id: str, agent: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_locks(task_id, agent)
                VALUES (?, ?)
                """,
                (task_id, agent),
            )
        return cursor.rowcount == 1

    def current_agent(self, task_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT agent FROM task_locks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def release_task(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_locks WHERE task_id = ?",
                (task_id,),
            )
