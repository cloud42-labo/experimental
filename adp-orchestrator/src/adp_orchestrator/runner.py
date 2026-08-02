from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .agent_queue import AgentHandoff, SQLiteAgentQueue
from .events import HandoffEvent

RunnerAgent = Literal["claude", "codex", "gemini"]


class SlackThreadClient(Protocol):
    def chat_postMessage(self, **kwargs: Any) -> Any: ...


class RunnerError(RuntimeError):
    """Safe runner error that never includes prompts, tokens, or process output."""


@dataclass(frozen=True)
class RunnerResult:
    status: Literal["done", "blocked"]
    summary: str
    requires_human: bool = False
    github_url: str | None = None
    notion_url: str | None = None


@dataclass(frozen=True)
class LocalRunnerConfig:
    agent: RunnerAgent
    command: tuple[str, ...]
    timeout_seconds: float = 1800.0
    lease_seconds: float = 2100.0

    @classmethod
    def from_environment(cls, agent: RunnerAgent) -> "LocalRunnerConfig":
        variable = f"ADP_{agent.upper()}_COMMAND"
        raw = os.getenv(variable, "").strip()
        if not raw:
            raise RunnerError(f"{variable} is not configured")
        command = tuple(shlex.split(raw, posix=os.name != "nt"))
        if not command:
            raise RunnerError(f"{variable} is empty")
        return cls(agent=agent, command=command)


class CommandExecutor(Protocol):
    def execute(
        self,
        command: tuple[str, ...],
        payload: str,
        timeout_seconds: float,
    ) -> str: ...


class SubprocessCommandExecutor:
    """Invoke an existing local CLI without a shell or paid API integration."""

    def execute(
        self,
        command: tuple[str, ...],
        payload: str,
        timeout_seconds: float,
    ) -> str:
        try:
            completed = subprocess.run(
                list(command),
                input=payload,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RunnerError("Local AI command could not be completed") from None
        if completed.returncode != 0:
            raise RunnerError("Local AI command returned a failure status")
        return completed.stdout


def _safe_summary(value: object) -> str:
    text = str(value).strip()
    if not text:
        raise RunnerError("Local AI result summary is empty")
    return text[:2000]


def parse_runner_result(output: str) -> RunnerResult:
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        raise RunnerError("Local AI command did not return valid JSON") from None
    if not isinstance(payload, dict):
        raise RunnerError("Local AI command result must be a JSON object")
    status = payload.get("status")
    if status not in {"done", "blocked"}:
        raise RunnerError("Local AI result status must be done or blocked")
    requires_human = bool(payload.get("requires_human", status == "blocked"))
    return RunnerResult(
        status=status,
        summary=_safe_summary(payload.get("summary", "")),
        requires_human=requires_human,
        github_url=str(payload["github_url"]) if payload.get("github_url") else None,
        notion_url=str(payload["notion_url"]) if payload.get("notion_url") else None,
    )


def build_cli_payload(handoff: AgentHandoff) -> str:
    event = HandoffEvent.model_validate_json(handoff.event_json)
    payload = {
        "schema_version": "1.0",
        "task_id": event.task_id,
        "correlation_id": event.correlation_id,
        "agent": handoff.target_agent,
        "event_type": event.event_type,
        "summary": event.summary,
        "github_url": None if event.github_url is None else str(event.github_url),
        "notion_url": None if event.notion_url is None else str(event.notion_url),
        "attempt": handoff.attempts,
        "response_contract": {
            "status": "done|blocked",
            "summary": "safe result summary",
            "requires_human": "boolean",
            "github_url": "optional URL",
            "notion_url": "optional URL",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


class LocalAgentRunner:
    def __init__(
        self,
        queue: SQLiteAgentQueue,
        slack_client: SlackThreadClient,
        config: LocalRunnerConfig,
        executor: CommandExecutor | None = None,
    ) -> None:
        self.queue = queue
        self.slack_client = slack_client
        self.config = config
        self.executor = executor or SubprocessCommandExecutor()

    def _post_event(
        self,
        handoff: AgentHandoff,
        event_type: str,
        status: str,
        summary: str,
        *,
        requires_human: bool = False,
        github_url: str | None = None,
        notion_url: str | None = None,
    ) -> None:
        original = HandoffEvent.model_validate_json(handoff.event_json)
        is_started = event_type == "work_started"
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "event_id": f"runner-{uuid.uuid4().hex}",
            "task_id": original.task_id,
            "correlation_id": original.correlation_id,
            "from_agent": "chris" if is_started else self.config.agent,
            "to_agent": self.config.agent if is_started else ("human" if requires_human else "chris"),
            "event_type": event_type,
            "status": status,
            "summary": summary,
            "requires_human": requires_human,
            "attempt": original.attempt,
            "max_attempts": original.max_attempts,
        }
        if github_url:
            payload["github_url"] = github_url
        if notion_url:
            payload["notion_url"] = notion_url
        HandoffEvent.model_validate(payload)
        self.slack_client.chat_postMessage(
            channel=handoff.channel_id,
            thread_ts=handoff.thread_ts,
            text=json.dumps(payload, ensure_ascii=False),
        )

    def run_once(self) -> bool:
        handoff = self.queue.claim_next(
            self.config.agent,
            lease_seconds=self.config.lease_seconds,
        )
        if handoff is None:
            return False
        if not handoff.channel_id:
            self.queue.fail(handoff.idempotency_key, "Slack channel context is unavailable")
            raise RunnerError("Slack channel context is unavailable")

        try:
            self._post_event(
                handoff,
                "work_started",
                "running",
                "Local runner started the assigned work.",
            )
            output = self.executor.execute(
                self.config.command,
                build_cli_payload(handoff),
                self.config.timeout_seconds,
            )
            result = parse_runner_result(output)
            if result.requires_human or result.status == "blocked":
                self._post_event(
                    handoff,
                    "human_required",
                    "blocked",
                    result.summary,
                    requires_human=True,
                    github_url=result.github_url,
                    notion_url=result.notion_url,
                )
            else:
                self._post_event(
                    handoff,
                    "work_completed",
                    "done",
                    result.summary,
                    github_url=result.github_url,
                    notion_url=result.notion_url,
                )
        except Exception as exc:
            self.queue.fail(handoff.idempotency_key, "Local runner execution failed")
            if isinstance(exc, RunnerError):
                raise
            raise RunnerError("Local runner execution failed") from None

        self.queue.complete(handoff.idempotency_key)
        return True


def run_from_environment(agent: RunnerAgent, db_path: Path | str | None = None) -> int:
    from slack_sdk import WebClient

    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token.startswith("xoxb-"):
        raise RunnerError("SLACK_BOT_TOKEN is not configured")
    queue = SQLiteAgentQueue(db_path)
    runner = LocalAgentRunner(
        queue,
        WebClient(token=token),
        LocalRunnerConfig.from_environment(agent),
    )
    return 0 if runner.run_once() else 2
