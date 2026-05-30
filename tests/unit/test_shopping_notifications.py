from core.db import FamilyMember
from core.services.shopping_list import build_add_notifications

VOVA = 100
JULIA = 200


def _member(uid: int) -> FamilyMember:
    return FamilyMember(family_id=1, telegram_user_id=uid, display_name=None)


def test_no_notifications_when_adder_is_not_vova():
    members = [_member(VOVA), _member(JULIA)]
    result = build_add_notifications(
        adder_id=JULIA, vova_id=VOVA, members=members, names=["молоко"]
    )
    assert result == []


def test_no_notifications_when_vova_id_not_configured():
    members = [_member(VOVA), _member(JULIA)]
    result = build_add_notifications(
        adder_id=VOVA, vova_id=None, members=members, names=["молоко"]
    )
    assert result == []


def test_no_notifications_when_names_empty():
    members = [_member(VOVA), _member(JULIA)]
    result = build_add_notifications(
        adder_id=VOVA, vova_id=VOVA, members=members, names=[]
    )
    assert result == []


def test_notifies_other_members_excluding_vova():
    members = [_member(VOVA), _member(JULIA)]
    result = build_add_notifications(
        adder_id=VOVA, vova_id=VOVA, members=members, names=["молоко"]
    )
    assert result == [(JULIA, "🛒 Вова добавил в список: молоко")]


def test_joins_multiple_names():
    members = [_member(VOVA), _member(JULIA)]
    result = build_add_notifications(
        adder_id=VOVA, vova_id=VOVA, members=members, names=["молоко", "хлеб"]
    )
    assert result == [(JULIA, "🛒 Вова добавил в список: молоко, хлеб")]
