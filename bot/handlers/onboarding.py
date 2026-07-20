"""Онбординг нового юзера: опрос → генерация профиля → создание семьи."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger

from bot.formatting import md_to_telegram_html
from bot.fsm import Onboarding
from bot.keyboards import (
    kb_cook_minutes,
    kb_household,
    kb_multiselect,
    kb_profile_confirm,
    kb_skip,
)
from core import emoji
from core.exceptions import LLMError
from core.repositories import log_llm_usage
from core.services.family_service import create_family
from core.services.onboarding import OnboardingAnswers, generate_profile

router = Router()

SLOT_OPTIONS = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}
RESTRICTION_OPTIONS = {
    "lactose": "Без лактозы",
    "gluten": "Без глютена",
    "onion_garlic": "Без лука/чеснока",
    "nuts": "Без орехов",
    "pork": "Без свинины",
}
PREFERENCE_OPTIONS = {
    "chicken": "Курица",
    "fish": "Рыба/морепродукты",
    "beef": "Говядина",
    "pork": "Свинина",
    "veg": "Больше овощей",
    "euro": "Европейская кухня",
    "asia": "Азиатская кухня",
}


async def start_onboarding(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Onboarding.household)
    await message.answer(
        "Настроим бота под вашу семью — 6 коротких вопросов.\n\n1/6. Сколько человек в семье?",
        reply_markup=kb_household(),
    )


@router.callback_query(Onboarding.household, F.data.startswith("onb:hh:"))
async def on_household(cb: CallbackQuery, state: FSMContext) -> None:
    count = cb.data.split(":")[-1]
    await state.update_data(household=f"{count} чел.", slots=[])
    await state.set_state(Onboarding.slots)
    await cb.message.edit_text(
        "2/6. Какие приемы пищи планировать?",
        reply_markup=kb_multiselect("onb:slot", SLOT_OPTIONS, set()),
    )
    await cb.answer()


async def _toggle(
    cb: CallbackQuery, state: FSMContext, key: str, field: str, prefix: str, options: dict[str, str]
) -> None:
    data = await state.get_data()
    selected: list[str] = data.get(field, [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(**{field: selected})
    await cb.message.edit_reply_markup(reply_markup=kb_multiselect(prefix, options, set(selected)))
    await cb.answer()


@router.callback_query(Onboarding.slots, F.data.startswith("onb:slot:"))
async def on_slot(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "slots", "onb:slot", SLOT_OPTIONS)
        return
    data = await state.get_data()
    if not data.get("slots"):
        await cb.answer("Выберите хотя бы один прием пищи", show_alert=True)
        return
    await state.update_data(restrictions=[])
    await state.set_state(Onboarding.restrictions)
    await cb.message.edit_text(
        "3/6. Аллергии и исключения? Отметьте кнопками и/или напишите свое сообщением.",
        reply_markup=kb_multiselect("onb:restr", RESTRICTION_OPTIONS, set()),
    )
    await cb.answer()


@router.callback_query(Onboarding.restrictions, F.data.startswith("onb:restr:"))
async def on_restriction(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "restrictions", "onb:restr", RESTRICTION_OPTIONS)
        return
    await state.set_state(Onboarding.cook_minutes)
    await cb.message.edit_text(
        "4/6. Сколько времени готовы тратить на активную готовку одного блюда?",
        reply_markup=kb_cook_minutes(),
    )
    await cb.answer()


@router.message(Onboarding.restrictions, F.text)
async def on_restriction_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    restrictions = data.get("restrictions", [])
    restrictions.append(message.text.strip())
    await state.update_data(restrictions=restrictions)
    await message.answer(f"Записал: {message.text.strip()}. Отметьте еще или жмите «Готово» выше.")


@router.callback_query(Onboarding.cook_minutes, F.data.startswith("onb:cook:"))
async def on_cook(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cook_minutes=int(cb.data.split(":")[-1]), preferences=[])
    await state.set_state(Onboarding.preferences)
    await cb.message.edit_text(
        "5/6. Что любите? Отметьте кнопками и/или напишите свое сообщением.",
        reply_markup=kb_multiselect("onb:pref", PREFERENCE_OPTIONS, set()),
    )
    await cb.answer()


@router.callback_query(Onboarding.preferences, F.data.startswith("onb:pref:"))
async def on_pref(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "preferences", "onb:pref", PREFERENCE_OPTIONS)
        return
    await state.set_state(Onboarding.extra)
    await cb.message.edit_text(
        "6/6. Что еще важно знать? (техника, стиль питания, нелюбимые продукты...)\n"
        "Напишите сообщением или пропустите.",
        reply_markup=kb_skip("onb:extra:skip"),
    )
    await cb.answer()


@router.message(Onboarding.preferences, F.text)
async def on_pref_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prefs = data.get("preferences", [])
    prefs.append(message.text.strip())
    await state.update_data(preferences=prefs)
    await message.answer(f"Записал: {message.text.strip()}. Отметьте еще или жмите «Готово» выше.")


async def _ask_city(target_message: Message, state: FSMContext) -> None:
    await state.set_state(Onboarding.city)
    await target_message.answer(
        "И последнее: в каком городе живете? (нужно для времени напоминаний)",
        reply_markup=kb_skip("onb:city:skip"),
    )


@router.message(Onboarding.extra, F.text)
async def on_extra_text(message: Message, state: FSMContext) -> None:
    await state.update_data(extra=message.text.strip())
    await _ask_city(message, state)


@router.callback_query(Onboarding.extra, F.data == "onb:extra:skip")
async def on_extra_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(extra=None)
    await _ask_city(cb.message, state)
    await cb.answer()


@router.message(Onboarding.city, F.text)
async def on_city_text(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip())
    await _generate_and_show(message, state)


@router.callback_query(Onboarding.city, F.data == "onb:city:skip")
async def on_city_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=None)
    await _generate_and_show(cb.message, state)
    await cb.answer()


def _labels(keys: list[str], options: dict[str, str]) -> list[str]:
    return [options.get(k, k) for k in keys]


async def _generate_and_show(message: Message, state: FSMContext) -> None:
    from core.services.onboarding import get_llm_client  # локальный импорт для моков

    data = await state.get_data()
    answers = OnboardingAnswers(
        household=data["household"],
        slots=data["slots"],
        restrictions=_labels(data.get("restrictions", []), RESTRICTION_OPTIONS),
        cook_minutes=data.get("cook_minutes", 40),
        preferences=_labels(data.get("preferences", []), PREFERENCE_OPTIONS),
        extra=data.get("extra"),
        city=data.get("city"),
    )
    placeholder = await message.answer(f"{emoji.WAIT} Составляю профиль семьи...")
    try:
        result = await generate_profile(get_llm_client(), answers)
    except LLMError:  # LLMInvalidResponse — его подкласс
        logger.exception("onboarding: profile generation failed")
        await placeholder.edit_text("Не получилось составить профиль. Попробуйте еще раз: /start")
        await state.clear()
        return
    await state.update_data(
        profile_md=result.profile_md,
        timezone=result.timezone,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    await state.set_state(Onboarding.confirm)
    await placeholder.edit_text(
        f"Вот профиль вашей семьи:\n\n{md_to_telegram_html(result.profile_md)}\n\n"
        "Его всегда можно изменить командой /profile.",
        reply_markup=kb_profile_confirm(),
    )


@router.callback_query(Onboarding.confirm, F.data == "onb:profile:ok")
async def on_profile_ok(cb: CallbackQuery, state: FSMContext, db_session, family=None) -> None:
    if family is not None:
        # Юзер уже вступил в семью (например, по инвайту посреди онбординга).
        await state.clear()
        await cb.message.edit_text("Вы уже состоите в семье.")
        await cb.answer()
        return
    data = await state.get_data()
    family, _member = await create_family(
        db_session,
        telegram_user_id=cb.from_user.id,
        display_name=cb.from_user.full_name,
        profile_md=data["profile_md"],
        timezone=data["timezone"],
        plan_slots=data["slots"],
    )
    await log_llm_usage(
        db_session,
        family_id=family.id,
        operation="profile",
        tokens_in=data.get("tokens_in", 0),
        tokens_out=data.get("tokens_out", 0),
    )
    await state.clear()
    await cb.message.edit_text(
        f"{emoji.DONE} Готово! Семья создана.\n\n"
        "Пригласить близких: /invite\n"
        "Профиль семьи: /profile\n"
        "Справка: /help"
    )
    await cb.answer()


@router.callback_query(Onboarding.confirm, F.data == "onb:profile:edit")
async def on_profile_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.edit_profile)
    await cb.message.answer(
        "Пришлите новую версию профиля целиком (текущий текст выше — скопируйте и поправьте):",
        reply_markup=ForceReply(),
    )
    await cb.answer()


@router.message(Onboarding.edit_profile, F.text)
async def on_profile_edited(message: Message, state: FSMContext) -> None:
    await state.update_data(profile_md=message.text)
    await state.set_state(Onboarding.confirm)
    await message.answer(
        f"Обновленный профиль:\n\n{md_to_telegram_html(message.text)}",
        reply_markup=kb_profile_confirm(),
    )


@router.message()
async def no_family_fallback(message: Message, family=None) -> None:
    if family is None:
        await message.answer("Сначала настроим бота: нажмите /start")
