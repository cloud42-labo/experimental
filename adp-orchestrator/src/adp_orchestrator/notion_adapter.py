from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from .events import HandoffEvent
from .router import RouteResult

_NOTION_API_BASE = "https://api.notion.com/v1"
_PAGE_ID_PATTERN = re.compile(
    r"(?P<id>[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
_STATUS_NAMES = {
    "backlog": "Backlog",
    "ready": "Ready",
    "running": "In Progress",
    "review": "Review",
    "done": "Done",
    "blocked": "Blocked",
}
_AGENT_NAMES = {
    "chris": "ChatGPT",
    "claude": "Claude Opus",
    "gemini": "Gemini CLI",
    "codex": "Codex",
    "human": "Human",
}


class NotionAdapterError(RuntimeError):
    """Safe integration error that never includes tokens or response bodies."""


@dataclass(frozen=True)
class NotionAdapterConfig:
    token: SecretStr
    api_version: str = "2026-03-11"
    timeout_seconds: float = 10.0


def page_id_from_url(url: str) -> str:
    match = _PAGE_ID_PATTERN.search(url)
    if match is None:
        raise NotionAdapterError("Notion page URL does not contain a page ID")
    return match.group("id").replace("-", "")


def _rich_text(content: str) -> dict[str, object]:
    return {
        "rich_text": [
            {
                "type": "text",
                "text": {"content": content[:2000]},
            }
        ]
    }


class NotionTaskRepository:
    """Updates one Stories & Tasks row through Notion's Update page API."""

    def __init__(
        self,
        config: NotionAdapterConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        if event.notion_url is None:
            raise NotionAdapterError("notion_url is required for Notion task updates")

        page_id = page_id_from_url(str(event.notion_url))
        properties: dict[str, object] = {
            "Status": {"select": {"name": _STATUS_NAMES[result.status]}},
            "Result": _rich_text(result.message),
        }

        assigned_agent = _AGENT_NAMES.get(result.target_agent or "")
        if assigned_agent is not None:
            properties["Assigned Agent"] = {"select": {"name": assigned_agent}}

        if result.status == "blocked" or result.kind == "human_required":
            properties["Blocker"] = _rich_text(result.message)
            properties["Environment Help"] = {"checkbox": True}
        else:
            properties["Blocker"] = {"rich_text": []}
            properties["Environment Help"] = {"checkbox": False}

        try:
            response = self.client.patch(
                f"{_NOTION_API_BASE}/pages/{page_id}",
                headers={
                    "Authorization": (
                        f"Bearer {self.config.token.get_secret_value()}"
                    ),
                    "Content-Type": "application/json",
                    "Notion-Version": self.config.api_version,
                },
                json={"properties": properties},
            )
        except httpx.RequestError:
            # Suppress the original transport exception because its traceback can
            # contain proxy credentials, URLs, or user-controlled diagnostics.
            raise NotionAdapterError(
                "Notion page update transport failed"
            ) from None

        if response.is_error:
            raise NotionAdapterError(
                f"Notion page update failed with HTTP {response.status_code}"
            )
