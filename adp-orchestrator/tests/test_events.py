import re

import pytest
from pydantic import ValidationError

from adp_orchestrator.events import HandoffEvent


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "event_id": "event-1",
        "task_id": "ADP-012",
        "correlation_id": "correlation-1",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Implement the MVP",
        "requires_human": False,
        "attempt": 1,
        "max_attempts": 3,
    }


def terminal_payload() -> dict[str, object]:
    payload = valid_payload()
    payload.update(
        {
            "event_id": "complete-1",
            "from_agent": "claude",
            "to_agent": "chris",
            "event_type": "work_completed",
            "status": "done",
            "summary": "Completed the work",
        }
    )
    return payload


def test_run_id_and_event_key_are_stable_versioned_hashes() -> None:
    first = HandoffEvent.model_validate(valid_payload())
    second = HandoffEvent.model_validate(valid_payload())
    assert first.run_id == second.run_id
    assert first.idempotency_key == second.idempotency_key
    assert re.fullmatch(r"run-v1:[0-9a-f]{64}", first.run_id)
    assert re.fullmatch(r"event-v1:[0-9a-f]{64}", first.idempotency_key)


def test_retry_attempt_has_distinct_run_and_event_keys() -> None:
    first = HandoffEvent.model_validate(valid_payload())
    payload = valid_payload()
    payload["attempt"] = 2
    second = HandoffEvent.model_validate(payload)
    assert first.run_id != second.run_id
    assert first.idempotency_key != second.idempotency_key


def test_colons_in_identifiers_cannot_collide() -> None:
    first_payload = valid_payload()
    first_payload["correlation_id"] = "a:b"
    first_payload["task_id"] = "c"
    second_payload = valid_payload()
    second_payload["correlation_id"] = "a"
    second_payload["task_id"] = "b:c"

    first = HandoffEvent.model_validate(first_payload)
    second = HandoffEvent.model_validate(second_payload)

    assert first.run_id != second.run_id
    assert first.idempotency_key != second.idempotency_key


def test_heartbeats_in_same_run_have_distinct_keys() -> None:
    first_payload = valid_payload()
    first_payload.update(
        {
            "event_type": "work_heartbeat",
            "status": "running",
            "from_agent": "claude",
            "event_id": "heartbeat-1",
        }
    )
    second_payload = dict(first_payload)
    second_payload["event_id"] = "heartbeat-2"

    first = HandoffEvent.model_validate(first_payload)
    second = HandoffEvent.model_validate(second_payload)

    assert first.run_id == second.run_id
    assert first.idempotency_key != second.idempotency_key


def test_heartbeat_redelivery_has_same_key() -> None:
    payload = valid_payload()
    payload.update(
        {
            "event_type": "work_heartbeat",
            "status": "running",
            "from_agent": "claude",
            "event_id": "heartbeat-1",
        }
    )
    first = HandoffEvent.model_validate(payload)
    second = HandoffEvent.model_validate(payload)
    assert first.idempotency_key == second.idempotency_key


def test_terminal_redelivery_with_new_envelope_has_same_key() -> None:
    first_payload = terminal_payload()
    second_payload = dict(first_payload)
    second_payload["event_id"] = "complete-redelivery"

    first = HandoffEvent.model_validate(first_payload)
    second = HandoffEvent.model_validate(second_payload)

    assert first.run_id == second.run_id
    assert first.idempotency_key == second.idempotency_key


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("status", "review"),
        ("summary", "Changed completion details"),
        ("max_attempts", 4),
        ("to_agent", "codex"),
        ("github_url", "https://github.com/cloud42-labo/experimental/pull/58"),
    ],
)
def test_terminal_outcome_changes_produce_distinct_keys(
    field: str,
    changed_value: object,
) -> None:
    first_payload = terminal_payload()
    changed_payload = dict(first_payload)
    changed_payload[field] = changed_value

    first = HandoffEvent.model_validate(first_payload)
    changed = HandoffEvent.model_validate(changed_payload)

    assert first.run_id == changed.run_id
    assert first.idempotency_key != changed.idempotency_key


def test_failed_escalation_rule_is_bound_to_terminal_key() -> None:
    first_payload = terminal_payload()
    first_payload.update(
        {
            "event_type": "failed",
            "status": "blocked",
            "summary": "Attempt failed",
            "attempt": 3,
            "max_attempts": 3,
        }
    )
    changed_payload = dict(first_payload)
    changed_payload["max_attempts"] = 4

    first = HandoffEvent.model_validate(first_payload)
    changed = HandoffEvent.model_validate(changed_payload)

    assert first.run_id == changed.run_id
    assert first.idempotency_key != changed.idempotency_key


def test_attempt_must_not_exceed_max_attempts() -> None:
    payload = valid_payload()
    payload["attempt"] = 4
    with pytest.raises(ValidationError):
        HandoffEvent.model_validate(payload)


def test_human_target_sets_requires_human() -> None:
    payload = valid_payload()
    payload["to_agent"] = "human"
    event = HandoffEvent.model_validate(payload)
    assert event.requires_human is True


@pytest.mark.parametrize("event_type", ["work_heartbeat", "work_completed", "failed"])
def test_worker_lifecycle_events_require_worker_source(event_type: str) -> None:
    payload = valid_payload()
    payload.update(
        {
            "event_type": event_type,
            "status": "running" if event_type == "work_heartbeat" else "done",
            "from_agent": "chris",
            "to_agent": "chris",
        }
    )

    with pytest.raises(ValidationError, match="must originate from a worker agent"):
        HandoffEvent.model_validate(payload)


def test_work_started_requires_worker_target() -> None:
    payload = valid_payload()
    payload.update(
        {
            "event_type": "work_started",
            "status": "running",
            "to_agent": "human",
        }
    )

    with pytest.raises(ValidationError, match="must target a worker agent"):
        HandoffEvent.model_validate(payload)


@pytest.mark.parametrize("from_agent", ["chris", "human", "claude"])
def test_work_started_cannot_require_human_action(from_agent: str) -> None:
    payload = valid_payload()
    payload.update(
        {
            "from_agent": from_agent,
            "event_type": "work_started",
            "status": "running",
            "requires_human": True,
        }
    )

    with pytest.raises(ValidationError, match="work_started cannot require human action"):
        HandoffEvent.model_validate(payload)
