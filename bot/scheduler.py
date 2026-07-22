"""Per-family планировщик: дайджест и напоминания в локальный digest_hour семьи.

Тик каждые 15 минут: для каждой семьи, чей локальный час совпал с digest_hour
и которой сегодня еще не слали, отправляется утренний дайджест (если включен).
Дедупликация — in-memory (после рестарта в тот же час возможен повтор — MVP).
При ошибке обработки семьи last_sent не проставляется — ретрай на следующем
тике в пределах того же часа.
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
from core.db import Family
from core.repositories import get_family_members
from core.services import digest, reminders
from core.services.family_service import get_admins

TICK_SECONDS = 900  # 15 минут


def _family_tz(family) -> ZoneInfo:
    try:
        return ZoneInfo(family.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def families_due(
    families, *, now: datetime, last_sent: dict[int, DateType]
) -> list[Family]:
    """Семьи, у которых сейчас локальный digest_hour и сегодня еще не слали."""
    due = []
    for f in families:
        local = now.astimezone(_family_tz(f))
        if local.hour == f.digest_hour and last_sent.get(f.id) != local.date():
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
    if get_settings().planning_enabled:
        await _send_plan_reminder(bot, sessionmaker, family, today)


async def _tick_family(
    bot: Bot,
    sessionmaker: async_sessionmaker,
    family: Family,
    now: datetime,
    last_sent: dict[int, DateType],
) -> None:
    """Process one due family; mark last_sent only on success (retry on failure)."""
    local_today = now.astimezone(_family_tz(family)).date()
    try:
        await _process_due_family(bot, sessionmaker, family, local_today)
    except Exception:
        logger.exception("scheduler: family {} failed", family.id)
        return
    last_sent[family.id] = local_today


async def _scheduler_loop(bot: Bot, sessionmaker: async_sessionmaker) -> None:
    last_sent: dict[int, DateType] = {}
    while True:
        await asyncio.sleep(TICK_SECONDS)
        now = datetime.now(UTC)
        try:
            async with sessionmaker() as session:
                families = list((await session.execute(select(Family))).scalars().all())
        except Exception:
            logger.exception("scheduler: failed to load families")
            continue
        for family in families_due(families, now=now, last_sent=last_sent):
            await _tick_family(bot, sessionmaker, family, now, last_sent)


def start_scheduler(bot: Bot, sessionmaker: async_sessionmaker) -> list[asyncio.Task]:
    """Spawn background tasks. Caller is responsible for cancelling them at shutdown."""
    return [asyncio.create_task(_scheduler_loop(bot, sessionmaker), name="digest")]


__all__ = ["start_scheduler", "families_due", "TICK_SECONDS"]
