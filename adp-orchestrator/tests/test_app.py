import json
from pathlib import Path

import pytest

from adp_orchestrator.adapters import NoopTaskRepository
from adp_orchestrator.app import (
    apply_envelope_event_id,
    build_task_repository,
    deliver_result,
    extract_event_payload,
    format_result,
)
from adp_orchestrator.config import Settings
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.notion_adapter import NotionTaskRepository
from adp_orchestrator.router import RouteResult


class RecordingService:
    def __init__(self) -> None:
        self.rolled_back: list[HandoffEvent] = []

    def rollback(self, event: HandoffEvent) -> None:
        self.rolled_back.append(event)


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


def test_extracts_json_after_slack_mention() -> None:
    text = '<@U123ABC> {"schema_version": "1.0", "task_id": "ADP-012"}'
    assert extract_event_payload(text)["task_id"] == "ADP-012"


def test_extracts_json_code_block() -> None:
    text = '<@U123ABC> ```json\n{"event_id": "event-1"}\n```'
    assert extract_event_payload(text) == {"event_id": "event-1"}


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

    assert service.rolled_back == []
