"""Tool schemas + dispatcher for the conversation agent."""
from datetime import UTC, datetime
from datetime import date as DateType
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.db import ShoppingItem
from core.services import dish_replacer, recipe_service
from core.services import shopping_list as shopping_list_service


def _today() -> DateType:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_active_menu",
        "description": (
            "Возвращает текущее активное меню семьи (список блюд с датами и приёмами). "
            "Используй когда пользователь спрашивает 'что у нас в меню', 'какое меню сейчас'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_meals_for_date",
        "description": (
            "Возвращает блюда на конкретную дату из активного меню. "
            "Используй когда пользователь спрашивает 'что сегодня', 'что на завтра', "
            "'что в четверг'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Дата в формате YYYY-MM-DD",
                }
            },
            "required": ["date"],
        },
    },
    {
        "name": "replace_meal",
        "description": (
            "Заменяет блюдо в активном меню. "
            "Используй когда пользователь просит 'поменяй четверг ужин', "
            "'замени курицу на рыбу' и т.п."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "slot": {"type": "string", "enum": ["lunch", "dinner"]},
                "hint": {
                    "type": "string",
                    "description": (
                        "Пожелание пользователя по новому блюду "
                        "(например, 'с рыбой', 'попроще')"
                    ),
                },
            },
            "required": ["date", "slot"],
        },
    },
    {
        "name": "get_recipe_for_meal",
        "description": (
            "Возвращает подробный рецепт блюда из активного меню. "
            "Используй когда пользователь просит рецепт конкретного приёма "
            "('дай рецепт сегодняшнего ужина', 'как готовить четверг обед')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "slot": {"type": "string", "enum": ["lunch", "dinner"]},
            },
            "required": ["date", "slot"],
        },
    },
    {
        "name": "add_shopping_item",
        "description": (
            "Добавляет пункт в список покупок. "
            "Используй когда пользователь говорит 'добавь молоко в список', 'надо купить X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "string", "description": "например '500 г', '1 шт'"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "mark_shopping_item_bought",
        "description": (
            "Отмечает пункт списка покупок купленным. "
            "Используй когда пользователь говорит 'я купила X', 'отметь молоко'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_substring": {
                    "type": "string",
                    "description": "Часть названия пункта (бот сам найдёт по подстроке)",
                }
            },
            "required": ["name_substring"],
        },
    },
]


async def execute_tool(
    session: AsyncSession, *, family_id: int, name: str, input: dict[str, Any]
) -> str:
    """Dispatch a tool call. Returns string result for the LLM."""
    if name == "get_active_menu":
        return await _tool_get_active_menu(session, family_id)
    if name == "get_meals_for_date":
        return await _tool_get_meals_for_date(session, family_id, input["date"])
    if name == "replace_meal":
        return await _tool_replace_meal(session, family_id, input)
    if name == "get_recipe_for_meal":
        return await _tool_get_recipe_for_meal(session, family_id, input)
    if name == "add_shopping_item":
        return await _tool_add_shopping_item(session, family_id, input)
    if name == "mark_shopping_item_bought":
        return await _tool_mark_bought(session, family_id, input)
    return f"Неизвестный tool: {name}"


async def _tool_get_active_menu(session: AsyncSession, family_id: int) -> str:
    today = _today()
    meals = await repositories.get_future_meals(session, family_id, today)
    if not meals:
        return "Меню не загружено."
    last_date = max(m.date for m in meals)
    days = (last_date - today).days + 1
    lines = [f"Меню на {days} дн. с {today.isoformat()}:"]
    for m in meals:
        sides = ", ".join(m.side_dishes or [])
        lines.append(
            f"  {m.date.isoformat()} {m.slot.value}: {m.dish_name}"
            + (f" (гарниры: {sides})" if sides else "")
        )
    return "\n".join(lines)


async def _tool_get_meals_for_date(
    session: AsyncSession, family_id: int, date_str: str
) -> str:
    try:
        d = DateType.fromisoformat(date_str)
    except ValueError:
        return f"Неверный формат даты: {date_str}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    if not meals:
        return f"На {d.isoformat()} в активном меню ничего."
    lines = [f"{d.isoformat()}:"]
    for m in meals:
        sides = ", ".join(m.side_dishes or [])
        lines.append(
            f"  {m.slot.value}: {m.dish_name}"
            + (f" (гарниры: {sides})" if sides else "")
        )
    return "\n".join(lines)


async def _tool_replace_meal(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    try:
        d = DateType.fromisoformat(input["date"])
    except ValueError:
        return f"Неверный формат даты: {input['date']}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    target = next((m for m in meals if m.slot.value == input["slot"]), None)
    if target is None:
        return f"Не нашёл {input['slot']} на {input['date']} в активном меню."
    new_meal = await dish_replacer.replace_meal(
        session, meal_id=target.id, hint=input.get("hint")
    )
    result = f"Заменил {input['slot']} {input['date']} на: {new_meal.dish_name}"
    if new_meal.side_dishes:
        result += f" (гарниры: {', '.join(new_meal.side_dishes)})"
    return result


async def _tool_get_recipe_for_meal(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    try:
        d = DateType.fromisoformat(input["date"])
    except ValueError:
        return f"Неверный формат даты: {input['date']}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    target = next((m for m in meals if m.slot.value == input["slot"]), None)
    if target is None:
        return f"Не нашёл {input['slot']} на {input['date']} в активном меню."
    recipe = await recipe_service.get_recipe(session, meal_id=target.id)
    return f"Рецепт «{target.dish_name}» (~{recipe.prep_minutes} мин):\n\n{recipe.content_md}"


async def _tool_add_shopping_item(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    await shopping_list_service.add_manual_item(
        session,
        family_id=family_id,
        name=input["name"],
        quantity=input.get("quantity", ""),
    )
    return f"Добавил в список: {input['name']}"


async def _tool_mark_bought(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    substring = input["name_substring"].lower()
    stmt = select(ShoppingItem).where(
        ShoppingItem.family_id == family_id,
        ShoppingItem.bought.is_(False),
    )
    items = list((await session.execute(stmt)).scalars().all())
    target = next((i for i in items if substring in i.name.lower()), None)
    if target is None:
        return f"Не нашёл незакрытый пункт со словом '{substring}'."
    target.bought = True
    target.bought_at = datetime.now(UTC)
    await session.flush()
    return f"Отметил купленным: {target.name}"
