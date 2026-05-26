from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_days() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="7 дней", callback_data="plan:days:7")
    b.button(text="14 дней", callback_data="plan:days:14")
    return b.as_markup()


def kb_draft_review(menu_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Утвердить", callback_data=f"plan:approve:{menu_id}")
    b.button(text="🔁 Заменить блюдо", callback_data=f"plan:replace_pick:{menu_id}")
    b.button(text="❌ Отмена", callback_data=f"plan:cancel:{menu_id}")
    b.adjust(1)
    return b.as_markup()


def kb_meals_for_replace(meals) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in meals:
        label = f"{m.date.strftime('%a %d.%m')} {m.slot.value} — {m.dish_name[:25]}"
        b.button(text=label, callback_data=f"plan:replace_meal:{m.id}")
    b.adjust(1)
    return b.as_markup()
