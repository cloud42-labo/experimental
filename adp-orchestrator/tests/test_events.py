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
