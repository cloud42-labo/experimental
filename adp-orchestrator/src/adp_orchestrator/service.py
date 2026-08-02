from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace

from pydantic import SecretStr

from .adapters import AgentActivator, TaskRepository
from .events import HandoffEvent
from .github_adapter import (
    GitHubAdapterConfig,
    GitHubReference,
    GitHubReferenceClient,
)
from .router import EventRouter, RouteResult

DeliveryGuard = Callable[[HandoffEvent, RouteResult], None]


def format_github_reference(reference: GitHubReference) -> str:
    """Return a compact Slack-safe summary without exposing credentials or bodies."""

    repository = f"{reference.owner}/{reference.repository}"
    if reference.kind == "issue":
        return (
            f"GitHub Issue: {repository}#{reference.number} "
            f"[{reference.state}] {reference.title}\n{reference.html_url}"
        )

    flags: list[str] = [reference.state]
    if reference.draft:
        flags.append("draft")
    if reference.merged:
        flags.append("merged")
    details = ", ".join(flags)
    base = f" -> {reference.base_branch}" if reference.base_branch else ""
    return (
        f"GitHub PR: {repository}#{reference.number} "
        f"[{details}] {reference.title}{base}\n{reference.html_url}"
    )


class OrchestrationService:
    """Coordinates routing and external side effects through adapters."""

    def __init__(
        self,
        router: EventRouter,
        task_repository: TaskRepository,
        agent_activator: AgentActivator,
        delivery_guard: DeliveryGuard | None = None,
        github_reference_client: GitHubReferenceClient | None = None,
    ) -> None:
        self.router = router
        self.task_repository = task_repository
        self.agent_activator = agent_activator
        self.delivery_guard = delivery_guard
        self.github_reference_client = github_reference_client

    def rollback(self, event: HandoffEvent) -> None:
        self.router.rollback(event)

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        self.router.finalize(event, result)

    def ensure_delivery(self, event: HandoffEvent, result: RouteResult) -> None:
        if self.delivery_guard is not None:
            self.delivery_guard(event, result)

    def _github_client(self) -> tuple[GitHubReferenceClient, bool]:
        if self.github_reference_client is not None:
            return self.github_reference_client, False
        token_value = os.getenv("GITHUB_TOKEN")
        token = SecretStr(token_value) if token_value else None
        return GitHubReferenceClient(GitHubAdapterConfig(token=token)), True

    def _attach_github_reference(
        self,
        event: HandoffEvent,
        result: RouteResult,
    ) -> RouteResult:
        if event.github_url is None:
            return result

        client, owns_client = self._github_client()
        try:
            reference = client.fetch(str(event.github_url))
        finally:
            if owns_client:
                client.close()

        return replace(
            result,
            message=f"{result.message}\n\n{format_github_reference(reference)}",
        )

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
            result = self._attach_github_reference(event, result)
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
