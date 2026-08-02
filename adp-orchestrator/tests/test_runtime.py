from pathlib import Path

import pytest

from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.runtime import (
    RuntimeLease,
    RuntimeLeaseConfig,
    RuntimeLeaseError,
)


def test_runtime_lease_registers_renews_and_unregisters(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    runtime = RuntimeLease(
        store,
        RuntimeLeaseConfig(lease_seconds=3, heartbeat_seconds=1),
        instance_id="runtime-1",
    )

    runtime.start()
    assert runtime.is_started is True
    runtime.ensure_active()
    assert store.heartbeat_runtime("runtime-1", 3) is True

    runtime.stop()
    assert runtime.is_started is False
    assert store.heartbeat_runtime("runtime-1", 3) is False


def test_runtime_lease_fails_closed_if_ownership_disappears(
    tmp_path: Path,
) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")
    runtime = RuntimeLease(
        store,
        RuntimeLeaseConfig(lease_seconds=3, heartbeat_seconds=1),
        instance_id="runtime-1",
    )
    runtime.start()
    store.unregister_runtime("runtime-1")

    with pytest.raises(RuntimeLeaseError, match="heartbeat failed"):
        runtime.ensure_active()

    assert runtime.failure is not None
    runtime.stop()


def test_runtime_context_manager_releases_owner(tmp_path: Path) -> None:
    store = IdempotencyStore(tmp_path / "orchestrator.sqlite3")

    with RuntimeLease(
        store,
        RuntimeLeaseConfig(lease_seconds=3, heartbeat_seconds=1),
        instance_id="runtime-1",
    ) as runtime:
        assert runtime.is_started is True
        assert store.heartbeat_runtime("runtime-1", 3) is True

    assert runtime.is_started is False
    assert store.heartbeat_runtime("runtime-1", 3) is False


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
