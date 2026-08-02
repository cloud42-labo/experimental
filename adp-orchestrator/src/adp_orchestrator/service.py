from __future__ import annotations

from collections.abc import Callable

from .adapters import AgentActivator, TaskRepository
from .events import HandoffEvent
from .router import EventRouter, RouteResult

DeliveryGuard = Callable[[HandoffEvent, RouteResult], None]


class OrchestrationService:
    """Coordinates routing and external side effects through adapters."""

    def __init__(
        self,
        router: EventRouter,
        task_repository: TaskRepository,
        agent_activator: AgentActivator,
        delivery_guard: DeliveryGuard | None = None,
    ) -> None:
        self.router = router
        self.task_repository = task_repository
        self.agent_activator = agent_activator
        self.delivery_guard = delivery_guard

    def rollback(self, event: HandoffEvent) -> None:
        self.router.rollback(event)

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        self.router.finalize(event, result)

    def ensure_delivery(self, event: HandoffEvent, result: RouteResult) -> None:
        if self.delivery_guard is not None:
            self.delivery_guard(event, result)

    def _apply_side_effects(
        self,
        event: HandoffEvent,
        result: RouteResult,
    ) -> RouteResult:
        if result.kind in {"ignored", "conflict", "deferred"}:
            return result
        if not result.apply_external_side_effects:
            return result

        # Heartbeats renew only the local lease. They do not rewrite Notion or
        # enqueue work, which avoids status noise and external API load.
        if event.event_type == "work_heartbeat":
            return result

        try:
            self.ensure_delivery(event, result)
            self.task_repository.record(event, result)

            should_enqueue = (
                result.kind == "accepted"
                and event.event_type in {"task_assigned", "review_requested"}
                and result.target_agent not in {None, "human"}
            )
            if should_enqueue:
                self.ensure_delivery(event, result)
                self.agent_activator.enqueue(event, result)
        except Exception:
            self.rollback(event)
            raise

        return result

    def handle(self, event: HandoffEvent) -> RouteResult:
        return self._apply_side_effects(event, self.router.route(event))

    def replay_claimed(self, event: HandoffEvent) -> RouteResult:
        """Resume durable outbox work whose routing claim survived a crash."""

        return self._apply_side_effects(
            event,
            self.router.replay_claimed(event),
        )
