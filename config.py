from functools import lru_cache
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    db_url: str = "sqlite+aiosqlite:///./data/chef.db"
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"
    claude_model: str = "claude-sonnet-4-6"
    conversation_enabled: bool = False
    # Дефолты SDK — таймаут 10 минут и 2 ретрая, то есть до ~30 минут на один
    # зависший вызов. Все это время открыта сессия БД (мидлварь держит ее на
    # весь хендлер), на Postgres это соединение в idle-in-transaction.
    # Таймаут ретраится, поэтому потолок по времени = timeout * (retries + 1).
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 1
    # FSM-состояние: без REDIS_URL живет в памяти процесса и гибнет при рестарте
    # (человек теряет прогресс онбординга, админ — доступ к готовому черновику).
    redis_url: str | None = None
    # Срок жизни заброшенного диалога и осиротевшего черновика меню — одно
    # значение на оба, иначе состояние и данные разъедутся.
    fsm_ttl_hours: int = 24

    # спека §6: разовый (пожизненный) триал на семью + месячный anti-abuse потолок
    trial_menu_gen_limit: int = 4
    trial_replace_limit: int = 15
    trial_recipe_limit: int = 15
    trial_shopping_limit: int = 10
    monthly_token_cap_per_family: int = 500_000
    # генерация профиля идет ДО создания семьи, поэтому вне триал-лимитов:
    # считаем попытки по telegram_user_id за сутки, иначе это бесплатный
    # LLM-вызов на аккаунт, повторяемый бесконечно
    onboarding_daily_limit: int = 5
    # месячный потолок токенов семьи с активной подпиской (выдана /grant)
    sub_monthly_token_cap_per_family: int = 600_000

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
