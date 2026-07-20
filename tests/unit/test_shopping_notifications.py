from core.db import FamilyMember
from core.services.shopping_list import build_added_notifications


def _member(tg_id: int, name: str) -> FamilyMember:
    return FamilyMember(family_id=1, telegram_user_id=tg_id, display_name=name)


def test_notifies_everyone_except_adder():
    adder = _member(1, "Вова")
    members = [adder, _member(2, "Юля"), _member(3, "Мама")]
    pairs = build_added_notifications(adder, members, ["молоко", "хлеб"])
    ids = [tg for tg, _ in pairs]
    assert ids == [2, 3]
    assert all("Вова добавил в список: молоко, хлеб" in text for _, text in pairs)


def test_no_names_no_notifications():
    adder = _member(1, "Вова")
    assert build_added_notifications(adder, [adder, _member(2, "Юля")], []) == []
