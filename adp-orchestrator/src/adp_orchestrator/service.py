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

        # Duplicates and stale/conflicting events are reported to Slack but must
        # not mutate Notion or activate another agent.
        if result.kind in {"ignored", "conflict"}:
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
            # Property updates are idempotent. Releasing the claim lets a
            # transient adapter failure be retried instead of becoming permanent.
            self.router.rollback(event)
            raise

        return result
