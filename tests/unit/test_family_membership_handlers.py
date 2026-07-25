"""Хендлеры удаления участника и выхода из семьи: подтверждения и уведомления."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import family as family_handler
from core.db import MemberRole
from core.exceptions import CannotRemoveAdmin, LastAdminCannotLeave


def _member(member_id: int, tg_id: int, name: str, role=MemberRole.member):
    return SimpleNamespace(
        id=member_id, telegram_user_id=tg_id, display_name=name, role=role
    )


ADMIN = _member(1, 111, "Юля", MemberRole.admin)
MEMBER = _member(2, 222, "Петя")
FAMILY = SimpleNamespace(id=7, name="Ивановы", invite_code="code")


def _cb(data: str):
    cb = AsyncMock()
    cb.data = data
    return cb


def _patch_members(monkeypatch, members):
    async def fake_members(session, family_id=None):
        return members

    monkeypatch.setattr(family_handler, "get_family_members", fake_members)


# --- удаление участника ---


async def test_remove_ask_shows_confirmation(monkeypatch):
    _patch_members(monkeypatch, [ADMIN, MEMBER])
    cb = _cb("fam:rm:2")

    await family_handler.on_remove_ask(cb, db_session=None, family=FAMILY)

    text, kwargs = cb.message.edit_text.await_args.args[0], cb.message.edit_text.await_args.kwargs
    assert "Петя" in text and "Удалить" in text
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert buttons == ["fam:rmyes:2", "fam:rmno"]


async def test_remove_ask_rejects_admin_target(monkeypatch):
    _patch_members(monkeypatch, [ADMIN, MEMBER])
    cb = _cb("fam:rm:1")  # цель — админ

    await family_handler.on_remove_ask(cb, db_session=None, family=FAMILY)

    cb.message.edit_text.assert_not_awaited()
    assert cb.answer.await_args.kwargs["show_alert"] is True


async def test_remove_confirm_deletes_and_notifies(monkeypatch):
    async def fake_remove(session, *, family_id, actor, member_id):
        assert (family_id, member_id) == (7, 2)
        return MEMBER

    monkeypatch.setattr(family_handler, "remove_member", fake_remove)
    cb = _cb("fam:rmyes:2")

    await family_handler.on_remove_confirm(
        cb, db_session=None, family=FAMILY, family_member=ADMIN
    )

    assert "Петя" in cb.message.edit_text.await_args.args[0]
    # Удаленному приходит уведомление и снимается постоянная клавиатура.
    notice = cb.bot.send_message.await_args
    assert notice.args[0] == 222
    assert "Ивановы" in notice.args[1]
    assert notice.kwargs["reply_markup"] is not None


async def test_remove_confirm_survives_blocked_user(monkeypatch):
    """Заблокировавший бота не должен ломать удаление — оно уже состоялось."""

    async def fake_remove(session, *, family_id, actor, member_id):
        return MEMBER

    monkeypatch.setattr(family_handler, "remove_member", fake_remove)
    cb = _cb("fam:rmyes:2")
    cb.bot.send_message.side_effect = RuntimeError("bot was blocked")

    await family_handler.on_remove_confirm(
        cb, db_session=None, family=FAMILY, family_member=ADMIN
    )

    cb.answer.assert_awaited()  # хендлер дошел до конца


async def test_remove_confirm_reports_admin_guard(monkeypatch):
    async def fake_remove(session, *, family_id, actor, member_id):
        raise CannotRemoveAdmin

    monkeypatch.setattr(family_handler, "remove_member", fake_remove)
    cb = _cb("fam:rmyes:1")

    await family_handler.on_remove_confirm(
        cb, db_session=None, family=FAMILY, family_member=ADMIN
    )

    assert cb.answer.await_args.kwargs["show_alert"] is True
    cb.bot.send_message.assert_not_awaited()


async def test_remove_cancel_restores_family_view(monkeypatch):
    _patch_members(monkeypatch, [ADMIN, MEMBER])
    cb = _cb("fam:rmno")

    await family_handler.on_remove_cancel(cb, db_session=None, family=FAMILY)

    assert "Ивановы" in cb.message.edit_text.await_args.args[0]


# --- выход из семьи ---


async def test_leave_ask_shows_confirmation():
    cb = _cb("fam:leave")

    await family_handler.on_leave_ask(cb, family=FAMILY)

    text = cb.message.edit_text.await_args.args[0]
    kwargs = cb.message.edit_text.await_args.kwargs
    assert "Ивановы" in text and "ссылке-приглашению" in text
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert buttons == ["fam:leaveyes", "fam:leaveno"]


async def test_leave_confirm_notifies_remaining_admins(monkeypatch):
    called = {}

    async def fake_leave(session, *, family, member):
        called["member"] = member.id

    async def fake_admins(session, *, family_id):
        return [SimpleNamespace(telegram_user_id=111)]

    monkeypatch.setattr(family_handler, "leave_family", fake_leave)
    monkeypatch.setattr(family_handler, "get_admins", fake_admins)
    cb = _cb("fam:leaveyes")

    await family_handler.on_leave_confirm(
        cb, db_session=None, family=FAMILY, family_member=MEMBER
    )

    assert called["member"] == 2
    assert "покинули семью" in cb.message.edit_text.await_args.args[0]
    assert cb.bot.send_message.await_args.args[0] == 111
    assert "Петя" in cb.bot.send_message.await_args.args[1]


async def test_leave_confirm_blocks_last_admin(monkeypatch):
    async def fake_leave(session, *, family, member):
        raise LastAdminCannotLeave

    monkeypatch.setattr(family_handler, "leave_family", fake_leave)
    cb = _cb("fam:leaveyes")

    await family_handler.on_leave_confirm(
        cb, db_session=None, family=FAMILY, family_member=ADMIN
    )

    alert = cb.answer.await_args
    assert alert.kwargs["show_alert"] is True
    assert "единственный администратор" in alert.args[0]
    cb.message.edit_text.assert_not_awaited()


async def test_leave_cancel_member_gets_leave_only_keyboard(monkeypatch):
    _patch_members(monkeypatch, [ADMIN, MEMBER])
    cb = _cb("fam:leaveno")

    await family_handler.on_leave_cancel(
        cb, db_session=None, family=FAMILY, family_member=MEMBER
    )

    kwargs = cb.message.edit_text.await_args.kwargs
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert buttons == ["fam:leave"]


async def test_leave_cancel_admin_gets_full_keyboard(monkeypatch):
    _patch_members(monkeypatch, [ADMIN, MEMBER])
    cb = _cb("fam:leaveno")

    await family_handler.on_leave_cancel(
        cb, db_session=None, family=FAMILY, family_member=ADMIN
    )

    kwargs = cb.message.edit_text.await_args.kwargs
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert "fam:rm:2" in buttons and "fam:leave" in buttons


# --- клавиатуры ---


def test_family_keyboard_has_no_remove_for_admins():
    buttons = [
        b.callback_data
        for row in family_handler._kb_family([ADMIN, MEMBER]).inline_keyboard
        for b in row
    ]
    assert "fam:rm:2" in buttons
    assert "fam:rm:1" not in buttons  # админа удалить нельзя
    assert "fam:leave" in buttons
