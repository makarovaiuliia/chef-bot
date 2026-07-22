from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bot.scheduler as scheduler
from bot.scheduler import families_due
from config import get_settings

# 2026-07-21 02:07 UTC == 09:07 в Бангкоке (UTC+7)
NOW = datetime(2026, 7, 21, 2, 7, tzinfo=UTC)


def _family(fid, tz="Asia/Bangkok", hour=9, enabled=True):
    return SimpleNamespace(id=fid, timezone=tz, digest_hour=hour, digest_enabled=enabled)


def test_due_when_local_hour_matches():
    fams = [_family(1)]
    assert families_due(fams, now=NOW, last_sent={}) == fams


def test_not_due_wrong_hour():
    assert families_due([_family(1, hour=8)], now=NOW, last_sent={}) == []


def test_not_due_when_already_sent_today():
    bkk_today = date(2026, 7, 21)
    assert families_due([_family(1)], now=NOW, last_sent={1: bkk_today}) == []


def test_due_respects_timezone():
    # в UTC сейчас 02 часа — семья с UTC и hour=2 due, с hour=9 нет
    assert families_due([_family(1, tz="UTC", hour=2)], now=NOW, last_sent={}) != []
    assert families_due([_family(2, tz="UTC", hour=9)], now=NOW, last_sent={}) == []


def test_invalid_timezone_falls_back_to_utc():
    fams = [_family(1, tz="Каир", hour=2)]
    assert families_due(fams, now=NOW, last_sent={}) == fams


def test_digest_disabled_family_still_due():
    # семья с выключенным дайджестом остается due — для напоминания о планировании
    fams = [_family(1, enabled=False)]
    assert families_due(fams, now=NOW, last_sent={}) == fams


async def test_tick_family_marks_last_sent_on_success(monkeypatch):
    async def ok(bot, sessionmaker, family, today):
        return None

    monkeypatch.setattr(scheduler, "_process_due_family", ok)
    fam = _family(1)
    last_sent: dict[int, date] = {}
    await scheduler._tick_family(None, None, fam, NOW, last_sent)
    assert last_sent[1] == date(2026, 7, 21)


async def test_tick_family_does_not_mark_last_sent_on_failure(monkeypatch):
    async def boom(bot, sessionmaker, family, today):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_process_due_family", boom)
    fam = _family(1)
    last_sent: dict[int, date] = {}
    await scheduler._tick_family(None, None, fam, NOW, last_sent)
    assert 1 not in last_sent


async def test_reminder_sent_even_when_digest_disabled(monkeypatch):
    # два if'а в _process_due_family независимы: digest_enabled=False не должен
    # гасить напоминание о планировании (регрессия на будущий "упроститель").
    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    digest_mock = AsyncMock()
    reminder_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_family_digest", digest_mock)
    monkeypatch.setattr(scheduler, "_send_plan_reminder", reminder_mock)
    fam = _family(1, enabled=False)

    await scheduler._process_due_family(None, None, fam, date(2026, 7, 21))

    digest_mock.assert_not_awaited()
    reminder_mock.assert_awaited_once()


async def test_reminder_gated_by_planning_flag(monkeypatch):
    # обратная сторона: выключенный флаг не должен мешать дайджесту.
    monkeypatch.setattr(get_settings(), "planning_enabled", False)
    digest_mock = AsyncMock()
    reminder_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_family_digest", digest_mock)
    monkeypatch.setattr(scheduler, "_send_plan_reminder", reminder_mock)
    fam = _family(1, enabled=True)

    await scheduler._process_due_family(None, None, fam, date(2026, 7, 21))

    digest_mock.assert_awaited_once()
    reminder_mock.assert_not_awaited()
