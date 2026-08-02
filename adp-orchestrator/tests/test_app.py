import json
from pathlib import Path

import pytest

from adp_orchestrator.adapters import NoopAgentActivator, NoopTaskRepository
from adp_orchestrator.app import (
    apply_envelope_event_id,
    build_task_repository,
    deliver_result,
    extract_event_payload,
    format_result,
)
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.notion_adapter import NotionTaskRepository
from adp_orchestrator.router import EventRouter, RouteResult
from adp_orchestrator.service import OrchestrationService


class RecordingService:
    def __init__(self) -> None:
        self.rolled_back: list[HandoffEvent] = []
        self.finalized: list[tuple[HandoffEvent, RouteResult]] = []

    def rollback(self, event: HandoffEvent) -> None:
        self.rolled_back.append(event)

    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        self.finalized.append((event, result))


class FailingFinalizeService(RecordingService):
    def finalize(self, event: HandoffEvent, result: RouteResult) -> None:
        del event, result
        raise RuntimeError("terminal finalization failed")


class FailingClient:
    def chat_postMessage(self, **kwargs: object) -> None:
        del kwargs
        raise RuntimeError("Slack notification failed")


def settings(tmp_path: Path, notion_token: str | None = None) -> Settings:
    return Settings(
        slack_bot_token="xoxb-valid-placeholder",
        slack_app_token="xapp-valid-placeholder",
        adp_control_channel_id="C_CONTROL",
        adp_human_requests_channel_id="C_HUMAN",
        adp_daily_channel_id="C_DAILY",
        adp_db_path=tmp_path / "orchestrator.sqlite3",
        notion_token=notion_token,
    )


def handoff() -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "event-1",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "chris",
            "to_agent": "claude",
            "event_type": "task_assigned",
            "status": "ready",
            "summary": "Implement the MVP",
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def worker_event(
    *,
    event_id: str,
    event_type: str,
    status: str,
    summary: str,
) -> HandoffEvent:
    return HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": event_id,
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "claude",
            "to_agent": "chris",
            "event_type": event_type,
            "status": status,
            "summary": summary,
            "attempt": 1,
            "max_attempts": 3,
        }
    )


def test_extracts_json_after_slack_mention() -> None:
    text = '<@U123ABC> {"schema_version": "1.0", "task_id": "ADP-012"}'
    assert extract_event_payload(text)["task_id"] == "ADP-012"


def test_extracts_json_code_block() -> None:
    text = '<@U123ABC> ```json\n{"event_id": "event-1"}\n```'
    assert extract_event_payload(text) == {"event_id": "event-1"}


def test_preserves_mentions_inside_json_string_values() -> None:
    text = (
        '<@U_ORCHESTRATOR> {"event_id": "event-1", '
        '"summary": "Ask <@U_APPROVER> to approve"}'
    )

    assert extract_event_payload(text)["summary"] == (
        "Ask <@U_APPROVER> to approve"
    )


def test_slack_envelope_event_id_overrides_user_value() -> None:
    payload = {"event_id": "user-controlled"}
    enriched = apply_envelope_event_id(
        payload, {"event_id": "Ev_signed_by_slack"}
    )
    assert enriched["event_id"] == "Ev_signed_by_slack"
    assert payload["event_id"] == "user-controlled"


def test_missing_envelope_event_id_keeps_contract_value() -> None:
    payload = {"event_id": "contract-event"}
    assert apply_envelope_event_id(payload, {})["event_id"] == "contract-event"


def test_rejects_text_without_json_object() -> None:
    with pytest.raises(ValueError):
        extract_event_payload("<@U123ABC> run this command")


def test_rejects_json_array() -> None:
    with pytest.raises(ValueError):
        extract_event_payload("[1, 2, 3]")


def test_invalid_json_does_not_execute_or_coerce() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_event_payload("{'event_id': __import__('os').system('echo no')} ")


def test_format_result_has_no_trailing_space_in_target() -> None:
    result = RouteResult(
        kind="accepted",
        task_id="ADP-012",
        status="ready",
        message="accepted",
        target_agent="claude",
    )
    formatted = format_result(result)
    assert "*Target:* `claude`" in formatted
    assert "`claude `" not in formatted


def test_without_notion_token_uses_noop_repository(tmp_path: Path) -> None:
    assert isinstance(build_task_repository(settings(tmp_path)), NoopTaskRepository)


def test_with_notion_token_enables_notion_repository(tmp_path: Path) -> None:
    repository = build_task_repository(
        settings(tmp_path, notion_token="notion_secret")
    )
    assert isinstance(repository, NotionTaskRepository)
    repository.close()


def test_successful_delivery_finalizes_accepted_result(tmp_path: Path) -> None:
    service = RecordingService()
    event = handoff()
    result = RouteResult(
        kind="accepted",
        task_id=event.task_id,
        status="ready",
        message="accepted",
        target_agent="claude",
    )

    deliver_result(
        handoff=event,
        result=result,
        thread_ts="123.45",
        say=lambda **kwargs: None,
        client=object(),
        settings=settings(tmp_path),
        service=service,  # type: ignore[arg-type]
    )

    assert service.finalized == [(event, result)]
    assert service.rolled_back == []


def test_slack_thread_reply_failure_rolls_back_event(tmp_path: Path) -> None:
    service = RecordingService()
    event = handoff()
    result = RouteResult(
        kind="accepted",
        task_id=event.task_id,
        status="ready",
        message="accepted",
        target_agent="claude",
    )

    with pytest.raises(RuntimeError):
        deliver_result(
            handoff=event,
            result=result,
            thread_ts="123.45",
            say=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Slack reply failed")
            ),
            client=object(),
            settings=settings(tmp_path),
            service=service,  # type: ignore[arg-type]
        )

    assert service.finalized == []
    assert service.rolled_back == [event]


def test_human_channel_failure_rolls_back_event(tmp_path: Path) -> None:
    service = RecordingService()
    event = handoff()
    result = RouteResult(
        kind="human_required",
        task_id=event.task_id,
        status="blocked",
        message="human required",
        target_agent="human",
    )

    with pytest.raises(RuntimeError):
        deliver_result(
            handoff=event,
            result=result,
            thread_ts="123.45",
            say=lambda **kwargs: None,
            client=FailingClient(),
            settings=settings(tmp_path),
            service=service,  # type: ignore[arg-type]
        )

    assert service.finalized == []
    assert service.rolled_back == [event]


def test_finalize_failure_rolls_back_reserved_result(tmp_path: Path) -> None:
    service = FailingFinalizeService()
    event = handoff()
    result = RouteResult(
        kind="accepted",
        task_id=event.task_id,
        status="ready",
        message="accepted",
        target_agent="claude",
    )

    with pytest.raises(RuntimeError, match="terminal finalization failed"):
        deliver_result(
            handoff=event,
            result=result,
            thread_ts="123.45",
            say=lambda **kwargs: None,
            client=object(),
            settings=settings(tmp_path),
            service=service,  # type: ignore[arg-type]
        )

    assert service.rolled_back == [event]


def test_ignored_delivery_failure_does_not_remove_original_claim(
    tmp_path: Path,
) -> None:
    service = RecordingService()
    event = handoff()
    result = RouteResult(
        kind="ignored",
        task_id=event.task_id,
        status="ready",
        message="duplicate",
        target_agent="claude",
    )

    with pytest.raises(RuntimeError):
        deliver_result(
            handoff=event,
            result=result,
            thread_ts="123.45",
            say=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Slack reply failed")
            ),
            client=object(),
            settings=settings(tmp_path),
            service=service,  # type: ignore[arg-type]
        )

    assert service.finalized == []
    assert service.rolled_back == []


def test_conflict_delivery_failure_does_not_restore_rejected_run(
    tmp_path: Path,
) -> None:
    service = RecordingService()
    event = HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "stale-complete",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "claude",
            "to_agent": "chris",
            "event_type": "work_completed",
            "status": "done",
            "summary": "Stale completion",
            "attempt": 1,
            "max_attempts": 3,
        }
    )
    result = RouteResult(
        kind="conflict",
        task_id=event.task_id,
        status="ready",
        message="No active run matches the stale completion.",
        target_agent=None,
    )

    with pytest.raises(RuntimeError):
        deliver_result(
            handoff=event,
            result=result,
            thread_ts="123.45",
            say=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Slack reply failed")
            ),
            client=object(),
            settings=settings(tmp_path),
            service=service,  # type: ignore[arg-type]
        )

    assert service.finalized == []
    assert service.rolled_back == []


def test_slack_failure_preserves_first_terminal_outcome_for_exact_retry(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    owner = "runtime-test"
    store.register_runtime(owner, 60)
    service = OrchestrationService(
        router=EventRouter(store, delivery_owner_id=owner),
        task_repository=NoopTaskRepository(),
        agent_activator=NoopAgentActivator(),
    )
    start = HandoffEvent.model_validate(
        {
            "schema_version": "1.0",
            "event_id": "start-1",
            "task_id": "ADP-012",
            "correlation_id": "correlation-1",
            "from_agent": "chris",
            "to_agent": "claude",
            "event_type": "work_started",
            "status": "running",
            "summary": "Start work",
            "attempt": 1,
            "max_attempts": 3,
        }
    )
    assert service.handle(start).kind == "accepted"

    completed = worker_event(
        event_id="complete-1",
        event_type="work_completed",
        status="done",
        summary="Completed",
    )
    completed_result = service.handle(completed)
    assert completed_result.kind == "accepted"

    with pytest.raises(RuntimeError, match="Slack reply failed"):
        deliver_result(
            handoff=completed,
            result=completed_result,
            thread_ts="123.45",
            say=lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("Slack reply failed")
            ),
            client=object(),
            settings=settings(tmp_path),
            service=service,
        )

    contradictory = worker_event(
        event_id="failed-1",
        event_type="failed",
        status="blocked",
        summary="Failed after completion",
    )
    assert service.handle(contradictory).kind == "conflict"

    redelivery = worker_event(
        event_id="complete-redelivery",
        event_type="work_completed",
        status="done",
        summary="Completed",
    )
    redelivery_result = service.handle(redelivery)
    assert redelivery_result.kind == "accepted"
    deliver_result(
        handoff=redelivery,
        result=redelivery_result,
        thread_ts="123.45",
        say=lambda **kwargs: None,
        client=object(),
        settings=settings(tmp_path),
        service=service,
    )

    assert store.current_lock("ADP-012") is None
