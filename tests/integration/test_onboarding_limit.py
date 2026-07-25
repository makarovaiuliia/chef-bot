"""Суточный лимит генерации профиля в онбординге (по telegram_user_id)."""
from datetime import UTC, datetime, timedelta

import pytest

from config import get_settings
from core.exceptions import OnboardingLimitExceeded
from core.repositories import (
    count_onboarding_attempts_today,
    count_onboarding_attempts_today_all,
)
from core.services.onboarding import (
    ensure_onboarding_attempt_allowed,
    onboarding_denial_text,
)


@pytest.fixture
def limit_of_three(monkeypatch):
    monkeypatch.setattr(get_settings(), "onboarding_daily_limit", 3, raising=False)
    return 3


async def test_attempts_allowed_up_to_limit(db_session, limit_of_three):
    for _ in range(limit_of_three):
        await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    assert (
        await count_onboarding_attempts_today(
            db_session, telegram_user_id=111, now=datetime.now(UTC)
        )
        == 3
    )


async def test_attempt_over_limit_raises(db_session, limit_of_three):
    for _ in range(limit_of_three):
        await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    with pytest.raises(OnboardingLimitExceeded) as exc:
        await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    assert exc.value.limit == 3
    # Отказ не должен записывать лишнюю попытку.
    assert (
        await count_onboarding_attempts_today(
            db_session, telegram_user_id=111, now=datetime.now(UTC)
        )
        == 3
    )


async def test_attempt_is_recorded_before_llm_call(db_session, limit_of_three):
    """Попытка пишется самим ensure_*, до всякого обращения к модели."""
    await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    assert (
        await count_onboarding_attempts_today(
            db_session, telegram_user_id=111, now=datetime.now(UTC)
        )
        == 1
    )


async def test_users_counted_separately(db_session, limit_of_three):
    for _ in range(limit_of_three):
        await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    # Другому юзеру лимит первого не мешает.
    await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=222)

    now = datetime.now(UTC)
    assert await count_onboarding_attempts_today(
        db_session, telegram_user_id=222, now=now
    ) == 1


async def test_counter_resets_next_day(db_session, limit_of_three):
    """Попытки прошлых суток не считаются: смотрим тем же счетчиком из «завтра»."""
    for _ in range(limit_of_three):
        await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)

    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert (
        await count_onboarding_attempts_today(
            db_session, telegram_user_id=111, now=tomorrow
        )
        == 0
    )
    # И лимит снова разрешает генерацию.
    await ensure_onboarding_attempt_allowed(
        db_session, telegram_user_id=111, now=tomorrow
    )


async def test_all_users_counter_for_admin(db_session, limit_of_three):
    await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=111)
    await ensure_onboarding_attempt_allowed(db_session, telegram_user_id=222)

    total = await count_onboarding_attempts_today_all(
        db_session, now=datetime.now(UTC)
    )
    assert total == 2


def test_denial_text_names_the_limit():
    text = onboarding_denial_text(OnboardingLimitExceeded(5))
    assert "5 попыток" in text and "завтра" in text
