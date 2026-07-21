from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.onboarding import start_onboarding
from bot.keyboards import kb_main
from config import get_settings
from core import emoji

router = Router()

def help_text() -> str:
    lines = [
        "Я — семейный помощник для меню и покупок.",
        "",
        "Команды:",
        f"{emoji.MENU} /menu — текущее меню",
        f"{emoji.TODAY} /today — что готовить сегодня",
        *(
            [f"{emoji.MENU} /plan — спланировать меню"]
            if get_settings().planning_enabled
            else []
        ),
        f"{emoji.SHOPPING} /list — список покупок",
        f"{emoji.ADD} /add — добавить пункт в список",
        f"{emoji.PROFILE} /profile — профиль семьи",
        f"{emoji.FAMILY} /family — управление семьей",
        f"{emoji.INVITE} /invite — пригласить в семью",
        f"{emoji.HELP} /help — справка",
    ]
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, family=None) -> None:
    # deep-link inv_<код> обрабатывается в bot/handlers/family.py (роутер регистрируется раньше)
    if family is not None:
        await message.answer(help_text(), reply_markup=kb_main())
        return
    await start_onboarding(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text(), reply_markup=kb_main())
