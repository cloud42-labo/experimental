from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ClaimResult = Literal["accepted", "duplicate", "conflict"]


@dataclass(frozen=True)
class TaskLock:
    task_id: str
    agent: str
    run_id: str
    terminal_event_id: str | None = None


class IdempotencyStore:
    """SQLite-backed processed-event store and leased per-run task lock."""

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
                    run_id TEXT,
                    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    lease_expires_at TEXT,
                    terminal_event_id TEXT,
                    terminal_idempotency_key TEXT
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(task_locks)")
            }
            if "run_id" not in columns:
                connection.execute("ALTER TABLE task_locks ADD COLUMN run_id TEXT")
            if "lease_expires_at" not in columns:
                connection.execute(
                    "ALTER TABLE task_locks ADD COLUMN lease_expires_at TEXT"
                )
            if "terminal_event_id" not in columns:
                connection.execute(
                    "ALTER TABLE task_locks ADD COLUMN terminal_event_id TEXT"
                )
            if "terminal_idempotency_key" not in columns:
                connection.execute(
                    "ALTER TABLE task_locks ADD COLUMN terminal_idempotency_key TEXT"
                )
            # Locks created before run IDs or leases cannot be safely attributed
            # to a current attempt and are expired during migration.
            connection.execute(
                """
                UPDATE task_locks
                SET lease_expires_at = CURRENT_TIMESTAMP
                WHERE run_id IS NULL OR lease_expires_at IS NULL
                """
            )
            self._delete_expired_locks(connection)

    def _delete_expired_locks(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM task_locks
            WHERE run_id IS NULL
               OR (
                    terminal_event_id IS NULL
                    AND (
                        lease_expires_at IS NULL
                        OR datetime(lease_expires_at) <= CURRENT_TIMESTAMP
                    )
               )
            """
        )

    def _insert_event_claim(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        idempotency_key: str,
    ) -> bool:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO processed_events(event_id, idempotency_key)
            VALUES (?, ?)
            """,
            (event_id, idempotency_key),
        )
        return cursor.rowcount == 1

    def _delete_event_claim(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        idempotency_key: str,
    ) -> None:
        connection.execute(
            """
            DELETE FROM processed_events
            WHERE event_id = ? AND idempotency_key = ?
            """,
            (event_id, idempotency_key),
        )

    def _acquire_task(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        agent: str,
        run_id: str,
    ) -> bool:
        self._delete_expired_locks(connection)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO task_locks(
                task_id,
                agent,
                run_id,
                acquired_at,
                lease_expires_at,
                terminal_event_id,
                terminal_idempotency_key
            )
            VALUES (
                ?, ?, ?, CURRENT_TIMESTAMP, datetime('now', ?), NULL, NULL
            )
            """,
            (task_id, agent, run_id, self._lease_modifier),
        )
        return cursor.rowcount == 1

    def claim_event(self, event_id: str, idempotency_key: str) -> bool:
        with self._connect() as connection:
            return self._insert_event_claim(
                connection,
                event_id,
                idempotency_key,
            )

    def claim_started_event(
        self,
        event_id: str,
        idempotency_key: str,
        task_id: str,
        agent: str,
        run_id: str,
    ) -> ClaimResult:
        """Atomically claim a start event and acquire its run lock."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._insert_event_claim(
                connection,
                event_id,
                idempotency_key,
            ):
                return "duplicate"
            if self._acquire_task(connection, task_id, agent, run_id):
                return "accepted"
            self._delete_event_claim(connection, event_id, idempotency_key)
            return "conflict"

    def claim_terminal_event(
        self,
        event_id: str,
        idempotency_key: str,
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> ClaimResult:
        """Atomically claim and reserve one terminal delivery for a live run."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._insert_event_claim(
                connection,
                event_id,
                idempotency_key,
            ):
                return "duplicate"
            self._delete_expired_locks(connection)
            cursor = connection.execute(
                """
                UPDATE task_locks
                SET terminal_event_id = ?,
                    terminal_idempotency_key = ?,
                    lease_expires_at = datetime('now', ?)
                WHERE task_id = ?
                  AND agent = ?
                  AND run_id = ?
                  AND terminal_event_id IS NULL
                """,
                (
                    event_id,
                    idempotency_key,
                    self._lease_modifier,
                    task_id,
                    expected_agent,
                    expected_run_id,
                ),
            )
            if cursor.rowcount == 1:
                return "accepted"
            self._delete_event_claim(connection, event_id, idempotency_key)
            return "conflict"

    def release_event(self, event_id: str, idempotency_key: str) -> None:
        with self._connect() as connection:
            self._delete_event_claim(connection, event_id, idempotency_key)

    def rollback_started_event(
        self,
        event_id: str,
        idempotency_key: str,
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> bool:
        """Roll back a start only while its exact non-terminal lock is live."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                DELETE FROM task_locks
                WHERE task_id = ?
                  AND agent = ?
                  AND run_id = ?
                  AND terminal_event_id IS NULL
                """,
                (task_id, expected_agent, expected_run_id),
            )
            if cursor.rowcount != 1:
                return False
            self._delete_event_claim(connection, event_id, idempotency_key)
            return True

    def rollback_terminal_event(
        self,
        event_id: str,
        idempotency_key: str,
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> bool:
        """Release a terminal reservation and claim while retaining its lock."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE task_locks
                SET terminal_event_id = NULL,
                    terminal_idempotency_key = NULL,
                    lease_expires_at = datetime('now', ?)
                WHERE task_id = ?
                  AND agent = ?
                  AND run_id = ?
                  AND terminal_event_id = ?
                  AND terminal_idempotency_key = ?
                """,
                (
                    self._lease_modifier,
                    task_id,
                    expected_agent,
                    expected_run_id,
                    event_id,
                    idempotency_key,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._delete_event_claim(connection, event_id, idempotency_key)
            return True

    def finalize_terminal_event(
        self,
        event_id: str,
        idempotency_key: str,
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> bool:
        """Release the run only after its reserved terminal delivery succeeds."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                DELETE FROM task_locks
                WHERE task_id = ?
                  AND agent = ?
                  AND run_id = ?
                  AND terminal_event_id = ?
                  AND terminal_idempotency_key = ?
                """,
                (
                    task_id,
                    expected_agent,
                    expected_run_id,
                    event_id,
                    idempotency_key,
                ),
            )
            return cursor.rowcount == 1

    def acquire_task(self, task_id: str, agent: str, run_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._acquire_task(connection, task_id, agent, run_id)

    def heartbeat_task(self, task_id: str, agent: str, run_id: str) -> bool:
        """Extend a live lease only for the exact non-terminal attempt run."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._delete_expired_locks(connection)
            cursor = connection.execute(
                """
                UPDATE task_locks
                SET lease_expires_at = datetime('now', ?)
                WHERE task_id = ?
                  AND agent = ?
                  AND run_id = ?
                  AND terminal_event_id IS NULL
                """,
                (self._lease_modifier, task_id, agent, run_id),
            )
            return cursor.rowcount == 1

    def current_lock(self, task_id: str) -> TaskLock | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._delete_expired_locks(connection)
            row = connection.execute(
                """
                SELECT task_id, agent, run_id, terminal_event_id
                FROM task_locks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskLock(
            task_id=str(row[0]),
            agent=str(row[1]),
            run_id=str(row[2]),
            terminal_event_id=(None if row[3] is None else str(row[3])),
        )

    def current_agent(self, task_id: str) -> str | None:
        lock = self.current_lock(task_id)
        return None if lock is None else lock.agent

    def release_task(
        self,
        task_id: str,
        expected_agent: str,
        expected_run_id: str,
    ) -> bool:
        """Release only the lock owned by the exact Agent and attempt run."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM task_locks
                WHERE task_id = ? AND agent = ? AND run_id = ?
                """,
                (task_id, expected_agent, expected_run_id),
            )
            return cursor.rowcount == 1
