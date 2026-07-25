from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bot.scheduler as scheduler
from bot.scheduler import families_due
from config import get_settings


def _fake_sessionmaker():
    @asynccontextmanager
    async def _session():
        yield None

    return _session

# 2026-07-21 02:07 UTC == 09:07 в Бангкоке (UTC+7)
NOW = datetime(2026, 7, 21, 2, 7, tzinfo=UTC)


def _family(fid, tz="Asia/Bangkok", hour=9, enabled=True, sub_until=None, last_digest_on=None):
    return SimpleNamespace(
        id=fid, timezone=tz, digest_hour=hour, digest_enabled=enabled,
        sub_until=sub_until, last_digest_on=last_digest_on,
    )


def test_due_when_local_hour_matches():
    fams = [_family(1)]
    assert families_due(fams, now=NOW) == fams


def test_not_due_wrong_hour():
    assert families_due([_family(1, hour=8)], now=NOW) == []


def test_not_due_when_already_sent_today():
    bkk_today = date(2026, 7, 21)
    assert families_due([_family(1, last_digest_on=bkk_today)], now=NOW) == []


def test_due_respects_timezone():
    # в UTC сейчас 02 часа — семья с UTC и hour=2 due, с hour=9 нет
    assert families_due([_family(1, tz="UTC", hour=2)], now=NOW) != []
    assert families_due([_family(2, tz="UTC", hour=9)], now=NOW) == []


def test_invalid_timezone_falls_back_to_utc():
    fams = [_family(1, tz="Каир", hour=2)]
    assert families_due(fams, now=NOW) == fams


def test_due_across_dst_transition():
    # Europe/Berlin: зимой UTC+1 (9:00 = 08:00 UTC), летом UTC+2 (9:00 = 07:00 UTC)
    fam = [_family(1, tz="Europe/Berlin", hour=9)]
    winter = datetime(2026, 1, 15, 8, 5, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 7, 5, tzinfo=UTC)
    assert families_due(fam, now=winter) == fam
    assert families_due(fam, now=summer) == fam


def test_digest_disabled_family_still_due():
    # семья с выключенным дайджестом остается due — для напоминания о планировании
    fams = [_family(1, enabled=False)]
    assert families_due(fams, now=NOW) == fams


def _patch_claim(monkeypatch, *, granted=True):
    """Заявка в БД: возвращает granted и записывает вызовы release."""
    released = []

    async def fake_claim(session, *, family_id, local_date):
        return granted

    async def fake_release(session, *, family_id, previous):
        released.append((family_id, previous))

    monkeypatch.setattr(scheduler.repositories, "claim_digest_slot", fake_claim)
    monkeypatch.setattr(scheduler.repositories, "release_digest_slot", fake_release)
    return released


async def test_tick_family_marks_sent_on_success(monkeypatch):
    async def ok(bot, sessionmaker, family, today):
        return None

    monkeypatch.setattr(scheduler, "_process_due_family", ok)
    released = _patch_claim(monkeypatch)
    fam = _family(1)

    await scheduler._tick_family(None, _fake_sessionmaker(), fam, NOW)

    assert fam.last_digest_on == date(2026, 7, 21)
    assert released == []


async def test_tick_family_releases_claim_on_failure(monkeypatch):
    """Упавшая рассылка возвращает заявку — ретрай на следующем тике."""

    async def boom(bot, sessionmaker, family, today):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_process_due_family", boom)
    released = _patch_claim(monkeypatch)
    fam = _family(1)

    await scheduler._tick_family(None, _fake_sessionmaker(), fam, NOW)

    assert fam.last_digest_on is None  # заявка снята
    assert released == [(1, None)]


async def test_tick_family_skips_when_claim_lost(monkeypatch):
    """Другая реплика уже забрала право — рассылку не начинаем."""
    calls = []

    async def process(bot, sessionmaker, family, today):
        calls.append(1)

    monkeypatch.setattr(scheduler, "_process_due_family", process)
    _patch_claim(monkeypatch, granted=False)

    await scheduler._tick_family(None, _fake_sessionmaker(), _family(1), NOW)

    assert calls == []


async def test_reminder_sent_even_when_digest_disabled(monkeypatch):
    # два if'а в _process_due_family независимы: digest_enabled=False не должен
    # гасить напоминание о планировании (регрессия на будущий "упроститель").
    digest_mock = AsyncMock()
    reminder_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_family_digest", digest_mock)
    monkeypatch.setattr(scheduler, "_send_plan_reminder", reminder_mock)
    fam = _family(1, enabled=False)

    await scheduler._process_due_family(None, None, fam, date(2026, 7, 21))

    digest_mock.assert_not_awaited()
    reminder_mock.assert_awaited_once()


async def test_reminder_skipped_when_trial_exhausted(monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)

    async def fake_due(session, *, family_id, today):
        return True

    async def fake_count(session, *, family_id, operation):
        return 1  # лимит исчерпан

    monkeypatch.setattr(scheduler.reminders, "plan_reminder_due", fake_due)
    monkeypatch.setattr(scheduler, "count_llm_operations", fake_count)
    bot = AsyncMock()

    await scheduler._send_plan_reminder(bot, _fake_sessionmaker(), _family(1), date(2026, 7, 22))

    bot.send_message.assert_not_awaited()


async def test_reminder_sent_when_subscribed_despite_exhausted_trial(monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)

    async def fake_due(session, *, family_id, today):
        return True

    async def fake_count(session, *, family_id, operation):
        return 1  # лимит триала исчерпан, но семья подписана

    async def fake_admins(session, *, family_id):
        return [SimpleNamespace(telegram_user_id=1)]

    monkeypatch.setattr(scheduler.reminders, "plan_reminder_due", fake_due)
    monkeypatch.setattr(scheduler, "count_llm_operations", fake_count)
    monkeypatch.setattr(scheduler, "get_admins", fake_admins)
    bot = AsyncMock()
    today = date(2026, 7, 22)
    fam = _family(1, sub_until=date(2026, 8, 1))  # today + 10

    await scheduler._send_plan_reminder(bot, _fake_sessionmaker(), fam, today)

    bot.send_message.assert_awaited()
