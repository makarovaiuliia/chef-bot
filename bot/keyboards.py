from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import emoji


def kb_confirm_overwrite() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Да", callback_data="load:yes")
    b.button(text=f"{emoji.CANCEL} Нет", callback_data="load:no")
    b.adjust(2)
    return b.as_markup()


def kb_shopping_list(items) -> InlineKeyboardMarkup:
    """Flat checklist: one button per item + add button at the bottom."""
    b = InlineKeyboardBuilder()
    for item in items:
        mark = emoji.DONE if item.bought else emoji.UNCHECKED
        label = f"{mark} {item.name}"
        if item.quantity:
            label += f" — {item.quantity}"
        b.button(text=label, callback_data=f"shop:toggle:{item.id}")
    b.button(text=f"{emoji.ADD} Добавить", callback_data="shop:add")
    b.adjust(1)
    return b.as_markup()
