from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily
from bot.formatting import md_to_telegram_html
from bot.keyboards import BTN_ADD, BTN_LIST, kb_main, kb_shop_clear_confirm, kb_shopping_list
from core import emoji, repositories
from core.db import Family, FamilyMember
from core.services import shopping_list

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())

_ADD_PROMPT = "Что добавить в список?"


def _split_names(text: str) -> list[str]:
    """Split user input by commas/newlines into separate items."""
    parts = [p.strip() for p in text.replace("\n", ",").split(",")]
    return [p for p in parts if p]


async def _ask_what_to_add(message: Message) -> None:
    await message.answer(
        _ADD_PROMPT,
        reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
    )


async def _add_items(
    message: Message,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
    names: list[str],
) -> None:
    for name in names:
        await shopping_list.add_manual_item(
            db_session, family_id=family.id, name=name
        )
    # kb_main возвращаем: ForceReply-приглашение «Что добавить?» вытеснило
    # постоянную клавиатуру, подтверждение — момент вернуть ее.
    if len(names) == 1:
        await message.answer(f"Добавил: {names[0]}", reply_markup=kb_main())
    else:
        bullets = "\n".join(f"• {n}" for n in names)
        await message.answer(f"Добавил:\n{bullets}", reply_markup=kb_main())

    await _notify_added(message, family, family_member, db_session, names)


async def _notify_added(
    message: Message,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
    names: list[str],
) -> None:
    """Ping every other family member that someone added items to the list."""
    members = await repositories.get_family_members(db_session, family.id)
    for uid, text in shopping_list.build_added_notifications(family_member, members, names):
        try:
            await message.bot.send_message(uid, md_to_telegram_html(text))
        except Exception:
            logger.warning("shopping: added notification failed user_id={}", uid)


@router.message(Command("add"))
async def cmd_add(
    message: Message, family: Family, family_member: FamilyMember, db_session: AsyncSession
) -> None:
    text = (message.text or "").removeprefix("/add").strip()
    if not text:
        await _ask_what_to_add(message)
        return
    names = _split_names(text)
    if not names:
        await message.answer("Не понял, что добавить. Попробуй /add еще раз.")
        return
    await _add_items(message, family, family_member, db_session, names)


@router.message(
    F.reply_to_message.from_user.is_bot & (F.reply_to_message.text == _ADD_PROMPT)
)
async def handle_add_reply(
    message: Message, family: Family, family_member: FamilyMember, db_session: AsyncSession
) -> None:
    names = _split_names(message.text or "")
    if not names:
        await message.answer("Не понял, что добавить. Попробуй /add еще раз.")
        return
    await _add_items(message, family, family_member, db_session, names)


@router.message(Command("list"))
@router.message(F.text == BTN_LIST)
async def cmd_list(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not items:
        await message.answer(
            f"{emoji.SHOPPING} Все куплено {emoji.DONE}",
            reply_markup=kb_shopping_list([]),
        )
        return
    await message.answer(
        f"<b>{emoji.SHOPPING} Список покупок</b>", reply_markup=kb_shopping_list(items)
    )


@router.callback_query(F.data == "shop:add")
async def cb_add(cb: CallbackQuery) -> None:
    await _ask_what_to_add(cb.message)
    await cb.answer()


@router.message(F.text == BTN_ADD)
async def btn_add(message: Message) -> None:
    await _ask_what_to_add(message)


@router.callback_query(F.data.startswith("shop:toggle:"))
async def cb_toggle(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    item_id = int(cb.data.split(":")[2])
    await shopping_list.toggle_bought(db_session, item_id=item_id, family_id=family.id)
    open_items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not open_items:
        await cb.message.edit_text(
            f"<b>{emoji.SHOPPING} Список покупок</b>\n\nВсе пункты закрыты {emoji.DONE}",
            reply_markup=kb_shopping_list([]),
        )
    else:
        await cb.message.edit_reply_markup(reply_markup=kb_shopping_list(open_items))
    await cb.answer("Готово")


@router.callback_query(F.data == "shop:clear")
async def cb_clear(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "Закрыть все пункты списка? Это действие нельзя отменить.",
        reply_markup=kb_shop_clear_confirm(),
    )
    await cb.answer()


@router.callback_query(F.data == "shop:clear:yes")
async def cb_clear_yes(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    closed = await shopping_list.clear_all_open(db_session, family_id=family.id)
    await cb.message.edit_text(f"{emoji.DONE} Список очищен: закрыто пунктов — {closed}.")
    await cb.answer()


@router.callback_query(F.data == "shop:clear:no")
async def cb_clear_no(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    await cb.message.edit_text(
        f"<b>{emoji.SHOPPING} Список покупок</b>", reply_markup=kb_shopping_list(items)
    )
    await cb.answer()
