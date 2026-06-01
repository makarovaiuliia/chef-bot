"""Russian date formatting shared across the digest and menu views."""
from datetime import date as DateType

_WEEKDAYS_SHORT_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_MONTHS_RU_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def format_date_short(d: DateType) -> str:
    """e.g. date(2026, 6, 1) -> 'пн, 1 июня'."""
    return f"{_WEEKDAYS_SHORT_RU[d.weekday()]}, {d.day} {_MONTHS_RU_GENITIVE[d.month - 1]}"
