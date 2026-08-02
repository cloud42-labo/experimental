from __future__ import annotations

import json
import re
import threading
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
from .runtime import RuntimeLease, RuntimeLeaseConfig, RuntimeLeaseError
from .service import OrchestrationService

_CODE_BLOCK = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_LEADING_MENTION = re.compile(r"^\s*<@[A-Z0-9]+>\s*")
_VALIDATION_ERROR_MESSAGE = (
    "Event validation failed. Check schema_version, required fields, and allowed values."
)
_WRONG_CHANNEL_MESSAGE = "ADP task events are accepted only in #adp-control."
_NOTION_ERROR_MESSAGE = (
    "Notion update failed. The event claim was released and can be retried "
    "after the integration configuration is fixed."
)
_RUNTIME_ERROR_MESSAGE = (
    "Orchestrator runtime lease is unavailable. Restart the local process "
    "before retrying this event."
)


def extract_event_payload(text: str) -> dict[str, Any]:
    cleaned = _LEADING_MENTION.sub("", text, count=1).strip()
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


class DeferredDeliveryScheduler:
    """Retain one redelivery until a stale runtime owner can be reclaimed."""

    def __init__(
        self,
        *,
        runtime: RuntimeLease,
        service: OrchestrationService,
        settings: Settings,
        retry_seconds: float,
    ) -> None:
        if retry_seconds <= 0:
            raise ValueError("retry_seconds must be positive")
        self.runtime = runtime
        self.service = service
        self.settings = settings
        self.retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        self._stopped = False

    def schedule(
        self,
        *,
        handoff: HandoffEvent,
        channel: str,
        thread_ts: str | None,
        client: Any,
    ) -> bool:
        key = handoff.idempotency_key
        with self._lock:
            if self._stopped or key in self._timers:
                return False
            self._start_timer_locked(
                key=key,
                handoff=handoff,
                channel=channel,
                thread_ts=thread_ts,
                client=client,
            )
            return True

    def _start_timer_locked(
        self,
        *,
        key: str,
        handoff: HandoffEvent,
        channel: str,
        thread_ts: str | None,
        client: Any,
    ) -> None:
        timer = threading.Timer(
            self.retry_seconds,
            self._run,
            kwargs={
                "key": key,
                "handoff": handoff,
                "channel": channel,
                "thread_ts": thread_ts,
                "client": client,
            },
        )
        timer.daemon = True
        self._timers[key] = timer
        timer.start()

    def _finish_or_reschedule(
        self,
        *,
        key: str,
        handoff: HandoffEvent,
        channel: str,
        thread_ts: str | None,
        client: Any,
        reschedule: bool,
    ) -> None:
        with self._lock:
            self._timers.pop(key, None)
            if reschedule and not self._stopped:
                self._start_timer_locked(
                    key=key,
                    handoff=handoff,
                    channel=channel,
                    thread_ts=thread_ts,
                    client=client,
                )

    def _run(
        self,
        *,
        key: str,
        handoff: HandoffEvent,
        channel: str,
        thread_ts: str | None,
        client: Any,
    ) -> None:
        reschedule = False
        try:
            self.runtime.ensure_active()
            result = self.service.handle(handoff)
            if result.kind == "deferred":
                reschedule = True
            elif result.kind not in {"ignored", "conflict"}:
                deliver_result(
                    handoff=handoff,
                    result=result,
                    thread_ts=thread_ts,
                    say=lambda **kwargs: client.chat_postMessage(
                        channel=channel,
                        **kwargs,
                    ),
                    client=client,
                    settings=self.settings,
                    service=self.service,
                )
        except RuntimeLeaseError:
            # This process no longer owns a valid runtime lease. A restart is
            # required; retaining timers in a failed process would be unsafe.
            reschedule = False
        except Exception:
            # Accepted routing state is rolled back by service/deliver_result.
            # Keep the one preserved Slack redelivery for a later exact retry.
            reschedule = True
        finally:
            self._finish_or_reschedule(
                key=key,
                handoff=handoff,
                channel=channel,
                thread_ts=thread_ts,
                client=client,
                reschedule=reschedule,
            )

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()


def build_app(settings: Settings) -> App:
    app = App(token=settings.slack_bot_token)
    store = IdempotencyStore(
        settings.adp_db_path,
        lock_lease_seconds=settings.adp_lock_lease_seconds,
    )
    runtime = RuntimeLease(
        store,
        RuntimeLeaseConfig(
            lease_seconds=settings.adp_runtime_lease_seconds,
            heartbeat_seconds=settings.adp_runtime_heartbeat_seconds,
        ),
    )
    runtime.start()

    try:
        service = OrchestrationService(
            router=EventRouter(
                store,
                delivery_owner_id=runtime.instance_id,
            ),
            task_repository=build_task_repository(settings),
            agent_activator=NoopAgentActivator(),
        )
        deferred_scheduler = DeferredDeliveryScheduler(
            runtime=runtime,
            service=service,
            settings=settings,
            retry_seconds=float(settings.adp_runtime_lease_seconds + 1),
        )
    except Exception:
        runtime.stop()
        raise

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
            runtime.ensure_active()
            payload = extract_event_payload(str(event.get("text", "")))
            payload = apply_envelope_event_id(payload, body)
            handoff = HandoffEvent.model_validate(payload)
            result = service.handle(handoff)
        except (ValueError, json.JSONDecodeError, ValidationError):
            say(text=_VALIDATION_ERROR_MESSAGE, thread_ts=thread_ts)
            return
        except RuntimeLeaseError:
            say(text=_RUNTIME_ERROR_MESSAGE, thread_ts=thread_ts)
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

        if result.kind == "deferred":
            deferred_scheduler.schedule(
                handoff=handoff,
                channel=str(event["channel"]),
                thread_ts=thread_ts,
                client=client,
            )
            say(text=format_result(result), thread_ts=thread_ts)
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

    setattr(app, "_adp_deferred_scheduler", deferred_scheduler)
    setattr(app, "_adp_runtime_lease", runtime)
    return app


def stop_app_runtime(app: App) -> None:
    scheduler = getattr(app, "_adp_deferred_scheduler", None)
    if isinstance(scheduler, DeferredDeliveryScheduler):
        scheduler.stop()
    runtime = getattr(app, "_adp_runtime_lease", None)
    if isinstance(runtime, RuntimeLease):
        runtime.stop()


def main() -> None:
    settings = Settings()
    app = build_app(settings)
    try:
        SocketModeHandler(app, settings.slack_app_token).start()
    finally:
        stop_app_runtime(app)


if __name__ == "__main__":
    main()
