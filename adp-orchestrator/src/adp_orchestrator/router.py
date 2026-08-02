from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .events import HandoffEvent
from .idempotency import IdempotencyStore, TaskLock

RouteKind = Literal["ignored", "accepted", "human_required", "conflict"]
_WORKER_AGENTS = {"claude", "gemini", "codex"}


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
        elif event.event_type in {"work_completed", "failed"}:
            self.store.rollback_terminal_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.from_agent,
                event.run_id,
            )
        elif (
            event.event_type == "human_required"
            and event.from_agent in _WORKER_AGENTS
        ):
            self.store.rollback_terminal_event(
                event.event_id,
                event.idempotency_key,
                event.task_id,
                event.from_agent,
                event.run_id,
            )
        else:
            self.store.release_event(event.event_id, event.idempotency_key)

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

    def _release_worker_run(self, event: HandoffEvent) -> RouteResult | None:
        """Atomically release only the exact worker run or return a retryable conflict."""

        released = self.store.release_task(
            event.task_id,
            event.from_agent,
            event.run_id,
        )
        if released:
            return None

        # The semantic key intentionally identifies the run and event type, not
        # the sender. A spoofed or stale sender must not permanently claim that
        # key and block the legitimate owner from publishing its terminal event.
        self.store.release_event(event.event_id, event.idempotency_key)
        return self._lock_conflict(
            event,
            self.store.current_lock(event.task_id),
        )

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
            if event.from_agent in _WORKER_AGENTS:
                conflict = self._release_worker_run(event)
                if conflict is not None:
                    return conflict
            return RouteResult(
                kind="human_required",
                task_id=event.task_id,
                status="blocked",
                message=f"Human action required: {event.summary}",
                target_agent="human",
            )

        if event.event_type in {"failed", "work_completed"}:
            conflict = self._release_worker_run(event)
            if conflict is not None:
                return conflict

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

        if event.event_type == "work_started":
            acquired = self.store.acquire_task(
                event.task_id,
                event.to_agent,
                event.run_id,
            )
            if not acquired:
                # A start conflict is transient: once the current run ends, the
                # exact same start event may be retried successfully.
                self.store.release_event(event.event_id, event.idempotency_key)
                return self._lock_conflict(
                    event,
                    self.store.current_lock(event.task_id),
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
