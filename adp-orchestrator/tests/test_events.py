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


def test_valid_event_has_stable_idempotency_key() -> None:
    event = HandoffEvent.model_validate(valid_payload())
    assert event.idempotency_key == "correlation-1:ADP-012:task_assigned"


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
