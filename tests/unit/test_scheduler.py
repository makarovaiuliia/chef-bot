from datetime import datetime
from zoneinfo import ZoneInfo

from bot.scheduler import seconds_until_next

BKK = ZoneInfo("Asia/Bangkok")


def test_target_later_today():
    now = datetime(2026, 5, 27, 6, 0, tzinfo=BKK)
    secs = seconds_until_next(8, 0, BKK, now=now)
    assert secs == 2 * 3600


def test_target_already_passed_today_rolls_to_tomorrow():
    now = datetime(2026, 5, 27, 9, 0, tzinfo=BKK)
    secs = seconds_until_next(8, 0, BKK, now=now)
    assert secs == 23 * 3600


def test_exact_match_rolls_to_tomorrow():
    now = datetime(2026, 5, 27, 8, 0, tzinfo=BKK)
    secs = seconds_until_next(8, 0, BKK, now=now)
    assert secs == 24 * 3600


def test_handles_now_in_different_tz():
    now_utc = datetime(2026, 5, 27, 0, 0, tzinfo=ZoneInfo("UTC"))
    secs = seconds_until_next(8, 0, BKK, now=now_utc)
    assert secs == 1 * 3600
