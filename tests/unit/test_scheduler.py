from datetime import UTC, date, datetime
from types import SimpleNamespace

from bot.scheduler import families_due

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
