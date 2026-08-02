from pathlib import Path
from typing import Any

import adp_orchestrator.app as app_module
from adp_orchestrator.config import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        slack_bot_token="xoxb-valid-placeholder",
        slack_app_token="xapp-valid-placeholder",
        adp_control_channel_id="C_CONTROL",
        adp_human_requests_channel_id="C_HUMAN",
        adp_daily_channel_id="C_DAILY",
        adp_db_path=tmp_path / "orchestrator.sqlite3",
    )


def test_slack_app_processes_listener_before_acknowledgement(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    captured: dict[str, object] = {}
    fake_app = object()

    def create_fake_app(**kwargs: object) -> object:
        captured.update(kwargs)
        return fake_app

    monkeypatch.setattr(app_module, "App", create_fake_app)

    result = app_module.create_slack_app(settings(tmp_path))

    assert result is fake_app
    assert captured["token"] == "xoxb-valid-placeholder"
    assert captured["process_before_response"] is True
