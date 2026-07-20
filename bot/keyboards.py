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


def kb_multiselect(
    prefix: str, options: dict[str, str], selected: set[str]
) -> InlineKeyboardMarkup:
    """Тогл-кнопки: prefix:<key>; кнопка завершения: prefix:done."""
    b = InlineKeyboardBuilder()
    for key, label in options.items():
        mark = f"{emoji.DONE} " if key in selected else ""
        b.button(text=f"{mark}{label}", callback_data=f"{prefix}:{key}")
    b.button(text=f"Готово {emoji.ARROW}", callback_data=f"{prefix}:done")
    b.adjust(1)
    return b.as_markup()


def kb_household() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in ("1", "2", "3", "4+"):
        b.button(text=n, callback_data=f"onb:hh:{n}")
    b.adjust(4)
    return b.as_markup()


def kb_cook_minutes() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in ("20", "40", "60"):
        b.button(text=f"{m} мин", callback_data=f"onb:cook:{m}")
    b.adjust(3)
    return b.as_markup()


def kb_skip(callback: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"Пропустить {emoji.ARROW}", callback_data=callback)
    return b.as_markup()


def kb_profile_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Всё верно", callback_data="onb:profile:ok")
    b.button(text=f"{emoji.EDIT} Редактировать", callback_data="onb:profile:edit")
    b.adjust(2)
    return b.as_markup()
