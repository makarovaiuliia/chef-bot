from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers.family import start_with_invite
from core.services.family_service import (
    create_family,
    get_admins,
    grant_admin,
    join_by_invite,
    resolve_member,
)


async def test_join_notifies_admin_target(db_session):
    family, admin = await create_family(
        db_session, telegram_user_id=1, display_name="Юля",
        profile_md="p", timezone="UTC", plan_slots=["dinner"],
    )
    _, member = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=2, display_name="Вова"
    )
    admins = await get_admins(db_session, family_id=family.id)
    assert admins[0].telegram_user_id == 1
    assert member.family_id == family.id


async def test_join_notifies_all_admins(db_session):
    """При 2+ админах о вступлении уведомляются все, кроме самого вступившего."""
    family, admin1 = await create_family(
        db_session, telegram_user_id=111, display_name="Юля",
        profile_md="p", timezone="UTC", plan_slots=["dinner"],
    )
    _, second = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await grant_admin(db_session, family_id=family.id, member_id=second.id)

    message = AsyncMock()
    message.from_user = SimpleNamespace(id=333, full_name="Гость")
    command = SimpleNamespace(args=f"inv_{family.invite_code}")
    state = AsyncMock()

    await start_with_invite(message, command, db_session, state=state, family=None)

    notified = {call.args[0] for call in message.bot.send_message.await_args_list}
    assert notified == {111, 222}  # оба админа, вступивший (333) — нет


async def test_start_with_invite_clears_fsm_state(db_session):
    """Клик по инвайт-ссылке посреди онбординга должен сбрасывать FSM-state."""
    family, _ = await create_family(
        db_session, telegram_user_id=1, display_name="Юля",
        profile_md="p", timezone="UTC", plan_slots=["dinner"],
    )
    message = AsyncMock()
    message.from_user = SimpleNamespace(id=2, full_name="Вова")
    command = SimpleNamespace(args=f"inv_{family.invite_code}")
    state = AsyncMock()

    await start_with_invite(
        message, command, db_session, state=state, family=None
    )

    state.clear.assert_awaited_once()
    resolved = await resolve_member(db_session, 2)
    assert resolved is not None
    assert resolved[0].id == family.id
