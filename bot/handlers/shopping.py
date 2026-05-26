from collections import defaultdict

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import STORE_LABELS, kb_shopping_list
from core import repositories
from core.db import Family
from core.services import shopping_list

router = Router()


def _group_by_store(items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.store.value].append(item)
    ordered_stores = ["makro", "villa", "lotus", "seven_eleven", "other"]
    return [(s, grouped[s]) for s in ordered_stores if grouped[s]]


@router.message(Command("list"))
async def cmd_list(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not items:
        await message.answer(
            "Незакрытых пунктов нет. Запусти /plan, чтобы создать меню и список."
        )
        return

    for store_key, store_items in _group_by_store(items):
        await message.answer(
            f"<b>{STORE_LABELS.get(store_key, store_key)}</b>",
            reply_markup=kb_shopping_list(store_items),
        )


@router.callback_query(F.data.startswith("shop:toggle:"))
async def cb_toggle(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    item_id = int(cb.data.split(":")[2])
    await shopping_list.toggle_bought(db_session, item_id=item_id)
    target_item = await repositories.get_shopping_item(db_session, item_id)
    if target_item is None:
        await cb.answer()
        return
    open_items = await shopping_list.get_open_items(db_session, family_id=family.id)
    same_store_items = [i for i in open_items if i.store == target_item.store]
    if not same_store_items:
        await cb.message.edit_text(
            f"<b>{STORE_LABELS.get(target_item.store.value)}</b>\n\nВсе пункты закрыты ✅"
        )
    else:
        await cb.message.edit_reply_markup(reply_markup=kb_shopping_list(same_store_items))
    await cb.answer("Готово")
