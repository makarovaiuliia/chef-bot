from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    db_url: str = "sqlite+aiosqlite:///./data/chef.db"
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"
    claude_model: str = "claude-sonnet-4-6"
    conversation_enabled: bool = False

    # спека §6: разовый (пожизненный) триал на семью + месячный anti-abuse потолок
    trial_menu_gen_limit: int = 4
    trial_replace_limit: int = 15
    trial_recipe_limit: int = 15
    monthly_token_cap_per_family: int = 500_000

    # суперадмины — операторы продукта, ОТДЕЛЬНЫЙ слой доверия, не роль семьи (роадмап)
    superadmin_ids: Annotated[list[int], NoDecode] = []

    @field_validator("superadmin_ids", mode="before")
    @classmethod
    def _parse_superadmin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
