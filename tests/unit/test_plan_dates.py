from datetime import date

from core.services.menu_planner import next_monday, parse_start_date

TODAY = date(2026, 7, 22)  # среда


def test_next_monday_from_wednesday():
    assert next_monday(TODAY) == date(2026, 7, 27)


def test_next_monday_on_monday_is_today():
    assert next_monday(date(2026, 7, 27)) == date(2026, 7, 27)


def test_parse_start_date_formats():
    assert parse_start_date("25.07.2026", TODAY) == date(2026, 7, 25)
    assert parse_start_date("2026-07-25", TODAY) == date(2026, 7, 25)
    assert parse_start_date("25.07", TODAY) == date(2026, 7, 25)


def test_parse_start_date_short_form_rolls_to_next_year():
    assert parse_start_date("05.01", TODAY) == date(2027, 1, 5)


def test_parse_start_date_rejects_past_and_garbage():
    assert parse_start_date("01.07.2026", TODAY) is None
    assert parse_start_date("послезавтра", TODAY) is None


def test_parse_start_date_feb_29_short_form():
    # ближайший будущий 29.02 от лета 2027 — в 2028 (високосный)
    assert parse_start_date("29.02", date(2027, 7, 1)) == date(2028, 2, 29)


def test_user_message_uses_russian_weekdays():
    from types import SimpleNamespace

    from core.services.menu_planner import _user_message

    fam = SimpleNamespace(plan_slots=["lunch", "dinner"], profile_md="п")
    msg = _user_message(fam, [date(2026, 7, 27)])  # понедельник
    assert "пн" in msg and "Mon" not in msg
