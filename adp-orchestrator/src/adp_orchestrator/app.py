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
from .outbox import DeferredDelivery, DeferredDeliveryOutbox
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
_WORKER_AGENTS = {"claude", "gemini", "codex"}
_TERMINAL_EVENT_TYPES = {"work_completed", "failed", "human_required"}


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
    """Fence, deliver, then finalize or roll back reserved routing state."""

    try:
        service.ensure_delivery(handoff, result)
        say(text=format_result(result), thread_ts=thread_ts)
        if result.kind == "human_required":
            service.ensure_delivery(handoff, result)
            client.chat_postMessage(
                channel=settings.adp_human_requests_channel_id,
                text=(
                    f"Human Request for `{result.task_id}`\n"
                    f"{result.message}\n"
                    f"Source thread: {thread_ts}"
                ),
            )
        if result.kind in {"accepted", "human_required"}:
            service.ensure_delivery(handoff, result)
            service.finalize(handoff, result)
    except Exception:
        if result.kind in {"accepted", "human_required"}:
            service.rollback(handoff)
        raise


class DeferredDeliveryScheduler:
    """Processes a persistent SQLite outbox across process restarts."""

    def __init__(
        self,
        *,
        runtime: RuntimeLease,
        service: OrchestrationService,
        settings: Settings,
        client: Any,
        outbox: DeferredDeliveryOutbox,
        retry_seconds: float,
        poll_seconds: float = 1.0,
        claim_seconds: float = 30.0,
    ) -> None:
        if retry_seconds <= 0 or poll_seconds <= 0 or claim_seconds <= 0:
            raise ValueError("scheduler intervals must be positive")
        self.runtime = runtime
        self.service = service
        self.settings = settings
        self.client = client
        self.outbox = outbox
        self.retry_seconds = retry_seconds
        self.poll_seconds = poll_seconds
        self.claim_seconds = claim_seconds
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_started(self) -> bool:
        with self._lock:
            return self._thread is not None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            self._wake_event.set()
            self._thread = threading.Thread(
                target=self._loop,
                name="adp-deferred-outbox",
                daemon=True,
            )
            self._thread.start()

    def defer(
        self,
        *,
        handoff: HandoffEvent,
        channel: str,
        thread_ts: str | None,
    ) -> None:
        self.outbox.defer(
            idempotency_key=handoff.idempotency_key,
            event_json=handoff.model_dump_json(),
            channel_id=channel,
            thread_ts=thread_ts,
            delay_seconds=self.retry_seconds,
        )
        self._wake_event.set()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            deliveries = self.outbox.claim_due(
                claim_seconds=self.claim_seconds,
            )
            if deliveries:
                for delivery in deliveries:
                    if self._stop_event.is_set():
                        self.outbox.reschedule(
                            delivery.idempotency_key,
                            self.poll_seconds,
                        )
                        return
                    self._process(delivery)
                continue
            self._wake_event.wait(self.poll_seconds)
            self._wake_event.clear()

    def _process(self, delivery: DeferredDelivery) -> None:
        try:
            self.runtime.ensure_active()
            handoff = HandoffEvent.model_validate_json(delivery.event_json)
            result = self.service.handle(handoff)
            if result.kind == "deferred":
                self.outbox.reschedule(
                    delivery.idempotency_key,
                    self.retry_seconds,
                )
                return
            if result.kind in {"ignored", "conflict"}:
                self.outbox.complete(delivery.idempotency_key)
                return

            deliver_result(
                handoff=handoff,
                result=result,
                thread_ts=delivery.thread_ts,
                say=lambda **kwargs: self.client.chat_postMessage(
                    channel=delivery.channel_id,
                    **kwargs,
                ),
                client=self.client,
                settings=self.settings,
                service=self.service,
            )
            self.outbox.complete(delivery.idempotency_key)
        except (ValidationError, ValueError):
            # A persisted payload that no longer matches the contract cannot be
            # delivered safely. Remove it rather than retrying forever.
            self.outbox.complete(delivery.idempotency_key)
        except Exception:
            # Adapter and Slack failures roll back accepted routing state. The
            # durable payload remains available for the next exact retry.
            self.outbox.reschedule(
                delivery.idempotency_key,
                self.retry_seconds,
            )

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop_event.set()
            self._wake_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join()


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

    def delivery_guard(event: HandoffEvent, result: RouteResult) -> None:
        runtime.ensure_active()
        is_worker_terminal = (
            event.from_agent in _WORKER_AGENTS
            and event.event_type in _TERMINAL_EVENT_TYPES
            and result.kind in {"accepted", "human_required"}
        )
        if not is_worker_terminal:
            return
        lock = store.current_lock(event.task_id)
        if (
            lock is None
            or lock.agent != event.from_agent
            or lock.run_id != event.run_id
            or lock.terminal_event_id != event.event_id
            or lock.terminal_owner_id != runtime.instance_id
        ):
            raise RuntimeLeaseError("Terminal delivery ownership was superseded")

    try:
        service = OrchestrationService(
            router=EventRouter(
                store,
                delivery_owner_id=runtime.instance_id,
            ),
            task_repository=build_task_repository(settings),
            agent_activator=NoopAgentActivator(),
            delivery_guard=delivery_guard,
        )
        outbox = DeferredDeliveryOutbox(settings.adp_db_path)
        deferred_scheduler = DeferredDeliveryScheduler(
            runtime=runtime,
            service=service,
            settings=settings,
            client=app.client,
            outbox=outbox,
            retry_seconds=float(settings.adp_runtime_lease_seconds + 1),
        )
        deferred_scheduler.start()
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
            # Persist before acknowledging Slack, so a replacement restart cannot
            # lose the only redelivery that arrived during the old Owner lease.
            deferred_scheduler.defer(
                handoff=handoff,
                channel=str(event["channel"]),
                thread_ts=thread_ts,
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
