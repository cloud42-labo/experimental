from __future__ import annotations

import sqlite3
from pathlib import Path


class IdempotencyStore:
    """SQLite-backed processed-event store and leased single-agent task lock."""

    def __init__(
        self,
        db_path: str | Path,
        lock_lease_seconds: int = 3600,
    ) -> None:
        if lock_lease_seconds < 1:
            raise ValueError("lock_lease_seconds must be positive")
        self.db_path = Path(db_path)
        self.lock_lease_seconds = lock_lease_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def _lease_modifier(self) -> str:
        return f"+{self.lock_lease_seconds} seconds"

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
                    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    lease_expires_at TEXT
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(task_locks)")
            }
            if "lease_expires_at" not in columns:
                connection.execute(
                    "ALTER TABLE task_locks ADD COLUMN lease_expires_at TEXT"
                )
            # Locks created by an older version have no lease and are treated as
            # expired on first startup, allowing recovery after an upgrade/crash.
            connection.execute(
                """
                UPDATE task_locks
                SET lease_expires_at = CURRENT_TIMESTAMP
                WHERE lease_expires_at IS NULL
                """
            )
            self._delete_expired_locks(connection)

    def _delete_expired_locks(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM task_locks
            WHERE lease_expires_at IS NULL
               OR datetime(lease_expires_at) <= CURRENT_TIMESTAMP
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
            connection.execute("BEGIN IMMEDIATE")
            self._delete_expired_locks(connection)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO task_locks(
                    task_id, agent, acquired_at, lease_expires_at
                )
                VALUES (?, ?, CURRENT_TIMESTAMP, datetime('now', ?))
                """,
                (task_id, agent, self._lease_modifier),
            )
        return cursor.rowcount == 1

    def heartbeat_task(self, task_id: str, agent: str) -> bool:
        """Extend a live lock lease only when the caller still owns it."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._delete_expired_locks(connection)
            cursor = connection.execute(
                """
                UPDATE task_locks
                SET lease_expires_at = datetime('now', ?)
                WHERE task_id = ? AND agent = ?
                """,
                (self._lease_modifier, task_id, agent),
            )
        return cursor.rowcount == 1

    def current_agent(self, task_id: str) -> str | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._delete_expired_locks(connection)
            row = connection.execute(
                "SELECT agent FROM task_locks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def release_task(self, task_id: str, expected_agent: str) -> bool:
        """Release only the lock owned by the expected agent."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM task_locks
                WHERE task_id = ? AND agent = ?
                """,
                (task_id, expected_agent),
            )
        return cursor.rowcount == 1
