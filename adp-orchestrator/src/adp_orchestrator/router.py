from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from .events import HandoffEvent
from .idempotency import ClaimResult, IdempotencyStore, TaskLock

RouteKind = Literal[
    "ignored",
    "accepted",
    "human_required",
    "conflict",
    "deferred",
]
_WORKER_AGENTS = {"claude", "gemini", "codex"}
_TERMINAL_EVENT_TYPES = {"work_completed", "failed", "human_required"}
_INLINE_RUNTIME_LEASE_SECONDS = 60


@dataclass(frozen=True)
class RouteResult:
    kind: RouteKind
    task_id: str
    status: str
    message: str
    target_agent: str | None = None


class EventRouter:
    def __init__(
        self,
        store: IdempotencyStore,
        delivery_owner_id: str | None = None,
    ) -> None:
        self.store = store
        if delivery_owner_id is None:
            delivery_owner_id = f"inline-runtime-{uuid.uuid4().hex}"
            self.store.register_runtime(
                delivery_owner_id,
                _INLINE_RUNTIME_LEASE_SECONDS,
            )
        if not delivery_owner_id:
            raise ValueError("delivery_owner_id must not be empty")
        self.delivery_owner_id = delivery_owner_id

    def _is_worker_terminal(self, event: HandoffEvent) -> bool:
        return (
            event.from_agent in _WORKER_AGENTS
            and event.event_type in _TERMINAL_EVENT_TYPES
        )

    def rollback(self, event: HandoffEvent) -> None:
        """Allow a safe retry when an external adapter or Slack delivery failed."""

        if event.event_type == "work_started":
            self.store.rollback_started_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.to_agent,
                event.run_id,
            )
        elif self._is_worker_terminal(event):
            self.store.rollback_terminal_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.from_agent,
                event.run_id,
                self.delivery_owner_id,
            )
        else:
            self.store.release_event(event.event_id, event.idempotency_key)

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        """Commit a reserved terminal event after all external delivery succeeds."""

        if result.kind not in {"accepted", "human_required"}:
            return
        if not self._is_worker_terminal(event):
            return
        finalized = self.store.finalize_terminal_event(
            event.event_id,
            event.idempotency_key,
            event.task_id,
            event.from_agent,
            event.run_id,
            self.delivery_owner_id,
        )
        if not finalized:
            raise RuntimeError("Terminal event finalization failed")

    def _ignored(self, event: HandoffEvent) -> RouteResult:
        return RouteResult(
            kind="ignored",
            task_id=event.task_id,
            status=event.status,
            message="Duplicate event ignored.",
            target_agent=event.to_agent,
        )

    def _deferred(self, event: HandoffEvent) -> RouteResult:
        return RouteResult(
            kind="deferred",
            task_id=event.task_id,
            status="running",
            message=(
                "Terminal delivery is waiting for the previous runtime owner "
                "lease to expire. It will be retried automatically."
            ),
            target_agent=event.from_agent,
        )

    def _lock_conflict(
        self,
        event: HandoffEvent,
        lock: TaskLock | None,
    ) -> RouteResult:
        if lock is None:
            message = (
                f"No active run matches {event.from_agent} attempt "
                f"{event.attempt}; stale {event.event_type} was not accepted."
            )
            status = "ready"
            target_agent = None
        else:
            message = (
                f"Task is owned by {lock.agent} in another run; stale "
                f"{event.event_type} from {event.from_agent} attempt "
                f"{event.attempt} was not accepted."
            )
            status = "running"
            target_agent = lock.agent
        return RouteResult(
            kind="conflict",
            task_id=event.task_id,
            status=status,
            message=message,
            target_agent=target_agent,
        )

    def _reservation_result(
        self,
        event: HandoffEvent,
        reservation: ClaimResult,
    ) -> RouteResult | None:
        if reservation == "accepted":
            return None
        if reservation == "duplicate":
            return self._ignored(event)
        if reservation == "deferred":
            return self._deferred(event)
        return self._lock_conflict(
            event,
            self.store.current_lock(event.task_id),
        )

    def route(self, event: HandoffEvent) -> RouteResult:
        if event.event_type == "work_started":
            reservation = self.store.claim_started_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.to_agent,
                event.run_id,
            )
            early_result = self._reservation_result(event, reservation)
            if early_result is not None:
                return early_result
        elif self._is_worker_terminal(event):
            reservation = self.store.claim_terminal_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.from_agent,
                event.run_id,
                self.delivery_owner_id,
            )
            early_result = self._reservation_result(event, reservation)
            if early_result is not None:
                return early_result
        elif not self.store.claim_event(event.event_id, event.idempotency_key):
            return self._ignored(event)

        if event.requires_human or event.event_type == "human_required":
            return RouteResult(
                kind="human_required",
                task_id=event.task_id,
                status="blocked",
                message=f"Human action required: {event.summary}",
                target_agent="human",
            )

        if event.event_type == "failed" and event.attempt >= event.max_attempts:
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

        if event.event_type == "work_heartbeat":
            renewed = self.store.heartbeat_task(
                event.task_id,
                event.from_agent,
                event.run_id,
            )
            if not renewed:
                return self._lock_conflict(
                    event,
                    self.store.current_lock(event.task_id),
                )
            return RouteResult(
                kind="accepted",
                task_id=event.task_id,
                status="running",
                message=(
                    f"work_heartbeat accepted for {event.from_agent}: "
                    f"{event.summary}"
                ),
                target_agent=event.from_agent,
            )

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
