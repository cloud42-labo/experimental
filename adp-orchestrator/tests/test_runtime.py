from pathlib import Path

import pytest

from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.runtime import (
    RuntimeLease,
    RuntimeLeaseConfig,
    RuntimeLeaseError,
)


def runtime(
    store: IdempotencyStore,
    instance_id: str,
) -> RuntimeLease:
    return RuntimeLease(
        store,
        RuntimeLeaseConfig(lease_seconds=3, heartbeat_seconds=1),
        instance_id=instance_id,
    )


def test_runtime_lease_registers_renews_and_unregisters(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    subject = runtime(store, "runtime-1")

    subject.start()
    assert subject.is_started is True
    subject.ensure_active()
    assert store.heartbeat_runtime("runtime-1", 3) is True

    subject.stop()
    assert subject.is_started is False
    assert store.heartbeat_runtime("runtime-1", 3) is False


def test_second_process_owner_is_fenced_until_first_stops(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    first = runtime(store, "runtime-1")
    second = runtime(store, "runtime-2")
    first.start()

    with pytest.raises(RuntimeLeaseError, match="already running"):
        second.start()

    first.stop()
    second.start()
    assert second.is_started is True
    second.stop()


def test_runtime_lease_fails_closed_if_ownership_disappears(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    subject = runtime(store, "runtime-1")
    subject.start()
    store.unregister_runtime("runtime-1")

    with pytest.raises(RuntimeLeaseError, match="heartbeat failed"):
        subject.ensure_active()

    assert subject.failure is not None
    subject.stop()


def test_runtime_context_manager_releases_owner_and_process_lock(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")

    with runtime(store, "runtime-1") as subject:
        assert subject.is_started is True
        assert store.heartbeat_runtime("runtime-1", 3) is True

    assert subject.is_started is False
    assert store.heartbeat_runtime("runtime-1", 3) is False

    replacement = runtime(store, "runtime-2")
    replacement.start()
    replacement.stop()


@pytest.mark.parametrize(
    ("lease_seconds", "heartbeat_seconds"),
    [(1, 1), (3, 0), (3, 3)],
)
def test_invalid_runtime_lease_config_is_rejected(
    lease_seconds: int,
    heartbeat_seconds: int,
) -> None:
    with pytest.raises(ValueError):
        RuntimeLeaseConfig(
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
