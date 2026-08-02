from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

EventType = Literal[
    "task_assigned",
    "work_started",
    "work_heartbeat",
    "work_completed",
    "review_requested",
    "human_required",
    "failed",
]

EventStatus = Literal[
    "backlog",
    "ready",
    "running",
    "review",
    "done",
    "blocked",
]

AgentName = Literal["chris", "claude", "gemini", "human", "codex"]
_WORKER_AGENTS = {"claude", "gemini", "codex"}
_WORKER_SOURCE_EVENTS = {"work_heartbeat", "work_completed", "failed"}


class HandoffEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1, max_length=200)
    task_id: str = Field(min_length=1, max_length=100)
    correlation_id: str = Field(min_length=1, max_length=200)
    from_agent: AgentName
    to_agent: AgentName
    event_type: EventType
    status: EventStatus
    summary: str = Field(min_length=1, max_length=2000)
    notion_url: HttpUrl | None = None
    github_url: HttpUrl | None = None
    requires_human: bool = False
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_contract(self) -> "HandoffEvent":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must not exceed max_attempts")
        if self.to_agent == "human":
            self.requires_human = True
        if self.event_type == "work_started" and self.to_agent not in _WORKER_AGENTS:
            raise ValueError("work_started must target a worker agent")
        if self.event_type == "work_started" and self.requires_human:
            raise ValueError("work_started cannot require human action")
        if (
            self.event_type in _WORKER_SOURCE_EVENTS
            and self.from_agent not in _WORKER_AGENTS
        ):
            raise ValueError(f"{self.event_type} must originate from a worker agent")
        if (
            self.from_agent in _WORKER_AGENTS
            and self.requires_human
            and self.event_type != "human_required"
        ):
            raise ValueError(
                "worker human requests must use the human_required event type"
            )
        return self

    def _canonical_hash(self, payload: dict[str, object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def run_id(self) -> str:
        """Identify one attempt of a task independently of the assigned agent."""

        digest = self._canonical_hash(
            {
                "attempt": self.attempt,
                "correlation_id": self.correlation_id,
                "task_id": self.task_id,
            }
        )
        return f"run-v1:{digest}"

    @property
    def idempotency_key(self) -> str:
        """Return an unambiguous semantic event key.

        Most event types occur once per run and are keyed by ``run_id`` and
        ``event_type``. Heartbeats are intentionally repeatable, so their signed
        Slack envelope ``event_id`` is also part of the semantic key. A redelivery
        of the same heartbeat is still deduplicated by both columns in SQLite.
        """

        payload: dict[str, object] = {
            "event_type": self.event_type,
            "run_id": self.run_id,
        }
        if self.event_type == "work_heartbeat":
            payload["heartbeat_event_id"] = self.event_id
        digest = self._canonical_hash(payload)
        return f"event-v1:{digest}"
