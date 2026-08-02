from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from adp_orchestrator.config import Settings


def base_settings(tmp_path: Path) -> dict[str, object]:
    return {
        "slack_bot_token": "xoxb-valid-placeholder",
        "slack_app_token": "xapp-valid-placeholder",
        "adp_control_channel_id": "C_CONTROL",
        "adp_human_requests_channel_id": "C_HUMAN",
        "adp_daily_channel_id": "C_DAILY",
        "adp_db_path": tmp_path / "orchestrator.sqlite3",
    }


def test_accepts_valid_configuration(tmp_path: Path) -> None:
    settings = Settings(**base_settings(tmp_path))
    assert settings.adp_db_path == tmp_path / "orchestrator.sqlite3"
    assert settings.adp_lock_lease_seconds == 3600
    assert settings.adp_runtime_lease_seconds == 60
    assert settings.adp_runtime_heartbeat_seconds == 10
    assert settings.notion_token is None
    assert settings.github_token is None


def test_accepts_custom_lock_and_runtime_leases(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    values["adp_lock_lease_seconds"] = 7200
    values["adp_runtime_lease_seconds"] = 90
    values["adp_runtime_heartbeat_seconds"] = 30

    settings = Settings(**values)

    assert settings.adp_lock_lease_seconds == 7200
    assert settings.adp_runtime_lease_seconds == 90
    assert settings.adp_runtime_heartbeat_seconds == 30


def test_rejects_too_short_lock_lease(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    values["adp_lock_lease_seconds"] = 29
    with pytest.raises(ValidationError) as exc_info:
        Settings(**values)
    assert "ADP_LOCK_LEASE_SECONDS" in str(exc_info.value)


def test_rejects_runtime_heartbeat_too_close_to_expiry(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    values["adp_runtime_lease_seconds"] = 60
    values["adp_runtime_heartbeat_seconds"] = 21

    with pytest.raises(ValidationError) as exc_info:
        Settings(**values)

    assert "ADP_RUNTIME_HEARTBEAT_SECONDS" in str(exc_info.value)


def test_accepts_optional_secret_tokens(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    values["notion_token"] = SecretStr("notion_secret")
    values["github_token"] = SecretStr("github_secret")

    settings = Settings(**values)

    assert settings.notion_token is not None
    assert settings.notion_token.get_secret_value() == "notion_secret"
    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "github_secret"


def test_invalid_bot_token_value_is_hidden(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    secret_value = "not-a-token-super-secret"
    values["slack_bot_token"] = secret_value

    with pytest.raises(ValidationError) as exc_info:
        Settings(**values)

    assert secret_value not in str(exc_info.value)
    assert "SLACK_BOT_TOKEN" in str(exc_info.value)


def test_invalid_app_token_value_is_hidden(tmp_path: Path) -> None:
    values = base_settings(tmp_path)
    secret_value = "not-an-app-token-super-secret"
    values["slack_app_token"] = secret_value

    with pytest.raises(ValidationError) as exc_info:
        Settings(**values)

    assert secret_value not in str(exc_info.value)
    assert "SLACK_APP_TOKEN" in str(exc_info.value)
