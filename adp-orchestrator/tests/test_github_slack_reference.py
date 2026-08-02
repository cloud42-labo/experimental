from pathlib import Path

import pytest

from adp_orchestrator.events import HandoffEvent
from adp_orchestrator.github_adapter import GitHubAdapterError, GitHubReference
from adp_orchestrator.idempotency import IdempotencyStore
from adp_orchestrator.router import EventRouter, RouteResult
from adp_orchestrator.service import OrchestrationService, format_github_reference


class RecordingTaskRepository:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []

    def record(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))


class RecordingAgentActivator:
    def __init__(self) -> None:
        self.records: list[tuple[HandoffEvent, RouteResult]] = []

    def enqueue(self, event: HandoffEvent, result: RouteResult) -> None:
        self.records.append((event, result))


class FakeGitHubReferenceClient:
    def __init__(self, reference: GitHubReference | None = None) -> None:
        self.reference = reference
        self.urls: list[str] = []

    def fetch(self, url: str) -> GitHubReference:
        self.urls.append(url)
        if self.reference is None:
            raise GitHubAdapterError("safe failure")
        return self.reference


def make_event(**overrides: object) -> HandoffEvent:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "event_id": "event-github-1",
        "task_id": "ADP-013",
        "correlation_id": "correlation-github-1",
        "from_agent": "chris",
        "to_agent": "claude",
        "event_type": "task_assigned",
        "status": "ready",
        "summary": "Read the linked GitHub work item",
        "github_url": "https://github.com/cloud42-labo/experimental/issues/59",
        "requires_human": False,
        "attempt": 1,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return HandoffEvent.model_validate(payload)


def make_service(
    tmp_path: Path,
    client: FakeGitHubReferenceClient,
) -> tuple[OrchestrationService, RecordingTaskRepository, RecordingAgentActivator]:
    tasks = RecordingTaskRepository()
    agents = RecordingAgentActivator()
    subject = OrchestrationService(
        router=EventRouter(IdempotencyStore(tmp_path / "orchestrator.sqlite3")),
        task_repository=tasks,
        agent_activator=agents,
        github_reference_client=client,  # type: ignore[arg-type]
    )
    return subject, tasks, agents


def test_issue_reference_is_added_to_route_result_and_adapter_records(
    tmp_path: Path,
) -> None:
    reference = GitHubReference(
        kind="issue",
        owner="cloud42-labo",
        repository="experimental",
        number=59,
        title="ADP-013: GitHub参照結果をSlackスレッドへ返す",
        state="open",
        html_url="https://github.com/cloud42-labo/experimental/issues/59",
    )
    client = FakeGitHubReferenceClient(reference)
    subject, tasks, agents = make_service(tmp_path, client)

    result = subject.handle(make_event())

    assert client.urls == ["https://github.com/cloud42-labo/experimental/issues/59"]
    assert "GitHub Issue: cloud42-labo/experimental#59 [open]" in result.message
    assert reference.title in result.message
    assert tasks.records[0][1] == result
    assert agents.records[0][1] == result


def test_pull_request_summary_contains_state_flags_and_base() -> None:
    reference = GitHubReference(
        kind="pull_request",
        owner="cloud42-labo",
        repository="experimental",
        number=60,
        title="Implement ADP-013",
        state="open",
        html_url="https://github.com/cloud42-labo/experimental/pull/60",
        draft=True,
        merged=False,
        head_sha="abc123",
        base_branch="main",
    )

    summary = format_github_reference(reference)

    assert "GitHub PR: cloud42-labo/experimental#60 [open, draft]" in summary
    assert "Implement ADP-013 -> main" in summary
    assert reference.html_url in summary


def test_github_fetch_failure_rolls_back_event_for_exact_retry(
    tmp_path: Path,
) -> None:
    failing_client = FakeGitHubReferenceClient()
    subject, tasks, agents = make_service(tmp_path, failing_client)
    event = make_event()

    with pytest.raises(GitHubAdapterError, match="safe failure"):
        subject.handle(event)

    assert tasks.records == []
    assert agents.records == []

    reference = GitHubReference(
        kind="issue",
        owner="cloud42-labo",
        repository="experimental",
        number=59,
        title="Retry succeeds",
        state="open",
        html_url="https://github.com/cloud42-labo/experimental/issues/59",
    )
    subject.github_reference_client = FakeGitHubReferenceClient(reference)  # type: ignore[assignment]

    result = subject.handle(event)

    assert result.kind == "accepted"
    assert "Retry succeeds" in result.message
    assert len(tasks.records) == 1
    assert len(agents.records) == 1


def test_event_without_github_url_does_not_call_client(tmp_path: Path) -> None:
    reference = GitHubReference(
        kind="issue",
        owner="cloud42-labo",
        repository="experimental",
        number=59,
        title="Unused",
        state="open",
        html_url="https://github.com/cloud42-labo/experimental/issues/59",
    )
    client = FakeGitHubReferenceClient(reference)
    subject, _, _ = make_service(tmp_path, client)

    result = subject.handle(make_event(github_url=None))

    assert result.kind == "accepted"
    assert client.urls == []
    assert "GitHub Issue:" not in result.message
