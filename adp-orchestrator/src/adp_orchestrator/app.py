from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Settings
from .events import HandoffEvent
from .idempotency import IdempotencyStore
from .router import EventRouter, RouteResult

_CODE_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_MENTION = re.compile(r"<@[A-Z0-9]+>")
_VALIDATION_ERROR_MESSAGE = (
    "Event validation failed. Check schema_version, required fields, and allowed values."
)


def extract_event_payload(text: str) -> dict[str, Any]:
    """Extract a JSON object from a Slack mention without evaluating code."""

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


def format_result(result: RouteResult) -> str:
    return (
        f"*Task:* `{result.task_id}`\n"
        f"*Result:* `{result.kind}`\n"
        f"*Status:* `{result.status}`\n"
        f"*Target:* `{result.target_agent or '-'}`\n"
        f"{result.message}"
    )


def build_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    store = IdempotencyStore(settings.adp_db_path)
    router = EventRouter(store)

    @app.event("app_mention")
    def handle_mention(event: dict[str, Any], say: Any, client: Any) -> None:
        if event.get("bot_id"):
            return

        thread_ts = event.get("thread_ts") or event.get("ts")
        try:
            payload = extract_event_payload(str(event.get("text", "")))
            handoff = HandoffEvent.model_validate(payload)
            result = router.route(handoff)
        except (ValueError, json.JSONDecodeError, ValidationError):
            # Never echo the payload or exception because users can paste secrets.
            say(text=_VALIDATION_ERROR_MESSAGE, thread_ts=thread_ts)
            return

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

    return app


def main() -> None:
    settings = Settings()
    app = build_app(settings)
    SocketModeHandler(app, settings.slack_app_token).start()


if __name__ == "__main__":
    main()
