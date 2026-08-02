from __future__ import annotations

from .adapters import AgentActivator, TaskRepository
from .events import HandoffEvent
from .router import EventRouter, RouteResult


class OrchestrationService:
    """Coordinates routing and external side effects through adapters."""

    def __init__(
        self,
        router: EventRouter,
        task_repository: TaskRepository,
        agent_activator: AgentActivator,
    ) -> None:
        self.router = router
        self.task_repository = task_repository
        self.agent_activator = agent_activator

    def handle(self, event: HandoffEvent) -> RouteResult:
        result = self.router.route(event)

        if result.kind == "ignored":
            return result

        try:
            self.task_repository.record(event, result)

            should_enqueue = (
                result.kind == "accepted"
                and event.event_type in {"task_assigned", "review_requested"}
                and result.target_agent not in {None, "human"}
            )
            if should_enqueue:
                self.agent_activator.enqueue(event, result)
        except Exception:
            # The page update is idempotent. Releasing the event claim lets a
            # transient adapter failure be retried instead of becoming permanent.
            self.router.rollback(event)
            raise

        return result
