from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

EventType = Literal[
    "task_assigned",
    "work_started",
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
    def validate_attempts(self) -> "HandoffEvent":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must not exceed max_attempts")
        if self.to_agent == "human":
            self.requires_human = True
        return self

    @property
    def idempotency_key(self) -> str:
        return f"{self.correlation_id}:{self.task_id}:{self.event_type}"
