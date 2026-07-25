"""Per-family планировщик: дайджест и напоминания в локальный digest_hour семьи.

Тик каждые 15 минут: для каждой семьи, чей локальный час совпал с digest_hour
и которой сегодня еще не слали, отправляется утренний дайджест (если включен).
Дедупликация — атомарная заявка в БД (families.last_digest_on): рестарт в тот
же час или вторая реплика больше не дают повторный дайджест.
При ошибке обработки семьи заявка возвращается — ретрай на следующем тике в
пределах того же часа.
"""
import asyncio
from datetime import UTC, datetime
from datetime import date as DateType
from zoneinfo import ZoneInfo

from aiogram import Bot
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.formatting import md_to_telegram_html
from bot.keyboards import kb_plan_reminder
from config import get_settings
from core import repositories
from core.db import Family
from core.repositories import count_llm_operations, get_family_members
from core.services import digest, reminders
from core.services.family_service import get_admins
from core.services.limits import subscription_active

TICK_SECONDS = 900  # 15 минут


def _family_tz(family) -> ZoneInfo:
    try:
        return ZoneInfo(family.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def families_due(families, *, now: datetime) -> list[Family]:
    """Семьи, у которых сейчас локальный digest_hour и сегодня еще не слали.

    Отбор по колонке last_digest_on — грубый фильтр, чтобы не дергать БД на
    каждую семью. Право на отправку все равно берется атомарной заявкой в
    _tick_family: между этой проверкой и заявкой могла вклиниться другая реплика.
    """
    due = []
    for f in families:
        local = now.astimezone(_family_tz(f))
        if local.hour == f.digest_hour and f.last_digest_on != local.date():
            due.append(f)
    return due


async def _send_family_digest(
    bot: Bot, sessionmaker: async_sessionmaker, family, today: DateType
) -> None:
    async with sessionmaker() as session:
        text = await digest.build_morning_digest(
            session, family_id=family.id, today=today
        )
        members = await get_family_members(session, family.id)
    if text is None:
        return
    for member in members:
        try:
            await bot.send_message(member.telegram_user_id, md_to_telegram_html(text))
        except Exception:
            logger.exception("scheduler: send failed user_id={}", member.telegram_user_id)


async def _send_plan_reminder(
    bot: Bot, sessionmaker: async_sessionmaker, family, today: DateType
) -> None:
    async with sessionmaker() as session:
        due = await reminders.plan_reminder_due(session, family_id=family.id, today=today)
        if due and not subscription_active(family, today):
            used = await count_llm_operations(
                session, family_id=family.id, operation="menu_gen"
            )
            if used >= get_settings().trial_menu_gen_limit:
                due = False  # триал исчерпан — не зовем в dead-end
        admins = await get_admins(session, family_id=family.id) if due else []
    for admin in admins:
        try:
            await bot.send_message(
                admin.telegram_user_id,
                "Меню заканчивается через 2 дня. Спланировать следующее?",
                reply_markup=kb_plan_reminder(),
            )
        except Exception:
            logger.exception(
                "scheduler: plan reminder failed admin_id={}", admin.telegram_user_id
            )


async def _process_due_family(
    bot: Bot, sessionmaker: async_sessionmaker, family, today: DateType
) -> None:
    """Все рассылки семьи в ее digest-час. Точка расширения для напоминаний."""
    if family.digest_enabled:
        await _send_family_digest(bot, sessionmaker, family, today)
    await _send_plan_reminder(bot, sessionmaker, family, today)


async def _tick_family(
    bot: Bot, sessionmaker: async_sessionmaker, family: Family, now: datetime
) -> None:
    """Обработать одну семью, взяв право на отправку атомарной заявкой.

    Заявка берется ДО рассылки — иначе вторая реплика успеет отправить свой
    дайджест, пока мы шлем свой. При ошибке заявка возвращается, чтобы
    отправка повторилась на следующем тике в пределах того же часа.
    """
    local_today = now.astimezone(_family_tz(family)).date()
    previous = family.last_digest_on
    async with sessionmaker() as session:
        claimed = await repositories.claim_digest_slot(
            session, family_id=family.id, local_date=local_today
        )
    if not claimed:
        logger.debug("scheduler: family {} already claimed for {}", family.id, local_today)
        return
    family.last_digest_on = local_today
    try:
        await _process_due_family(bot, sessionmaker, family, local_today)
    except Exception:
        logger.exception("scheduler: family {} failed", family.id)
        family.last_digest_on = previous
        async with sessionmaker() as session:
            await repositories.release_digest_slot(
                session, family_id=family.id, previous=previous
            )


async def _scheduler_loop(bot: Bot, sessionmaker: async_sessionmaker) -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        now = datetime.now(UTC)
        try:
            async with sessionmaker() as session:
                families = list((await session.execute(select(Family))).scalars().all())
        except Exception:
            logger.exception("scheduler: failed to load families")
            continue
        for family in families_due(families, now=now):
            await _tick_family(bot, sessionmaker, family, now)


def start_scheduler(bot: Bot, sessionmaker: async_sessionmaker) -> list[asyncio.Task]:
    """Spawn background tasks. Caller is responsible for cancelling them at shutdown."""
    return [asyncio.create_task(_scheduler_loop(bot, sessionmaker), name="digest")]


__all__ = ["start_scheduler", "families_due", "TICK_SECONDS"]
