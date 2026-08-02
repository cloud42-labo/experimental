from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")
_AGENTS = ("claude", "codex", "gemini")


@dataclass(frozen=True)
class AgentCounts:
    pending: int = 0
    claimed: int = 0
    completed: int = 0


@dataclass(frozen=True)
class DailyReport:
    report_date: date
    text: str


class DailyReportStore:
    """Build and durably mark one Slack-safe ADP report per JST date."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_report_deliveries (
                    report_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    sent_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def jst_date(now: datetime | None = None) -> date:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(_JST).date()

    def reserve(self, report_date: date) -> bool:
        """Reserve an unsent date. Failed deliveries remain retryable."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM daily_report_deliveries WHERE report_date = ?",
                (report_date.isoformat(),),
            ).fetchone()
            if row is not None and row["status"] == "sent":
                connection.commit()
                return False
            if row is None:
                connection.execute(
                    """
                    INSERT INTO daily_report_deliveries(report_date, status, attempts)
                    VALUES (?, 'pending', 0)
                    """,
                    (report_date.isoformat(),),
                )
            connection.execute(
                """
                UPDATE daily_report_deliveries
                SET status = 'sending', attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP, last_error = NULL
                WHERE report_date = ?
                """,
                (report_date.isoformat(),),
            )
            connection.commit()
        return True

    def mark_sent(self, report_date: date) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE daily_report_deliveries
                SET status = 'sent', sent_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP, last_error = NULL
                WHERE report_date = ? AND status = 'sending'
                """,
                (report_date.isoformat(),),
            )

    def mark_failed(self, report_date: date, safe_error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE daily_report_deliveries
                SET status = 'pending', updated_at = CURRENT_TIMESTAMP,
                    last_error = ?
                WHERE report_date = ? AND status = 'sending'
                """,
                (safe_error[:500], report_date.isoformat()),
            )

    def _agent_counts(self, connection: sqlite3.Connection) -> dict[str, AgentCounts]:
        rows = connection.execute(
            """
            SELECT target_agent, status, COUNT(*) AS count
            FROM agent_handoffs
            GROUP BY target_agent, status
            """
        ).fetchall()
        mutable = {
            agent: {"pending": 0, "claimed": 0, "completed": 0}
            for agent in _AGENTS
        }
        for row in rows:
            agent = str(row["target_agent"])
            status = str(row["status"])
            if agent in mutable and status in mutable[agent]:
                mutable[agent][status] = int(row["count"])
        return {agent: AgentCounts(**values) for agent, values in mutable.items()}

    def build(self, report_date: date) -> DailyReport:
        with self._connect() as connection:
            counts = self._agent_counts(connection)
            outbox_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM deferred_deliveries"
                ).fetchone()[0]
            )
            human_requests = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM deferred_deliveries
                    WHERE json_extract(event_json, '$.requires_human') = 1
                       OR json_extract(event_json, '$.event_type') = 'human_required'
                    """
                ).fetchone()[0]
            )
            completed = connection.execute(
                """
                SELECT task_id, target_agent FROM agent_handoffs
                WHERE status = 'completed'
                ORDER BY updated_at DESC LIMIT 5
                """
            ).fetchall()
            retrying = connection.execute(
                """
                SELECT task_id, target_agent, attempts FROM agent_handoffs
                WHERE status = 'pending' AND attempts > 0
                ORDER BY updated_at DESC LIMIT 5
                """
            ).fetchall()
            stale = connection.execute(
                """
                SELECT task_id, target_agent, attempts FROM agent_handoffs
                WHERE status = 'claimed'
                  AND claimed_at IS NOT NULL
                  AND claimed_at < unixepoch('now') - 1800
                ORDER BY claimed_at LIMIT 5
                """
            ).fetchall()

        lines = [f"*ADP Daily Report — {report_date.isoformat()} JST*", ""]
        for agent in _AGENTS:
            value = counts[agent]
            lines.append(
                f"*{agent.title()}:* pending {value.pending} / "
                f"claimed {value.claimed} / completed {value.completed}"
            )
        lines.extend(
            [
                "",
                f"*Outbox retries:* {outbox_count}",
                f"*Human Requests:* {human_requests}",
            ]
        )

        def append_rows(title: str, rows: list[sqlite3.Row], include_attempts: bool) -> None:
            lines.extend(["", f"*{title}*"])
            if not rows:
                lines.append("- none")
                return
            for row in rows:
                suffix = f" / attempts {int(row['attempts'])}" if include_attempts else ""
                lines.append(
                    f"- `{row['task_id']}` → {row['target_agent']}{suffix}"
                )

        append_rows("Recently completed", completed, False)
        append_rows("Retrying", retrying, True)
        append_rows("Claimed over 30 minutes", stale, True)
        return DailyReport(report_date=report_date, text="\n".join(lines))


class DailyReportPublisher:
    """Post once per JST date and safely retry a failed Slack delivery."""

    def __init__(self, store: DailyReportStore, client: object, channel_id: str) -> None:
        self.store = store
        self.client = client
        self.channel_id = channel_id

    def publish(self, now: datetime | None = None) -> bool:
        report_date = self.store.jst_date(now)
        if not self.store.reserve(report_date):
            return False
        report = self.store.build(report_date)
        try:
            self.client.chat_postMessage(channel=self.channel_id, text=report.text)
        except Exception:
            self.store.mark_failed(report_date, "Slack daily report delivery failed")
            raise
        self.store.mark_sent(report_date)
        return True
