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
        if not self.store.claim_event(event.event_id, event.idempotency_key):
            return RouteResult(
                kind="ignored",
                task_id=event.task_id,
                status=event.status,
                message="Duplicate event ignored.",
                target_agent=event.to_agent,
            )

        if event.requires_human or event.event_type == "human_required":
            self.store.release_task(event.task_id)
            return RouteResult(
                kind="human_required",
                task_id=event.task_id,
                status="blocked",
                message=f"Human action required: {event.summary}",
                target_agent="human",
            )

        if event.event_type == "failed":
            self.store.release_task(event.task_id)
            if event.attempt >= event.max_attempts:
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

        # Assignment announces the next agent but does not lock the task.
        # The lock starts only when work_started is received.
        if event.event_type == "work_started":
            acquired = self.store.acquire_task(event.task_id, event.to_agent)
            if not acquired:
                current_agent = self.store.current_agent(event.task_id)
                return RouteResult(
                    kind="conflict",
                    task_id=event.task_id,
                    status="running",
                    message=(
                        f"Task is already running with agent {current_agent}; "
                        "second start was not accepted."
                    ),
                    target_agent=current_agent,
                )

        if event.event_type == "work_completed":
            self.store.release_task(event.task_id)

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
