from datetime import UTC, datetime
from datetime import date as DateType

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db import (
    ClaudeConversation,
    Meal,
    MealSlot,
    Menu,
    MenuStatus,
    MessageRole,
    ProteinKind,
    Recipe,
    ShoppingItem,
    ShoppingList,
    Store,
)


async def create_draft_menu(
    session: AsyncSession,
    *,
    family_id: int,
    start_date: DateType,
    days_count: int,
    meals: list[dict],
) -> Menu:
    """Create a draft menu with all its meals atomically."""
    menu = Menu(
        family_id=family_id,
        start_date=start_date,
        days_count=days_count,
        status=MenuStatus.draft,
    )
    session.add(menu)
    await session.flush()

    for m in meals:
        meal = Meal(
            menu_id=menu.id,
            date=m["date"],
            slot=MealSlot(m["slot"]),
            dish_name=m["dish_name"],
            side_dishes=m.get("side_dishes", []),
            protein_kind=ProteinKind(m["protein_kind"]),
        )
        session.add(meal)
    await session.flush()
    await session.refresh(menu, attribute_names=["meals"])
    return menu


async def approve_menu(session: AsyncSession, menu_id: int) -> None:
    """Mark menu active; archive any previously-active menu in the same family."""
    menu = await session.get(Menu, menu_id)
    if menu is None:
        return
    await session.execute(
        update(Menu)
        .where(Menu.family_id == menu.family_id, Menu.status == MenuStatus.active)
        .values(status=MenuStatus.archived)
    )
    menu.status = MenuStatus.active
    menu.approved_at = datetime.now(UTC)


async def get_active_menu(session: AsyncSession, family_id: int) -> Menu | None:
    stmt = (
        select(Menu)
        .where(Menu.family_id == family_id, Menu.status == MenuStatus.active)
        .options(selectinload(Menu.meals))
        .order_by(Menu.approved_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_menu_with_meals(session: AsyncSession, menu_id: int) -> Menu | None:
    stmt = (
        select(Menu).where(Menu.id == menu_id).options(selectinload(Menu.meals))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_meal(session: AsyncSession, meal_id: int) -> Meal | None:
    return await session.get(Meal, meal_id)


async def get_meals_for_date(
    session: AsyncSession, family_id: int, on_date: DateType
) -> list[Meal]:
    stmt = (
        select(Meal)
        .join(Menu)
        .where(
            Menu.family_id == family_id,
            Menu.status == MenuStatus.active,
            Meal.date == on_date,
        )
        .order_by(Meal.slot)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_meal(
    session: AsyncSession,
    meal_id: int,
    *,
    dish_name: str,
    side_dishes: list[str],
    protein_kind: ProteinKind,
) -> Meal:
    meal = await session.get(Meal, meal_id)
    if meal is None:
        raise ValueError(f"Meal {meal_id} not found")
    meal.dish_name = dish_name
    meal.side_dishes = side_dishes
    meal.protein_kind = protein_kind
    existing_recipe = (
        await session.execute(select(Recipe).where(Recipe.meal_id == meal_id))
    ).scalar_one_or_none()
    if existing_recipe is not None:
        await session.delete(existing_recipe)
    await session.flush()
    return meal


async def save_recipe(
    session: AsyncSession,
    meal_id: int,
    *,
    content_md: str,
    ingredients: list[dict],
    prep_minutes: int,
) -> Recipe:
    recipe = Recipe(
        meal_id=meal_id,
        content_md=content_md,
        ingredients=ingredients,
        prep_minutes=prep_minutes,
    )
    session.add(recipe)
    await session.flush()
    return recipe


async def get_recipe(session: AsyncSession, meal_id: int) -> Recipe | None:
    stmt = select(Recipe).where(Recipe.meal_id == meal_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_shopping_list(
    session: AsyncSession,
    *,
    menu_id: int,
    family_id: int,
    items: list[dict],
) -> ShoppingList:
    sl = ShoppingList(menu_id=menu_id)
    session.add(sl)
    await session.flush()
    for item in items:
        si = ShoppingItem(
            shopping_list_id=sl.id,
            family_id=family_id,
            name=item["name"],
            quantity=item.get("quantity", ""),
            store=Store(item.get("store", "other")),
        )
        session.add(si)
    await session.flush()
    return sl


async def get_open_shopping_items(
    session: AsyncSession, *, family_id: int
) -> list[ShoppingItem]:
    stmt = (
        select(ShoppingItem)
        .where(ShoppingItem.family_id == family_id, ShoppingItem.bought.is_(False))
        .order_by(ShoppingItem.store, ShoppingItem.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_shopping_item(
    session: AsyncSession, item_id: int
) -> ShoppingItem | None:
    return await session.get(ShoppingItem, item_id)


async def mark_shopping_item_bought(
    session: AsyncSession, item_id: int, *, bought: bool = True
) -> ShoppingItem | None:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        return None
    item.bought = bought
    item.bought_at = datetime.now(UTC) if bought else None
    await session.flush()
    return item


async def append_conversation(
    session: AsyncSession,
    *,
    family_id: int,
    telegram_user_id: int,
    role: MessageRole,
    content: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    session.add(
        ClaudeConversation(
            family_id=family_id,
            telegram_user_id=telegram_user_id,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    await session.flush()


async def recent_conversation(
    session: AsyncSession, *, family_id: int, limit: int = 20
) -> list[ClaudeConversation]:
    stmt = (
        select(ClaudeConversation)
        .where(ClaudeConversation.family_id == family_id)
        .order_by(ClaudeConversation.created_at.desc(), ClaudeConversation.id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()
    return rows
