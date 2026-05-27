from datetime import date

import pytest

from bot.date_input import parse_date_input

TODAY = date(2026, 5, 27)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("сегодня", date(2026, 5, 27)),
        ("Сегодня", date(2026, 5, 27)),
        ("завтра", date(2026, 5, 28)),
        ("послезавтра", date(2026, 5, 29)),
        ("28.05", date(2026, 5, 28)),
        ("28.05.2026", date(2026, 5, 28)),
        ("2026-05-28", date(2026, 5, 28)),
        ("  завтра  ", date(2026, 5, 28)),
    ],
)
def test_parses_valid_input(text, expected):
    assert parse_date_input(text, today=TODAY) == expected


def test_short_date_in_past_rejected():
    # 01.01 with today=2026-05-27 — that's Jan 1 of THIS year, in the past.
    # User must spell out year if they really mean next January.
    assert parse_date_input("01.01", today=TODAY) is None


def test_short_date_same_month_future_uses_current_year():
    assert parse_date_input("30.05", today=TODAY) == date(2026, 5, 30)


def test_explicit_year_future_accepted():
    assert parse_date_input("01.01.2027", today=TODAY) == date(2027, 1, 1)


@pytest.mark.parametrize(
    "text",
    ["", "вчера", "не дата", "32.05", "2026-13-01", "abc.def"],
)
def test_returns_none_for_invalid_input(text):
    assert parse_date_input(text, today=TODAY) is None


def test_returns_none_for_past_date():
    assert parse_date_input("20.05", today=TODAY) is None
    assert parse_date_input("2026-05-20", today=TODAY) is None
