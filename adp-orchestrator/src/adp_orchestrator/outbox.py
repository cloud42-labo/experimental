from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeferredDelivery:
    idempotency_key: str
    event_json: str
    channel_id: str
    thread_ts: str | None


class DeferredDeliveryOutbox:
    """SQLite outbox that survives Orchestrator process restarts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _modifier(seconds: float) -> str:
        if seconds <= 0:
            raise ValueError("delay must be positive")
        return f"+{seconds:.3f} seconds"

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS deferred_deliveries (
                    idempotency_key TEXT PRIMARY KEY,
                    event_json TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT,
                    available_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def defer(
        self,
        *,
        idempotency_key: str,
        event_json: str,
        channel_id: str,
        thread_ts: str | None,
        delay_seconds: float,
    ) -> None:
        modifier = self._modifier(delay_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO deferred_deliveries(
                    idempotency_key,
                    event_json,
                    channel_id,
                    thread_ts,
                    available_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, datetime('now', ?), CURRENT_TIMESTAMP)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    event_json = excluded.event_json,
                    channel_id = excluded.channel_id,
                    thread_ts = excluded.thread_ts,
                    available_at = deferred_deliveries.available_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    idempotency_key,
                    event_json,
                    channel_id,
                    thread_ts,
                    modifier,
                ),
            )

    def claim_due(
        self,
        *,
        claim_seconds: float,
        limit: int = 20,
    ) -> list[DeferredDelivery]:
        if limit < 1:
            raise ValueError("limit must be positive")
        modifier = self._modifier(claim_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT idempotency_key, event_json, channel_id, thread_ts
                FROM deferred_deliveries
                WHERE datetime(available_at) <= CURRENT_TIMESTAMP
                ORDER BY datetime(available_at), datetime(created_at)
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            if rows:
                connection.executemany(
                    """
                    UPDATE deferred_deliveries
                    SET available_at = datetime('now', ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE idempotency_key = ?
                    """,
                    [(modifier, str(row[0])) for row in rows],
                )
        return [
            DeferredDelivery(
                idempotency_key=str(row[0]),
                event_json=str(row[1]),
                channel_id=str(row[2]),
                thread_ts=None if row[3] is None else str(row[3]),
            )
            for row in rows
        ]

    def reschedule(self, idempotency_key: str, delay_seconds: float) -> None:
        modifier = self._modifier(delay_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE deferred_deliveries
                SET available_at = datetime('now', ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE idempotency_key = ?
                """,
                (modifier, idempotency_key),
            )

    def complete(self, idempotency_key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM deferred_deliveries WHERE idempotency_key = ?",
                (idempotency_key,),
            )

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM deferred_deliveries"
            ).fetchone()
        return 0 if row is None else int(row[0])
