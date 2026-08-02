from __future__ import annotations

from typing import Protocol

from .events import HandoffEvent
from .router import RouteResult


class TaskRepository(Protocol):
    """Persists ADP task state to a system such as Notion."""

    def record(self, event: HandoffEvent, result: RouteResult) -> None: ...


class AgentActivator(Protocol):
    """Queues work for an agent without coupling to a paid AI API."""

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None: ...


class NoopTaskRepository:
    """Safe MVP default used until Notion credentials are configured."""

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result


class NoopAgentActivator:
    """Safe MVP default: records no external AI invocation or cost."""

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result
