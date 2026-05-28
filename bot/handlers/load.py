from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.fsm import LoadConfirm
from bot.keyboards import kb_confirm_overwrite
from core.db import Family
from core.services import menu_loader
from core.services.menu_loader import MenuFile, MenuLoadError

router = Router()

_MAX_BYTES = 1_000_000


def _success_text(menu) -> str:
    return (
        f"✅ Меню загружено: {menu.days_count} дн. с "
        f"{menu.start_date.strftime('%d.%m.%Y')}."
    )


@router.message(F.document)
async def handle_menu_file(
    message: Message,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
    bot: Bot,
) -> None:
    doc = message.document
    if doc is None or not doc.file_name:
        return
    if not doc.file_name.lower().endswith(".json"):
        await message.answer("Жду JSON-файл с меню (.json).")
        return
    if doc.file_size and doc.file_size > _MAX_BYTES:
        await message.answer("Файл слишком большой.")
        return

    buf = await bot.download(doc.file_id)
    raw = buf.read()
    today = date.today()
    await state.clear()

    try:
        preview = await menu_loader.preview_load(
            db_session, family_id=family.id, raw=raw, today=today
        )
    except MenuLoadError as e:
        await message.answer(f"Не получилось загрузить меню: {e}")
        return
    except Exception as e:
        logger.exception("menu preview failed: {}", e)
        await message.answer("Не получилось загрузить меню. Попробуй ещё раз.")
        return

    if not preview.conflicting_dates:
        try:
            menu = await menu_loader.commit_load(
                db_session,
                family_id=family.id,
                parsed=preview.parsed,
                today=today,
            )
        except Exception as e:
            logger.exception("menu commit failed: {}", e)
            await message.answer("Не получилось загрузить меню. Попробуй ещё раз.")
            return
        await message.answer(_success_text(menu))
        return

    dates_str = ", ".join(
        d.strftime("%d.%m.%Y") for d in sorted(preview.conflicting_dates)
    )
    await state.set_state(LoadConfirm.awaiting)
    await state.update_data(parsed_json=preview.parsed.model_dump_json())
    await message.answer(
        f"На даты {dates_str} уже загружено меню. "
        "Вы уверены, что хотите перезатереть?",
        reply_markup=kb_confirm_overwrite(),
    )


@router.callback_query(LoadConfirm.awaiting, F.data == "load:yes")
async def cb_load_yes(
    cb: CallbackQuery,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    parsed_json = data.get("parsed_json")
    await state.clear()
    if not parsed_json:
        await cb.message.edit_text("Не нашёл данные загрузки. Пришли файл ещё раз.")
        await cb.answer()
        return
    parsed = MenuFile.model_validate_json(parsed_json)
    today = date.today()
    try:
        menu = await menu_loader.commit_load(
            db_session, family_id=family.id, parsed=parsed, today=today
        )
    except Exception as e:
        logger.exception("menu commit failed: {}", e)
        await cb.message.edit_text("Не получилось загрузить меню. Попробуй ещё раз.")
        await cb.answer()
        return
    await cb.message.edit_text(_success_text(menu))
    await cb.answer()


@router.callback_query(LoadConfirm.awaiting, F.data == "load:no")
async def cb_load_no(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()
