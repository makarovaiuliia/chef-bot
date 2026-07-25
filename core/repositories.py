from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from datetime import date as DateType

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db import (
    ClaudeConversation,
    Family,
    FamilyMember,
    LlmUsage,
    Meal,
    MealSlot,
    Menu,
    MenuStatus,
    MessageRole,
    OnboardingAttempt,
    ProteinKind,
    Recipe,
    ShoppingItem,
    ShoppingList,
    SubscriptionRequest,
)

# завтрак → обед → ужин; строковый порядок enum'а ("breakfast" < "dinner" < "lunch") не годится
_SLOT_ORDER = case(
    (Meal.slot == MealSlot.breakfast, 0),
    (Meal.slot == MealSlot.lunch, 1),
    else_=2,
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
    """Mark a menu active. Multiple active menus per family are allowed —
    they accumulate into a single forward-looking meal calendar. Past days
    naturally drop out of display queries that filter by `date >= today`."""
    menu = await session.get(Menu, menu_id)
    if menu is None:
        return
    menu.status = MenuStatus.active
    menu.approved_at = datetime.now(UTC)


async def get_future_meals(
    session: AsyncSession, family_id: int, from_date: DateType
) -> list[Meal]:
    """All meals scheduled on or after from_date for this family."""
    stmt = (
        select(Meal)
        .join(Menu)
        .where(
            Menu.family_id == family_id,
            Menu.status == MenuStatus.active,
            Meal.date >= from_date,
        )
        .order_by(Meal.date, _SLOT_ORDER)
    )
    return list((await session.execute(stmt)).scalars().all())


async def find_conflicting_meal_dates(
    session: AsyncSession,
    *,
    family_id: int,
    dates: Iterable[DateType],
    from_date: DateType,
) -> set[DateType]:
    """Subset of `dates` (only those >= from_date) where this family already
    has meals scheduled."""
    dates_list = [d for d in dates if d >= from_date]
    if not dates_list:
        return set()
    stmt = (
        select(Meal.date)
        .join(Menu)
        .where(
            Menu.family_id == family_id,
            Menu.status == MenuStatus.active,
            Meal.date.in_(dates_list),
        )
        .distinct()
    )
    return {row[0] for row in (await session.execute(stmt)).all()}


async def delete_future_meals_on_dates(
    session: AsyncSession,
    *,
    family_id: int,
    dates: Iterable[DateType],
    from_date: DateType,
) -> None:
    """Delete meals on the given dates (>= from_date). Cascades to recipes."""
    dates_list = [d for d in dates if d >= from_date]
    if not dates_list:
        return
    stmt = (
        select(Meal)
        .join(Menu)
        .where(
            Menu.family_id == family_id,
            Menu.status == MenuStatus.active,
            Meal.date.in_(dates_list),
        )
    )
    meals = list((await session.execute(stmt)).scalars().all())
    for m in meals:
        await session.delete(m)
    await session.flush()


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
        .order_by(_SLOT_ORDER)
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


async def get_meal_for_family(
    session: AsyncSession, meal_id: int, *, family_id: int
) -> Meal | None:
    """Meal по id, только если он принадлежит меню этой семьи (защита callback-данных)."""
    stmt = (
        select(Meal)
        .join(Menu)
        .where(Meal.id == meal_id, Menu.family_id == family_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_family_members(
    session: AsyncSession, family_id: int
) -> list[FamilyMember]:
    stmt = select(FamilyMember).where(FamilyMember.family_id == family_id)
    return list((await session.execute(stmt)).scalars().all())


async def get_open_shopping_items(
    session: AsyncSession, *, family_id: int
) -> list[ShoppingItem]:
    stmt = (
        select(ShoppingItem)
        .where(ShoppingItem.family_id == family_id, ShoppingItem.bought.is_(False))
        .order_by(ShoppingItem.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_shopping_item(
    session: AsyncSession, item_id: int, *, family_id: int
) -> ShoppingItem | None:
    stmt = select(ShoppingItem).where(
        ShoppingItem.id == item_id, ShoppingItem.family_id == family_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def items_for_menu(session: AsyncSession, *, menu_id: int) -> list[ShoppingItem]:
    """Пункты списка покупок данного меню (для рендера текстом без чек-листа)."""
    stmt = (
        select(ShoppingItem)
        .join(ShoppingList, ShoppingItem.shopping_list_id == ShoppingList.id)
        .where(ShoppingList.menu_id == menu_id)
        .order_by(ShoppingItem.id)
    )
    return list((await session.execute(stmt)).scalars().all())


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


async def log_llm_usage(
    session: AsyncSession,
    *,
    family_id: int,
    operation: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    session.add(
        LlmUsage(
            family_id=family_id,
            operation=operation,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    await session.flush()


async def count_llm_operations(
    session: AsyncSession, *, family_id: int, operation: str
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(LlmUsage)
        .where(LlmUsage.family_id == family_id, LlmUsage.operation == operation)
    )
    return int(result.scalar_one())


def _month_boundary(now: datetime) -> datetime:
    """Граница календарного месяца для created_at-фильтров.

    Строгое > с эпсилоном: SQLite сравнивает datetime текстово, bound-параметр
    несет .000000, а CURRENT_TIMESTAMP пишет без микросекунд.
    """
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    return month_start - timedelta(microseconds=1)


async def sum_llm_tokens_current_month(
    session: AsyncSession, *, family_id: int, now: datetime
) -> int:
    """Сумма токенов семьи с 1-го числа календарного месяца `now` (UTC)."""
    boundary = _month_boundary(now)
    stmt = (
        select(func.coalesce(func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out), 0))
        .where(LlmUsage.family_id == family_id, LlmUsage.created_at > boundary)
    )
    return int((await session.execute(stmt)).scalar_one())


def _day_boundary(now: datetime) -> datetime:
    """Граница календарных суток UTC. Тот же эпсилон, что в _month_boundary."""
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return day_start - timedelta(microseconds=1)


async def log_onboarding_attempt(
    session: AsyncSession, *, telegram_user_id: int
) -> None:
    session.add(OnboardingAttempt(telegram_user_id=telegram_user_id))
    await session.flush()


async def count_onboarding_attempts_today(
    session: AsyncSession, *, telegram_user_id: int, now: datetime
) -> int:
    boundary = _day_boundary(now)
    stmt = (
        select(func.count())
        .select_from(OnboardingAttempt)
        .where(
            OnboardingAttempt.telegram_user_id == telegram_user_id,
            OnboardingAttempt.created_at > boundary,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def count_onboarding_attempts_today_all(
    session: AsyncSession, *, now: datetime
) -> int:
    """Все попытки онбординга за сутки — строка в сводке /admin."""
    boundary = _day_boundary(now)
    stmt = (
        select(func.count())
        .select_from(OnboardingAttempt)
        .where(OnboardingAttempt.created_at > boundary)
    )
    return int((await session.execute(stmt)).scalar_one())


async def admin_month_summary(session: AsyncSession, *, now: datetime) -> dict:
    """Сводка за календарный месяц для /admin: семьи, операции, токены (все семьи)."""
    boundary = _month_boundary(now)
    families = int(
        (await session.execute(select(func.count()).select_from(Family))).scalar_one()
    )
    ops_rows = (
        await session.execute(
            select(LlmUsage.operation, func.count())
            .where(LlmUsage.created_at > boundary)
            .group_by(LlmUsage.operation)
        )
    ).all()
    tokens_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LlmUsage.tokens_in), 0),
                func.coalesce(func.sum(LlmUsage.tokens_out), 0),
            ).where(LlmUsage.created_at > boundary)
        )
    ).one()
    return {
        "families": families,
        "ops": {op: int(cnt) for op, cnt in ops_rows},
        "tokens_in": int(tokens_row[0]),
        "tokens_out": int(tokens_row[1]),
    }


async def families_overview(session: AsyncSession, *, now: datetime) -> list[dict]:
    """По семье: id, имя, участники, часовой пояс, токены за месяц.

    Подзапросами (не общий outerjoin двух таблиц сразу) — иначе декартово
    произведение members × usage-строк раздувает SUM токенов.
    """
    boundary = _month_boundary(now)
    members_sq = (
        select(FamilyMember.family_id, func.count().label("members"))
        .group_by(FamilyMember.family_id)
        .subquery()
    )
    tokens_sq = (
        select(
            LlmUsage.family_id,
            func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out).label("tokens"),
        )
        .where(LlmUsage.created_at > boundary)
        .group_by(LlmUsage.family_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Family.id, Family.name, Family.timezone, Family.sub_until,
                func.coalesce(members_sq.c.members, 0),
                func.coalesce(tokens_sq.c.tokens, 0),
            )
            .outerjoin(members_sq, members_sq.c.family_id == Family.id)
            .outerjoin(tokens_sq, tokens_sq.c.family_id == Family.id)
            .order_by(Family.id)
        )
    ).all()
    return [
        {"id": r[0], "name": r[1], "timezone": r[2], "sub_until": r[3],
         "members": int(r[4]), "tokens_month": int(r[5])}
        for r in rows
    ]


async def extend_family_subscription(
    session: AsyncSession, *, family_id: int, days: int, today: DateType
) -> DateType | None:
    """Продлить подписку на days от max(today, текущее окончание). None — семьи нет."""
    family = await session.get(Family, family_id)
    if family is None:
        return None
    base = family.sub_until if family.sub_until and family.sub_until > today else today
    family.sub_until = base + timedelta(days=days)
    await session.flush()
    return family.sub_until


async def revoke_family_subscription(session: AsyncSession, *, family_id: int) -> bool:
    family = await session.get(Family, family_id)
    if family is None:
        return False
    family.sub_until = None
    await session.flush()
    return True


async def add_subscription_request(
    session: AsyncSession, *, family_id: int, telegram_user_id: int
) -> bool:
    """Заявка «хочу подписку». True — новая; False — по семье уже есть.

    Select — быстрый путь без похода в savepoint в общем случае; сама вставка
    защищена unique(family_id) через savepoint, так что гонка двух одновременных
    заявок одной семьи не приводит к необработанному IntegrityError наружу."""
    existing = (
        await session.execute(
            select(SubscriptionRequest.id).where(
                SubscriptionRequest.family_id == family_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    try:
        async with session.begin_nested():
            session.add(
                SubscriptionRequest(family_id=family_id, telegram_user_id=telegram_user_id)
            )
    except IntegrityError:
        return False
    return True


async def count_subscription_requests(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(SubscriptionRequest)
    )
    return int(result.scalar_one())


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
