from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from .idempotency import IdempotencyStore


class RuntimeLeaseError(RuntimeError):
    """Safe runtime-ownership error without database or secret details."""


@dataclass(frozen=True)
class RuntimeLeaseConfig:
    lease_seconds: int = 60
    heartbeat_seconds: int = 10

    def __post_init__(self) -> None:
        if self.lease_seconds < 2:
            raise ValueError("runtime lease must be at least 2 seconds")
        if self.heartbeat_seconds < 1:
            raise ValueError("runtime heartbeat must be positive")
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("runtime heartbeat must be shorter than the lease")


class RuntimeLease:
    """Maintains one process-owner lease used for terminal delivery recovery."""

    def __init__(
        self,
        store: IdempotencyStore,
        config: RuntimeLeaseConfig,
        instance_id: str | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.instance_id = instance_id or f"runtime-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._failure: RuntimeLeaseError | None = None

    @property
    def failure(self) -> RuntimeLeaseError | None:
        with self._state_lock:
            return self._failure

    @property
    def is_started(self) -> bool:
        with self._state_lock:
            return self._started

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                return
            self.store.register_runtime(
                self.instance_id,
                self.config.lease_seconds,
            )
            self._failure = None
            self._stop_event.clear()
            self._started = True
            self._thread = threading.Thread(
                target=self._heartbeat_loop,
                name="adp-runtime-heartbeat",
                daemon=True,
            )
            self._thread.start()

    def _set_failure(self) -> None:
        with self._state_lock:
            self._failure = RuntimeLeaseError("Runtime lease heartbeat failed")

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.config.heartbeat_seconds):
            try:
                renewed = self.store.heartbeat_runtime(
                    self.instance_id,
                    self.config.lease_seconds,
                )
            except Exception:
                self._set_failure()
                self._stop_event.set()
                return
            if not renewed:
                self._set_failure()
                self._stop_event.set()
                return

    def ensure_active(self) -> None:
        """Fail closed before accepting another Slack event."""

        with self._state_lock:
            if not self._started:
                raise RuntimeLeaseError("Runtime lease is not started")
            failure = self._failure
        if failure is not None:
            raise failure

        try:
            renewed = self.store.heartbeat_runtime(
                self.instance_id,
                self.config.lease_seconds,
            )
        except Exception:
            self._set_failure()
            raise RuntimeLeaseError("Runtime lease heartbeat failed") from None
        if not renewed:
            self._set_failure()
            raise RuntimeLeaseError("Runtime lease heartbeat failed")

    def stop(self) -> None:
        with self._state_lock:
            if not self._started:
                return
            self._started = False
            thread = self._thread
            self._thread = None
            self._stop_event.set()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.config.heartbeat_seconds + 1.0))

        try:
            self.store.unregister_runtime(self.instance_id)
        finally:
            self._stop_event.clear()

    def __enter__(self) -> "RuntimeLease":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.stop()
