from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .idempotency import IdempotencyStore


class RuntimeLeaseError(RuntimeError):
    """Safe runtime-ownership error without database or secret details."""


class ProcessFileLock:
    """Cross-platform non-blocking lock that fences local Orchestrator processes."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: BinaryIO | None = None

    @property
    def is_acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            raise RuntimeLeaseError(
                "Another ADP Orchestrator process is already running"
            ) from None
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


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
    """Maintains one fenced process owner used for terminal delivery recovery."""

    def __init__(
        self,
        store: IdempotencyStore,
        config: RuntimeLeaseConfig,
        instance_id: str | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.instance_id = instance_id or f"runtime-{uuid.uuid4().hex}"
        self._process_lock = ProcessFileLock(
            Path(f"{self.store.db_path}.runtime.lock")
        )
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
            self._process_lock.acquire()
            try:
                self.store.register_runtime(
                    self.instance_id,
                    self.config.lease_seconds,
                )
            except Exception:
                self._process_lock.release()
                raise
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
        """Fail closed before accepting another Slack event or side effect."""

        with self._state_lock:
            if not self._started or not self._process_lock.is_acquired:
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
                self._process_lock.release()
                return
            self._started = False
            thread = self._thread
            self._thread = None
            self._stop_event.set()

        if thread is not None and thread is not threading.current_thread():
            thread.join()

        try:
            self.store.unregister_runtime(self.instance_id)
        finally:
            self._process_lock.release()

    def __enter__(self) -> "RuntimeLease":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.stop()
