from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    db_url: str = "sqlite+aiosqlite:///./data/chef.db"
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"
    claude_model: str = "claude-sonnet-4-6"
    conversation_enabled: bool = False
    planning_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
