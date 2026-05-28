from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

_HELP_TEXT = (
    "Привет! Я бот-помощник для меню и покупок.\n\n"
    "Команды:\n"
    "/menu — текущее меню\n"
    "/today — что готовить сегодня\n"
    "/recipe — рецепт текущего приёма\n"
    "/list — список покупок\n"
    "/add &lt;название&gt; — добавить пункт в список\n"
    "/help — справка\n\n"
    "Чтобы загрузить новое меню — пришли JSON-файл документом.\n\n"
    "Также я понимаю свободный текст: спроси про меню, попроси заменить "
    "блюдо или отметить пункт купленным."
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(_HELP_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)
