import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from loguru import logger

from bot.handlers import family as family_handler
from bot.handlers import freetext as freetext_handler
from bot.handlers import load as load_handler
from bot.handlers import menu as menu_handler
from bot.handlers import onboarding as onboarding_handler
from bot.handlers import plan as plan_handler
from bot.handlers import profile as profile_handler
from bot.handlers import shopping as shopping_handler
from bot.handlers import start as start_handler
from bot.middlewares import FamilyResolverMiddleware
from bot.scheduler import start_scheduler
from config import get_settings
from core.db import get_sessionmaker


def bot_commands(*, planning_enabled: bool) -> list[BotCommand]:
    commands = [
        BotCommand(command="menu", description="Текущее меню"),
        BotCommand(command="today", description="Что готовить сегодня"),
        BotCommand(command="list", description="Список покупок"),
        BotCommand(command="add", description="Добавить пункт в список"),
        BotCommand(command="profile", description="Профиль семьи"),
        BotCommand(command="family", description="Управление семьей"),
        BotCommand(command="invite", description="Пригласить в семью"),
        BotCommand(command="help", description="Справка"),
    ]
    if planning_enabled:
        commands.insert(2, BotCommand(command="plan", description="Спланировать меню"))
    return commands


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level)


def create_dispatcher() -> Dispatcher:
    """Собирает Dispatcher с middleware и роутерами (без сайд-эффектов Telegram API)."""
    dp = Dispatcher()

    # ВАЖНО: именно outer — фильтры (HasFamily/IsAdmin) читают family из data,
    # а inner-middleware выполняется уже ПОСЛЕ проверки фильтров.
    dp.message.outer_middleware(FamilyResolverMiddleware())
    dp.callback_query.outer_middleware(FamilyResolverMiddleware())

    dp.include_router(family_handler.router)  # deep-link join + /family, /invite — ПЕРВЫМ
    dp.include_router(start_handler.router)  # /start, /help
    dp.include_router(profile_handler.router)
    dp.include_router(plan_handler.router)
    dp.include_router(menu_handler.router)
    dp.include_router(shopping_handler.router)
    dp.include_router(load_handler.router)
    dp.include_router(freetext_handler.router)  # HasFamily: catch-all для «семейных»
    dp.include_router(onboarding_handler.router)  # FSM + fallback для юзеров без семьи — ПОСЛЕДНИЙ
    return dp


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    await bot.set_my_commands(bot_commands(planning_enabled=settings.planning_enabled))
    scheduler_tasks = start_scheduler(bot, get_sessionmaker())
    logger.info("starting bot polling")
    try:
        await dp.start_polling(bot)
    finally:
        for task in scheduler_tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
