"""Уведомления об истечении подписки и статус в /settings."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import scheduler
from config import get_settings
from core.constants import SUB_EXPIRY_WARN_DAYS
from core.services import subscription

TODAY = date(2026, 7, 21)


def _family(sub_until=None, name="Ивановы", fid=7):
    return SimpleNamespace(id=fid, name=name, sub_until=sub_until, digest_enabled=True)


# --- чистая логика поводов ---


def test_no_subscription_no_notice():
    assert subscription.days_until_expiry(_family(), TODAY) is None
    assert subscription.expiry_notice(_family(), TODAY) is None
    assert subscription.operator_notice(_family(), TODAY) is None


def test_notice_three_days_before():
    family = _family(sub_until=date(2026, 7, 24))  # +3
    text = subscription.expiry_notice(family, TODAY)
    assert text is not None
    assert f"через {SUB_EXPIRY_WARN_DAYS}" in text and "24.07.2026" in text


def test_notice_on_last_day():
    text = subscription.expiry_notice(_family(sub_until=TODAY), TODAY)
    assert text is not None and "сегодня" in text


@pytest.mark.parametrize("delta", [1, 2, 4, 10, -1, -5])
def test_silent_on_other_days(delta):
    """Молчим и за 2 дня, и после истечения: про лимиты скажет denial_text."""
    family = _family(sub_until=date.fromordinal(TODAY.toordinal() + delta))
    assert subscription.expiry_notice(family, TODAY) is None


def test_operator_notice_carries_family_id():
    family = _family(sub_until=TODAY, fid=42)
    text = subscription.operator_notice(family, TODAY)
    assert "42" in text and "Ивановы" in text and "сегодня" in text


def test_operator_notice_handles_unnamed_family():
    text = subscription.operator_notice(_family(sub_until=TODAY, name=None), TODAY)
    assert "без имени" in text


# --- строка статуса в /settings ---


def test_status_line_without_subscription():
    assert "нет" in subscription.status_line(_family(), TODAY)


def test_status_line_active():
    line = subscription.status_line(_family(sub_until=date(2026, 8, 1)), TODAY)
    assert "активна до 01.08.2026" in line


def test_status_line_on_last_day_is_still_active():
    """sub_until включительно — в этот день подписка еще работает."""
    assert "активна" in subscription.status_line(_family(sub_until=TODAY), TODAY)


def test_status_line_expired():
    line = subscription.status_line(_family(sub_until=date(2026, 7, 20)), TODAY)
    assert "истекла 20.07.2026" in line


# --- рассылка ---


async def test_scheduler_notifies_admins_and_operator(monkeypatch):
    monkeypatch.setattr(get_settings(), "superadmin_ids", [999], raising=False)

    async def fake_admins(session, *, family_id):
        return [SimpleNamespace(telegram_user_id=111)]

    monkeypatch.setattr(scheduler, "get_admins", fake_admins)
    bot = AsyncMock()

    await scheduler._send_subscription_notice(
        bot, _sessionmaker(), _family(sub_until=TODAY), TODAY
    )

    targets = [c.args[0] for c in bot.send_message.await_args_list]
    assert targets == [111, 999]
    assert "7" in bot.send_message.await_args_list[1].args[1]  # id семьи оператору


async def test_scheduler_silent_without_reason(monkeypatch):
    bot = AsyncMock()
    await scheduler._send_subscription_notice(
        bot, _sessionmaker(), _family(sub_until=date(2026, 9, 1)), TODAY
    )
    bot.send_message.assert_not_awaited()


async def test_notice_ignores_digest_disabled(monkeypatch):
    """Платежное уведомление не должно гаситься выключенным дайджестом."""
    monkeypatch.setattr(get_settings(), "superadmin_ids", [], raising=False)

    async def fake_admins(session, *, family_id):
        return [SimpleNamespace(telegram_user_id=111)]

    monkeypatch.setattr(scheduler, "get_admins", fake_admins)
    monkeypatch.setattr(scheduler, "_send_family_digest", AsyncMock())
    monkeypatch.setattr(scheduler, "_send_plan_reminder", AsyncMock())
    bot = AsyncMock()
    family = _family(sub_until=TODAY)
    family.digest_enabled = False

    await scheduler._process_due_family(bot, _sessionmaker(), family, TODAY)

    bot.send_message.assert_awaited_once()


def _sessionmaker():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield None

    return _session
