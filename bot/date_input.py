"""Parse user-typed dates for the /plan wizard.

Accepts Russian shortcuts (сегодня/завтра/послезавтра) and numeric formats
(DD.MM, DD.MM.YYYY, YYYY-MM-DD). Rejects past dates and unparseable input.
"""
from datetime import date as DateType
from datetime import timedelta

_SHORTCUTS = {
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
}


def _try_iso(text: str) -> DateType | None:
    try:
        return DateType.fromisoformat(text)
    except ValueError:
        return None


def _try_dotted(text: str, today: DateType) -> DateType | None:
    parts = text.split(".")
    if len(parts) not in (2, 3):
        return None
    try:
        day = int(parts[0])
        month = int(parts[1])
        year = int(parts[2]) if len(parts) == 3 else today.year
    except ValueError:
        return None
    try:
        return DateType(year, month, day)
    except ValueError:
        return None


def parse_date_input(text: str, *, today: DateType) -> DateType | None:
    """Return parsed date, or None if invalid / in the past."""
    if not text:
        return None
    stripped = text.strip().lower()
    if not stripped:
        return None

    if stripped in _SHORTCUTS:
        return today + timedelta(days=_SHORTCUTS[stripped])

    parsed = _try_iso(stripped) or _try_dotted(stripped, today)
    if parsed is None:
        return None
    if parsed < today:
        return None
    return parsed
