from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .events import HandoffEvent
from .router import RouteResult

QueueStatus = Literal["pending", "claimed", "completed", "failed"]


@dataclass(frozen=True)
class AgentHandoff:
    idempotency_key: str
    task_id: str
    target_agent: str
    event_json: str
    channel_id: str | None
    thread_ts: str | None
    status: QueueStatus
    attempts: int
    last_error: str | None


class SQLiteAgentQueue:
    """Durable local queue that never invokes a paid AI API directly."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        configured = db_path or os.getenv("ADP_DB_PATH") or ".adp/orchestrator.sqlite3"
        self.db_path = Path(configured)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_handoffs (
                    idempotency_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    target_agent TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    channel_id TEXT,
                    thread_ts TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    claimed_at REAL,
                    completed_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_handoffs_agent_status
                ON agent_handoffs(target_agent, status, created_at)
                """
            )

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None:
        target = result.target_agent
        if target not in {"claude", "codex", "gemini"}:
            raise ValueError("AI handoff target must be claude, codex, or gemini")

        now = time.time()
        with self._connect() as connection:
            context = connection.execute(
                """
                SELECT channel_id, thread_ts
                FROM deferred_deliveries
                WHERE idempotency_key = ?
                """,
                (event.idempotency_key,),
            ).fetchone()
            channel_id = None if context is None else context["channel_id"]
            thread_ts = None if context is None else context["thread_ts"]
            connection.execute(
                """
                INSERT OR IGNORE INTO agent_handoffs (
                    idempotency_key, task_id, target_agent, event_json,
                    channel_id, thread_ts, status, attempts,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (
                    event.idempotency_key,
                    event.task_id,
                    target,
                    event.model_dump_json(),
                    channel_id,
                    thread_ts,
                    now,
                    now,
                ),
            )

    def claim_next(self, target_agent: str, lease_seconds: float = 300.0) -> AgentHandoff | None:
        if target_agent not in {"claude", "codex", "gemini"}:
            raise ValueError("unsupported target agent")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        now = time.time()
        expired = now - lease_seconds
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM agent_handoffs
                WHERE target_agent = ?
                  AND (status = 'pending' OR (status = 'claimed' AND claimed_at < ?))
                ORDER BY created_at
                LIMIT 1
                """,
                (target_agent, expired),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE agent_handoffs
                SET status = 'claimed', claimed_at = ?, attempts = attempts + 1,
                    updated_at = ?, last_error = NULL
                WHERE idempotency_key = ?
                """,
                (now, now, row["idempotency_key"]),
            )
            connection.commit()
        return self.get(str(row["idempotency_key"]))

    def complete(self, idempotency_key: str) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_handoffs
                SET status = 'completed', completed_at = ?, updated_at = ?, last_error = NULL
                WHERE idempotency_key = ? AND status = 'claimed'
                """,
                (now, now, idempotency_key),
            )

    def fail(self, idempotency_key: str, safe_error: str) -> None:
        now = time.time()
        message = safe_error[:500]
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_handoffs
                SET status = 'pending', claimed_at = NULL, updated_at = ?, last_error = ?
                WHERE idempotency_key = ? AND status = 'claimed'
                """,
                (now, message, idempotency_key),
            )

    def get(self, idempotency_key: str) -> AgentHandoff | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_handoffs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return AgentHandoff(
            idempotency_key=str(row["idempotency_key"]),
            task_id=str(row["task_id"]),
            target_agent=str(row["target_agent"]),
            event_json=str(row["event_json"]),
            channel_id=None if row["channel_id"] is None else str(row["channel_id"]),
            thread_ts=None if row["thread_ts"] is None else str(row["thread_ts"]),
            status=row["status"],
            attempts=int(row["attempts"]),
            last_error=None if row["last_error"] is None else str(row["last_error"]),
        )
