import json
from pathlib import Path

import pytest

from adp_orchestrator.agent_queue import SQLiteAgentQueue
from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.outbox import DeferredDeliveryOutbox
from adp_orchestrator.router import RouteResult
from adp_orchestrator.runner import (
    LocalAgentRunner,
    LocalRunnerConfig,
    RunnerError,
    build_cli_payload,
    parse_runner_result,
)


class RecordingSlackClient:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.posts: list[dict[str, object]] = []

    def chat_postMessage(self, **kwargs: object) -> None:
        call = len(self.posts) + 1
        if self.fail_on_call == call:
            raise RuntimeError("temporary Slack failure")
        self.posts.append(kwargs)


class RecordingExecutor:
    def __init__(self, output: str, fail: bool = False) -> None:
        self.output = output
        self.fail = fail
        self.calls: list[tuple[tuple[str, ...], str, float]] = []

    def execute(self, command: tuple[str, ...], payload: str, timeout_seconds: float) -> str:
        self.calls.append((command, payload, timeout_seconds))
        if self.fail:
            raise RunnerError("safe command failure")
        return self.output


def make_event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "runner-assignment",
        "task_id": "ADP-016",
        "correlation_id": "runner-correlation",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Complete local runner E2E",
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def seed_queue(tmp_path: Path, event: HandoffEvent) -> SQLiteAgentQueue:
    db_path = tmp_path / "orchestrator.sqlite3"
    outbox = DeferredDeliveryOutbox(db_path)
    outbox.defer(
        idempotency_key=event.idempotency_key,
        event_json=event.model_dump_json(),
        channel_id="C0CONTROL",
        thread_ts="1234.5678",
        delay_seconds=60,
    )
    queue = SQLiteAgentQueue(db_path)
    queue.enqueue(
        event,
        RouteResult(
            kind="accepted",
            task_id=event.task_id,
            status="ready",
            message="queued",
            target_agent=event.to_agent,
        ),
    )
    return queue


def test_parse_runner_result_rejects_non_json_without_leaking_output() -> None:
    with pytest.raises(RunnerError, match="valid JSON") as error:
        parse_runner_result("secret prompt and token")
    assert "secret prompt" not in str(error.value)


def test_build_cli_payload_contains_contract_and_no_slack_context(tmp_path: Path) -> None:
    event = make_event()
    queue = seed_queue(tmp_path, event)
    handoff = queue.claim_next("claude")
    assert handoff is not None

    payload = json.loads(build_cli_payload(handoff))

    assert payload["task_id"] == "ADP-016"
    assert payload["agent"] == "claude"
    assert payload["response_contract"]["status"] == "done|blocked"
    assert "channel_id" not in payload
    assert "thread_ts" not in payload


def test_success_posts_started_and_completed_then_completes_queue(tmp_path: Path) -> None:
    event = make_event()
    queue = seed_queue(tmp_path, event)
    slack = RecordingSlackClient()
    executor = RecordingExecutor(json.dumps({"status": "done", "summary": "Implemented and tested"}))
    runner = LocalAgentRunner(
        queue,
        slack,
        LocalRunnerConfig(agent="claude", command=("claude", "--print")),
        executor,
    )

    assert runner.run_once() is True

    assert len(slack.posts) == 2
    started = json.loads(str(slack.posts[0]["text"]))
    completed = json.loads(str(slack.posts[1]["text"]))
    assert started["event_type"] == "work_started"
    assert completed["event_type"] == "work_completed"
    assert completed["status"] == "done"
    assert slack.posts[1]["channel"] == "C0CONTROL"
    assert slack.posts[1]["thread_ts"] == "1234.5678"
    stored = queue.get(event.idempotency_key)
    assert stored is not None
    assert stored.status == "completed"
    assert len(executor.calls) == 1


def test_blocked_result_posts_human_required(tmp_path: Path) -> None:
    event = make_event(to_agent="codex", event_type="review_requested", status="review")
    queue = seed_queue(tmp_path, event)
    slack = RecordingSlackClient()
    executor = RecordingExecutor(json.dumps({"status": "blocked", "summary": "Desktop login required"}))
    runner = LocalAgentRunner(
        queue,
        slack,
        LocalRunnerConfig(agent="codex", command=("codex", "exec")),
        executor,
    )

    assert runner.run_once() is True

    terminal = json.loads(str(slack.posts[-1]["text"]))
    assert terminal["event_type"] == "human_required"
    assert terminal["requires_human"] is True
    assert terminal["to_agent"] == "human"


def test_command_failure_requeues_for_retry(tmp_path: Path) -> None:
    event = make_event()
    queue = seed_queue(tmp_path, event)
    runner = LocalAgentRunner(
        queue,
        RecordingSlackClient(),
        LocalRunnerConfig(agent="claude", command=("claude", "--print")),
        RecordingExecutor("", fail=True),
    )

    with pytest.raises(RunnerError, match="safe command failure"):
        runner.run_once()

    stored = queue.get(event.idempotency_key)
    assert stored is not None
    assert stored.status == "pending"
    assert stored.last_error == "Local runner execution failed"


def test_slack_terminal_failure_requeues_and_does_not_complete(tmp_path: Path) -> None:
    event = make_event()
    queue = seed_queue(tmp_path, event)
    runner = LocalAgentRunner(
        queue,
        RecordingSlackClient(fail_on_call=2),
        LocalRunnerConfig(agent="claude", command=("claude", "--print")),
        RecordingExecutor(json.dumps({"status": "done", "summary": "Finished"})),
    )

    with pytest.raises(RunnerError, match="execution failed"):
        runner.run_once()

    stored = queue.get(event.idempotency_key)
    assert stored is not None
    assert stored.status == "pending"
