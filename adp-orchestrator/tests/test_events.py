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


def test_idempotency_key_is_stable_versioned_hash() -> None:
    first = HandoffEvent.model_validate(valid_payload())
    second = HandoffEvent.model_validate(valid_payload())
    assert first.idempotency_key == second.idempotency_key
    assert re.fullmatch(r"v1:[0-9a-f]{64}", first.idempotency_key)


def test_retry_attempt_has_distinct_idempotency_key() -> None:
    first = HandoffEvent.model_validate(valid_payload())
    payload = valid_payload()
    payload["attempt"] = 2
    second = HandoffEvent.model_validate(payload)
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

    assert first.idempotency_key != second.idempotency_key


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
