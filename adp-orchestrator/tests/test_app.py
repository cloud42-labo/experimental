import json
from pathlib import Path

import pytest

from adp_orchestrator.adapters import NoopTaskRepository
from adp_orchestrator.app import (
    apply_envelope_event_id,
    build_task_repository,
    extract_event_payload,
    format_result,
)
from adp_orchestrator.config import Settings
from adp_orchestrator.notion_adapter import NotionTaskRepository
from adp_orchestrator.router import RouteResult


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


def test_extracts_json_after_slack_mention() -> None:
    text = '<@U123ABC> {"schema_version": "1.0", "task_id": "ADP-012"}'
    payload = extract_event_payload(text)
    assert payload["task_id"] == "ADP-012"


def test_extracts_json_code_block() -> None:
    text = '<@U123ABC> ```json\n{"event_id": "event-1"}\n```'
    payload = extract_event_payload(text)
    assert payload == {"event_id": "event-1"}


def test_slack_envelope_event_id_overrides_user_value() -> None:
    payload = {"event_id": "user-controlled"}
    body = {"event_id": "Ev_signed_by_slack"}

    enriched = apply_envelope_event_id(payload, body)

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
    repository = build_task_repository(settings(tmp_path))
    assert isinstance(repository, NoopTaskRepository)


def test_with_notion_token_enables_notion_repository(tmp_path: Path) -> None:
    repository = build_task_repository(
        settings(tmp_path, notion_token="notion_secret")
    )
    assert isinstance(repository, NotionTaskRepository)
    repository.close()
