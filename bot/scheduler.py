"""Background scheduler for the daily morning digest (9:00).

The digest also carries the open shopping-list reminder, so there is no
separate evening reminder. Native asyncio — one long-running task that
computes the next BKK-local fire time and sleeps. Stateless across restarts.
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.formatting import md_to_telegram_html
from core.db import FamilyMember
from core.services import digest

BKK = ZoneInfo("Asia/Bangkok")
DIGEST_HOUR = 9


def seconds_until_next(
    hour: int, minute: int, tz: ZoneInfo, *, now: datetime
) -> float:
    """Seconds from `now` until the next occurrence of HH:MM in tz.

    If `now` lands exactly on HH:MM, returns 24h (skip to tomorrow) to avoid
    a tight re-fire loop.
    """
    now_local = now.astimezone(tz)
    target_today = now_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target_today <= now_local:
        target_today += timedelta(days=1)
    return (target_today - now_local).total_seconds()


async def _send_to_all_members(
    bot: Bot, sessionmaker: async_sessionmaker, build_text
) -> None:
    """Iterate every family_member, build per-family text, send if non-None."""
    async with sessionmaker() as session:
        members = list(
            (await session.execute(select(FamilyMember))).scalars().all()
        )

    # Group by family_id to avoid building the same text twice.
    by_family: dict[int, list[FamilyMember]] = {}
    for m in members:
        by_family.setdefault(m.family_id, []).append(m)

    for family_id, fam_members in by_family.items():
        async with sessionmaker() as session:
            try:
                text = await build_text(session, family_id=family_id)
            except Exception:
                logger.exception("scheduler: build text failed family_id={}", family_id)
                continue
        if text is None:
            continue
        for member in fam_members:
            try:
                await bot.send_message(
                    member.telegram_user_id, md_to_telegram_html(text)
                )
            except Exception:
                logger.exception(
                    "scheduler: send failed user_id={}", member.telegram_user_id
                )


async def _digest_builder(today):
    async def build(session, *, family_id: int) -> str | None:
        return await digest.build_morning_digest(
            session, family_id=family_id, today=today
        )
    return build


async def _morning_digest_loop(bot: Bot, sessionmaker: async_sessionmaker) -> None:
    while True:
        delay = seconds_until_next(DIGEST_HOUR, 0, BKK, now=datetime.now(tz=BKK))
        logger.info("scheduler: next digest in {:.0f}s", delay)
        await asyncio.sleep(delay)
        today = datetime.now(tz=BKK).date()
        build = await _digest_builder(today)
        await _send_to_all_members(bot, sessionmaker, build)


def start_scheduler(
    bot: Bot, sessionmaker: async_sessionmaker
) -> list[asyncio.Task]:
    """Spawn background tasks. Caller is responsible for cancelling them at shutdown."""
    return [
        asyncio.create_task(_morning_digest_loop(bot, sessionmaker), name="digest"),
    ]


__all__ = ["start_scheduler", "seconds_until_next", "BKK"]
