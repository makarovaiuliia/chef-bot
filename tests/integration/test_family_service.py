import json

import pytest

from config import get_settings
from core.db import Family
from core.exceptions import (
    AlreadyInFamily,
    InvalidInviteCode,
    MemberNotInFamily,
    MonthlyCapExceeded,
)
from core.llm import LLMResponse
from core.repositories import count_llm_operations
from core.services.family_service import (
    change_family_timezone,
    create_family,
    get_admins,
    grant_admin,
    is_admin,
    join_by_invite,
    regenerate_invite,
    resolve_member,
    update_digest_settings,
)


class FakeLLM:
    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(text=self._texts.pop(0), tokens_in=10, tokens_out=20)


async def _make_family(db_session, tg_id=111):
    return await create_family(
        db_session,
        telegram_user_id=tg_id,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["lunch", "dinner"],
    )


async def test_create_family_sets_admin_and_invite(db_session):
    family, member = await _make_family(db_session)
    assert is_admin(member)
    assert family.invite_code
    assert family.profile_md == "# Профиль"
    assert family.plan_slots == ["lunch", "dinner"]


async def test_resolve_member_roundtrip(db_session):
    family, member = await _make_family(db_session)
    resolved = await resolve_member(db_session, 111)
    assert resolved is not None
    assert resolved[0].id == family.id
    assert await resolve_member(db_session, 999) is None


async def test_join_by_invite(db_session):
    family, _ = await _make_family(db_session)
    fam2, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    assert fam2.id == family.id
    assert not is_admin(joined)


async def test_join_invalid_code_raises(db_session):
    with pytest.raises(InvalidInviteCode):
        await join_by_invite(
            db_session, invite_code="nope", telegram_user_id=222, display_name=None
        )


async def test_join_twice_raises(db_session):
    family, _ = await _make_family(db_session)
    with pytest.raises(AlreadyInFamily):
        await join_by_invite(
            db_session, invite_code=family.invite_code, telegram_user_id=111, display_name=None
        )


async def test_grant_admin_keeps_old_admin_rights(db_session):
    family, admin = await _make_family(db_session)
    _, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await grant_admin(db_session, family_id=family.id, member_id=joined.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert {a.telegram_user_id for a in admins} == {111, 222}
    assert is_admin(admin) and is_admin(joined)  # прежний админ ничего не потерял


async def test_grant_admin_rejects_member_from_other_family(db_session):
    family, _ = await _make_family(db_session, tg_id=111)
    other_family, other_member = await _make_family(db_session, tg_id=333)
    with pytest.raises(MemberNotInFamily):
        await grant_admin(db_session, family_id=family.id, member_id=other_member.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert len(admins) == 1


async def test_regenerate_invite_changes_code(db_session):
    family, _ = await _make_family(db_session)
    old = family.invite_code
    new = await regenerate_invite(db_session, family=family)
    assert new != old and family.invite_code == new


async def test_update_digest_settings(db_session):
    family, _ = await _make_family(db_session)
    await update_digest_settings(db_session, family=family, enabled=False)
    assert family.digest_enabled is False
    await update_digest_settings(db_session, family=family, hour=7)
    assert family.digest_hour == 7
    with pytest.raises(ValueError):
        await update_digest_settings(db_session, family=family, hour=3)


async def _tz_family(db_session):
    fam = Family(name="f", timezone="UTC")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_change_family_timezone_happy(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Asia/Yekaterinburg"})
    tz = await change_family_timezone(
        db_session, family=fam, city="Пермь", llm=FakeLLM([ok])
    )
    assert tz == "Asia/Yekaterinburg"
    assert fam.timezone == "Asia/Yekaterinburg"
    assert await count_llm_operations(db_session, family_id=fam.id, operation="tz_detect") == 1


async def test_change_family_timezone_unrecognized_city(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": None})
    tz = await change_family_timezone(
        db_session, family=fam, city="асдфг", llm=FakeLLM([ok])
    )
    assert tz is None
    assert fam.timezone == "UTC"  # не тронута
    # usage все равно залогирован
    assert await count_llm_operations(db_session, family_id=fam.id, operation="tz_detect") == 1


async def test_change_family_timezone_invalid_iana(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Europe/Mordor"})
    tz = await change_family_timezone(
        db_session, family=fam, city="Мордор", llm=FakeLLM([ok])
    )
    assert tz is None
    assert fam.timezone == "UTC"


async def test_change_family_timezone_retries_on_bad_json(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Europe/Moscow"})
    llm = FakeLLM(["не json", ok])
    tz = await change_family_timezone(db_session, family=fam, city="Москва", llm=llm)
    assert tz == "Europe/Moscow"
    assert llm.calls == 2


async def test_change_family_timezone_blocked_by_cap(db_session, monkeypatch):
    fam = await _tz_family(db_session)
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 0)
    llm = FakeLLM([json.dumps({"timezone": "Europe/Moscow"})])
    with pytest.raises(MonthlyCapExceeded):
        await change_family_timezone(db_session, family=fam, city="Москва", llm=llm)
    assert llm.calls == 0  # отказ ДО LLM-вызова
