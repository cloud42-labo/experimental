from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .adapters import NoopAgentActivator, NoopTaskRepository, TaskRepository
from .config import Settings
from .events import HandoffEvent
from .idempotency import IdempotencyStore
from .notion_adapter import (
    NotionAdapterConfig,
    NotionAdapterError,
    NotionTaskRepository,
)
from .router import EventRouter, RouteResult
from .service import OrchestrationService

_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_MENTION = re.compile(r"<@[A-Z0-9]+>")
_VALIDATION_ERROR_MESSAGE = (
    "Event validation failed. Check schema_version, required fields, and allowed values."
)
_WRONG_CHANNEL_MESSAGE = "ADP task events are accepted only in #adp-control."
_NOTION_ERROR_MESSAGE = (
    "Notion update failed. The event claim was released and can be retried "
    "after the integration configuration is fixed."
)


def extract_event_payload(text: str) -> dict[str, Any]:
    cleaned = _MENTION.sub("", text).strip()
    match = _CODE_BLOCK.search(cleaned)
    candidate = match.group(1) if match else cleaned
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Message must contain one JSON object")
    payload = json.loads(candidate[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")
    return payload


def apply_envelope_event_id(
    payload: dict[str, Any], body: dict[str, Any]
) -> dict[str, Any]:
    enriched = dict(payload)
    envelope_event_id = body.get("event_id")
    if isinstance(envelope_event_id, str) and envelope_event_id:
        enriched["event_id"] = envelope_event_id
    return enriched


def format_result(result: RouteResult) -> str:
    return (
        f"*Task:* `{result.task_id}`\n"
        f"*Result:* `{result.kind}`\n"
        f"*Status:* `{result.status}`\n"
        f"*Target:* `{result.target_agent or '-'}`\n"
        f"{result.message}"
    )


def build_task_repository(settings: Settings) -> TaskRepository:
    if settings.notion_token is None:
        return NoopTaskRepository()
    return NotionTaskRepository(
        NotionAdapterConfig(token=settings.notion_token)
    )


def deliver_result(
    *,
    handoff: HandoffEvent,
    result: RouteResult,
    thread_ts: str | None,
    say: Any,
    client: Any,
    settings: Settings,
    service: OrchestrationService,
) -> None:
    """Deliver Slack output, then finalize or roll back reserved routing state."""

    try:
        say(text=format_result(result), thread_ts=thread_ts)
        if result.kind == "human_required":
            client.chat_postMessage(
                channel=settings.adp_human_requests_channel_id,
                text=(
                    f"Human Request for `{result.task_id}`\n"
                    f"{result.message}\n"
                    f"Source thread: {thread_ts}"
                ),
            )
        if result.kind in {"accepted", "human_required"}:
            service.finalize(handoff, result)
    except Exception:
        if result.kind in {"accepted", "human_required"}:
            service.rollback(handoff)
        raise


def build_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    service = OrchestrationService(
        router=EventRouter(
            IdempotencyStore(
                settings.adp_db_path,
                lock_lease_seconds=settings.adp_lock_lease_seconds,
            )
        ),
        task_repository=build_task_repository(settings),
        agent_activator=NoopAgentActivator(),
    )

    @app.event("app_mention")
    def handle_mention(
        event: dict[str, Any], body: dict[str, Any], say: Any, client: Any
    ) -> None:
        if event.get("bot_id"):
            return

        thread_ts = event.get("thread_ts") or event.get("ts")
        if event.get("channel") != settings.adp_control_channel_id:
            say(text=_WRONG_CHANNEL_MESSAGE, thread_ts=thread_ts)
            return

        handoff: HandoffEvent | None = None
        try:
            payload = extract_event_payload(str(event.get("text", "")))
            payload = apply_envelope_event_id(payload, body)
            handoff = HandoffEvent.model_validate(payload)
            result = service.handle(handoff)
        except (ValueError, json.JSONDecodeError, ValidationError):
            say(text=_VALIDATION_ERROR_MESSAGE, thread_ts=thread_ts)
            return
        except NotionAdapterError:
            say(text=_NOTION_ERROR_MESSAGE, thread_ts=thread_ts)
            task_id = handoff.task_id if handoff is not None else "unknown"
            client.chat_postMessage(
                channel=settings.adp_human_requests_channel_id,
                text=(
                    f"Human Request for `{task_id}`\n"
                    "Notion integration failed. Check the integration token and "
                    "page-sharing permission, then retry the Slack event."
                ),
            )
            return

        deliver_result(
            handoff=handoff,
            result=result,
            thread_ts=thread_ts,
            say=say,
            client=client,
            settings=settings,
            service=service,
        )

    return app


def main() -> None:
    settings = Settings()
    app = build_app(settings)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
