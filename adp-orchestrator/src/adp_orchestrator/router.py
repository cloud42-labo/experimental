from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .events import HandoffEvent
from .idempotency import IdempotencyStore

RouteKind = Literal["ignored", "accepted", "human_required", "conflict"]


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    task_id: str
    status: str
    message: str
    target_agent: str | None = None


class EventRouter:
    def __init__(self, store: IdempotencyStore) -> None:
        self.store = store

    def route(self, event: HandoffEvent) -> RouteResult:
        if self.store.is_processed(event.event_id, event.idempotency_key):
            return RouteResult(
                kind="ignored",
                task_id=event.task_id,
                status=event.status,
                message="Duplicate event ignored.",
                target_agent=event.to_agent,
            )

        if event.requires_human or event.event_type == "human_required":
            self.store.mark_processed(event.event_id, event.idempotency_key)
            return RouteResult(
                kind="human_required",
                task_id=event.task_id,
                status="blocked",
                message=f"Human action required: {event.summary}",
                target_agent="human",
            )

        if event.event_type == "failed" and event.attempt >= event.max_attempts:
            self.store.release_task(event.task_id)
            self.store.mark_processed(event.event_id, event.idempotency_key)
            return RouteResult(
                kind="human_required",
                task_id=event.task_id,
                status="blocked",
                message=(
                    f"Automatic attempts exhausted ({event.attempt}/"
                    f"{event.max_attempts}). Human review required."
                ),
                target_agent="human",
            )

        if event.event_type in {"task_assigned", "work_started"}:
            acquired = self.store.acquire_task(event.task_id, event.to_agent)
            if not acquired:
                current_agent = self.store.current_agent(event.task_id)
                self.store.mark_processed(event.event_id, event.idempotency_key)
                return RouteResult(
                    kind="conflict",
                    task_id=event.task_id,
                    status="running",
                    message=(
                        f"Task is already running with agent {current_agent}; "
                        "second assignment was not started."
                    ),
                    target_agent=current_agent,
                )

        if event.event_type == "work_completed":
            self.store.release_task(event.task_id)

        self.store.mark_processed(event.event_id, event.idempotency_key)
        next_status = {
            "task_assigned": "ready",
            "work_started": "running",
            "work_completed": "review" if event.status != "done" else "done",
            "review_requested": "review",
            "failed": "blocked",
        }[event.event_type]

        return RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status=next_status,
            message=f"{event.event_type} accepted for {event.to_agent}: {event.summary}",
            target_agent=event.to_agent,
        )
