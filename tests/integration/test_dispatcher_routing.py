"""Дымовой тест маршрутизации через реальный Dispatcher.

Ловит интеграционные швы, которые не видны юнит-тестам фильтров:
данные из FamilyResolverMiddleware должны быть доступны фильтру HasFamily,
т.е. мидлварь обязана быть OUTER (выполняется до проверки фильтров).
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.types import Chat, Message, Update, User

from bot.main import create_dispatcher
from core.db import Base, get_engine, session_scope
from core.services.family_service import create_family

TG_ID = 424242


def _make_update(text: str) -> Update:
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=TG_ID, type="private"),
            from_user=User(id=TG_ID, is_bot=False, first_name="Тест"),
            text=text,
        ),
    )


async def test_hasfamily_command_reaches_handler():
    """Юзер с семьёй шлёт /menu — хендлер должен ответить, а не молчать."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with session_scope() as session:
            await create_family(
                session,
                telegram_user_id=TG_ID,
                display_name="Тест",
                profile_md="тестовый профиль",
                timezone="UTC",
                plan_slots=["lunch", "dinner"],
            )

        dp = create_dispatcher()
        bot = Bot(token="42:TEST")
        with patch.object(Message, "answer", new_callable=AsyncMock) as answer:
            await dp.feed_update(bot, _make_update("/menu"))

        answer.assert_awaited_once()
        assert "Меню не загружено" in answer.await_args.args[0]
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
