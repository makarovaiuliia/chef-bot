from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core import emoji

router = Router()

_HELP_TEXT = (
    "Привет! Я бот-помощник для меню и покупок.\n\n"
    "Команды:\n"
    f"{emoji.MENU} /menu — текущее меню\n"
    f"{emoji.TODAY} /today — что готовить сегодня\n"
    f"{emoji.SHOPPING} /list — список покупок\n"
    f"{emoji.ADD} /add &lt;название&gt; — добавить пункт в список\n"
    f"{emoji.HELP} /help — справка\n\n"
    "Чтобы загрузить новое меню — пришли JSON-файл документом.\n\n"
    "Также я понимаю свободный текст: спроси про меню, попроси рецепт "
    "(«дай рецепт на ужин»), заменить блюдо или отметить пункт купленным."
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(_HELP_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)
