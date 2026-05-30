from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ForceReply, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.formatting import md_to_telegram_html
from bot.keyboards import kb_shopping_list
from config import get_settings
from core import repositories
from core.db import Family
from core.services import shopping_list

router = Router()

_ADD_PROMPT = "Что добавить в список?"


def _split_names(text: str) -> list[str]:
    """Split user input by commas/newlines into separate items."""
    parts = [p.strip() for p in text.replace("\n", ",").split(",")]
    return [p for p in parts if p]


async def _add_items(
    message: Message, family: Family, db_session: AsyncSession, names: list[str]
) -> None:
    for name in names:
        await shopping_list.add_manual_item(
            db_session, family_id=family.id, name=name
        )
    if len(names) == 1:
        await message.answer(f"Добавил: {names[0]}")
    else:
        bullets = "\n".join(f"• {n}" for n in names)
        await message.answer(f"Добавил:\n{bullets}")

    await _notify_vova_added(message, family, db_session, names)


async def _notify_vova_added(
    message: Message, family: Family, db_session: AsyncSession, names: list[str]
) -> None:
    """If Вова added the items, ping every other family member."""
    vova_id = get_settings().vova_telegram_id
    if not vova_id or message.from_user is None or message.from_user.id != vova_id:
        return
    members = await repositories.get_family_members(db_session, family.id)
    for uid, text in shopping_list.build_add_notifications(
        adder_id=message.from_user.id, vova_id=vova_id, members=members, names=names
    ):
        await message.bot.send_message(uid, md_to_telegram_html(text))


@router.message(Command("add"))
async def cmd_add(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    text = (message.text or "").removeprefix("/add").strip()
    if not text:
        await message.answer(
            _ADD_PROMPT,
            reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
        )
        return
    names = _split_names(text)
    if not names:
        await message.answer("Не понял, что добавить. Попробуй /add ещё раз.")
        return
    await _add_items(message, family, db_session, names)


@router.message(
    F.reply_to_message.from_user.is_bot & (F.reply_to_message.text == _ADD_PROMPT)
)
async def handle_add_reply(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    names = _split_names(message.text or "")
    if not names:
        await message.answer("Не понял, что добавить. Попробуй /add ещё раз.")
        return
    await _add_items(message, family, db_session, names)


@router.message(Command("list"))
async def cmd_list(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not items:
        await message.answer(
            "🛒 Всё куплено ✅", reply_markup=kb_shopping_list([])
        )
        return
    await message.answer(
        "<b>🛒 Список покупок</b>", reply_markup=kb_shopping_list(items)
    )


@router.callback_query(F.data == "shop:add")
async def cb_add(cb: CallbackQuery) -> None:
    await cb.message.answer(
        _ADD_PROMPT,
        reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("shop:toggle:"))
async def cb_toggle(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    item_id = int(cb.data.split(":")[2])
    await shopping_list.toggle_bought(db_session, item_id=item_id)
    open_items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not open_items:
        await cb.message.edit_text(
            "<b>🛒 Список покупок</b>\n\nВсе пункты закрыты ✅",
            reply_markup=kb_shopping_list([]),
        )
    else:
        await cb.message.edit_reply_markup(reply_markup=kb_shopping_list(open_items))
    await cb.answer("Готово")
