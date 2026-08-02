from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    slack_bot_token: str
    slack_app_token: str
    adp_control_channel_id: str
    adp_human_requests_channel_id: str
    adp_daily_channel_id: str
    adp_db_path: Path = Path(".adp/orchestrator.sqlite3")
    adp_lock_lease_seconds: int = 3600
    adp_runtime_lease_seconds: int = 60
    adp_runtime_heartbeat_seconds: int = 10
    notion_token: SecretStr | None = None
    github_token: SecretStr | None = None

    @field_validator("slack_bot_token")
    @classmethod
    def validate_bot_token(cls, value: str) -> str:
        if not value.startswith("xoxb-"):
            raise ValueError("SLACK_BOT_TOKEN must be a Slack bot token")
        return value

    @field_validator("slack_app_token")
    @classmethod
    def validate_app_token(cls, value: str) -> str:
        if not value.startswith("xapp-"):
            raise ValueError("SLACK_APP_TOKEN must be a Slack app-level token")
        return value

    @field_validator(
        "adp_control_channel_id",
        "adp_human_requests_channel_id",
        "adp_daily_channel_id",
    )
    @classmethod
    def validate_channel_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Slack channel ID must not be empty")
        return value.strip()

    @field_validator("adp_lock_lease_seconds")
    @classmethod
    def validate_lock_lease_seconds(cls, value: int) -> int:
        if value < 30:
            raise ValueError("ADP_LOCK_LEASE_SECONDS must be at least 30")
        return value

    @field_validator("adp_runtime_lease_seconds")
    @classmethod
    def validate_runtime_lease_seconds(cls, value: int) -> int:
        if value < 30 or value > 3600:
            raise ValueError(
                "ADP_RUNTIME_LEASE_SECONDS must be between 30 and 3600"
            )
        return value

    @field_validator("adp_runtime_heartbeat_seconds")
    @classmethod
    def validate_runtime_heartbeat_seconds(cls, value: int) -> int:
        if value < 1 or value > 300:
            raise ValueError(
                "ADP_RUNTIME_HEARTBEAT_SECONDS must be between 1 and 300"
            )
        return value

    @model_validator(mode="after")
    def validate_runtime_lease_ratio(self) -> "Settings":
        if self.adp_runtime_heartbeat_seconds * 3 > self.adp_runtime_lease_seconds:
            raise ValueError(
                "ADP_RUNTIME_HEARTBEAT_SECONDS must be at most one third "
                "of ADP_RUNTIME_LEASE_SECONDS"
            )
        return self
