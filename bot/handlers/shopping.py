from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import kb_shopping_list
from core.db import Family
from core.services import shopping_list

router = Router()


@router.message(Command("add"))
async def cmd_add(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    text = (message.text or "").removeprefix("/add").strip()
    if not text:
        await message.answer(
            "Использование: /add <название>\nПример: /add молоко"
        )
        return
    await shopping_list.add_manual_item(
        db_session, family_id=family.id, name=text
    )
    await message.answer(f"Добавил: {text}")


@router.message(Command("list"))
async def cmd_list(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not items:
        await message.answer(
            "Незакрытых пунктов нет. Добавить пункт: /add <название>."
        )
        return
    await message.answer(
        "<b>🛒 Список покупок</b>", reply_markup=kb_shopping_list(items)
    )


@router.callback_query(F.data.startswith("shop:toggle:"))
async def cb_toggle(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    item_id = int(cb.data.split(":")[2])
    await shopping_list.toggle_bought(db_session, item_id=item_id)
    open_items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not open_items:
        await cb.message.edit_text("<b>🛒 Список покупок</b>\n\nВсе пункты закрыты ✅")
    else:
        await cb.message.edit_reply_markup(reply_markup=kb_shopping_list(open_items))
    await cb.answer("Готово")
