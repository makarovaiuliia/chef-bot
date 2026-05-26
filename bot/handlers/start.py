from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-помощник для планирования меню.\n\n"
        "Команды:\n"
        "/plan — спланировать меню\n"
        "/menu — показать текущее меню\n"
        "/today — что готовить сегодня\n"
        "/recipe — рецепт текущего приёма\n"
        "/list — список покупок\n"
        "/help — справка\n\n"
        "Также я понимаю свободный текст — просто напиши, что хочешь."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)
