from datetime import date

from core.ru_format import format_date_short


def test_monday_first_of_june():
    assert format_date_short(date(2026, 6, 1)) == "пн, 1 июня"


def test_tuesday_second_of_june():
    assert format_date_short(date(2026, 6, 2)) == "вт, 2 июня"


def test_wednesday_27_may():
    assert format_date_short(date(2026, 5, 27)) == "ср, 27 мая"


def test_sunday_december():
    assert format_date_short(date(2026, 12, 6)) == "вс, 6 декабря"
