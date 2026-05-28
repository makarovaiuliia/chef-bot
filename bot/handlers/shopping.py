from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ForceReply, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import kb_shopping_list
from core.db import Family
from core.services import shopping_list

router = Router()

_ADD_PROMPT = "Что добавить в список?"


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
    await shopping_list.add_manual_item(
        db_session, family_id=family.id, name=text
    )
    await message.answer(f"Добавил: {text}")


@router.message(
    F.reply_to_message.from_user.is_bot & (F.reply_to_message.text == _ADD_PROMPT)
)
async def handle_add_reply(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Не понял, что добавить. Попробуй /add ещё раз.")
        return
    await shopping_list.add_manual_item(
        db_session, family_id=family.id, name=name
    )
    await message.answer(f"Добавил: {name}")


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
