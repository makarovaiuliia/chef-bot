import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from bot.handlers import freetext as freetext_handler
from bot.handlers import menu as menu_handler
from bot.handlers import plan as plan_handler
from bot.handlers import recipe as recipe_handler
from bot.handlers import shopping as shopping_handler
from bot.handlers import start as start_handler
from bot.middlewares import AllowlistMiddleware, FamilyResolverMiddleware
from bot.scheduler import start_scheduler
from config import get_settings
from core.db import get_sessionmaker


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.middleware(AllowlistMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware())
    dp.message.middleware(FamilyResolverMiddleware())
    dp.callback_query.middleware(FamilyResolverMiddleware())

    dp.include_router(start_handler.router)
    dp.include_router(plan_handler.router)
    dp.include_router(menu_handler.router)
    dp.include_router(recipe_handler.router)
    dp.include_router(shopping_handler.router)
    dp.include_router(freetext_handler.router)  # MUST be last — catches plain text

    scheduler_tasks = start_scheduler(bot, get_sessionmaker())
    logger.info("starting bot polling")
    try:
        await dp.start_polling(bot)
    finally:
        for task in scheduler_tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
