from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Validation errors intentionally mention only variable names and never include
    secret values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    slack_bot_token: str
    slack_app_token: str
    adp_control_channel_id: str
    adp_human_requests_channel_id: str
    adp_daily_channel_id: str
    adp_db_path: Path = Path(".adp/orchestrator.sqlite3")

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
