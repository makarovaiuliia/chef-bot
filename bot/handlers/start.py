from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.onboarding import start_onboarding
from bot.keyboards import kb_main
from core import emoji

router = Router()

_HELP_TEXT = (
    "Я — семейный помощник для меню и покупок.\n\n"
    "Команды:\n"
    f"{emoji.MENU} /menu — текущее меню\n"
    f"{emoji.TODAY} /today — что готовить сегодня\n"
    f"{emoji.SHOPPING} /list — список покупок\n"
    f"{emoji.ADD} /add — добавить пункт в список\n"
    f"{emoji.PROFILE} /profile — профиль семьи\n"
    f"{emoji.FAMILY} /family — управление семьей\n"
    f"{emoji.INVITE} /invite — пригласить в семью\n"
    f"{emoji.HELP} /help — справка"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, family=None) -> None:
    # deep-link inv_<код> обрабатывается в bot/handlers/family.py (роутер регистрируется раньше)
    if family is not None:
        await message.answer(_HELP_TEXT, reply_markup=kb_main())
        return
    await start_onboarding(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT, reply_markup=kb_main())
