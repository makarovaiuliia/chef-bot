"""Кнопки reply-клавиатуры маппятся на те же хэндлеры, что и команды."""
from unittest.mock import AsyncMock

from aiogram import F

from bot.handlers import family, menu, profile, shopping
from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY


def _magic_repr(magic) -> str:
    """Структурное представление MagicFilter.

    aiogram/magic_filter не переопределяет __repr__: голый repr(magic_filter)
    отдает id объекта в памяти, поэтому две структурно одинаковые магии
    (например, две F.text == "...") никогда не совпадут строкой. Собираем
    репрезентацию из внутренних _operations (тоже __slots__-объекты без
    repr), где и лежит реальное сравнение (имя атрибута, компаратор, значение).
    Сравнение полагается на то, что компараторы вроде operator.eq/in_op/not_ —
    синглтоны модуля magic_filter: с не-синглтон компаратором (например, lambda)
    репрезентация двух структурно одинаковых магий разойдется — тест шумно
    упадет (false negative), но не пройдет молча.
    """
    return repr(
        [
            (type(op).__name__, {s: getattr(op, s, None) for s in op.__slots__})
            for op in magic._operations
        ]
    )


def _registered_filters(router):
    """[(callback_name, [filter_reprs])] для всех message-хэндлеров роутера."""
    result = []
    for h in router.message.handlers:
        reprs = [
            _magic_repr(f.magic) if f.magic is not None else repr(f.callback)
            for f in h.filters
        ]
        result.append((h.callback.__name__, reprs))
    return result


def _has_text_binding(router, func_name: str, btn_text: str) -> bool:
    magic = _magic_repr(F.text == btn_text)
    return any(
        name == func_name and any(magic in f for f in filters)
        for name, filters in _registered_filters(router)
    )


def test_btn_today_bound_to_cmd_today():
    assert _has_text_binding(menu.router, "cmd_today", BTN_TODAY)


def test_btn_family_bound_to_both_family_views():
    assert _has_text_binding(family.router, "cmd_family", BTN_FAMILY)
    assert _has_text_binding(family.router, "cmd_family_member_view", BTN_FAMILY)


def test_btn_add_bound():
    assert _has_text_binding(shopping.router, "btn_add", BTN_ADD)


async def test_btn_add_asks_what_to_add():
    message = AsyncMock()
    await shopping.btn_add(message)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == shopping._ADD_PROMPT


async def test_cmd_help_attaches_main_keyboard():
    from bot.handlers import start
    from bot.keyboards import kb_main

    message = AsyncMock()
    await start.cmd_help(message)
    assert message.answer.await_args.kwargs["reply_markup"] == kb_main()


async def test_cmd_start_with_family_attaches_main_keyboard():
    from bot.handlers import start
    from bot.keyboards import kb_main

    message = AsyncMock()
    state = AsyncMock()
    await start.cmd_start(message, state, family=object())
    assert message.answer.await_args.kwargs["reply_markup"] == kb_main()


def test_profile_waiting_text_handler_excludes_keyboard_buttons():
    """Тап по кнопке клавиатуры во время редактирования профиля не должен
    матчиться хэндлером on_new_text (иначе он затрет profile_md текстом кнопки).
    """
    exclusion = _magic_repr(~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY}))
    reprs_by_handler = _registered_filters(profile.router)
    on_new_text_filters = next(
        filters for name, filters in reprs_by_handler if name == "on_new_text"
    )
    assert any(exclusion in f for f in on_new_text_filters)


def test_button_routers_registered_before_freetext(dispatcher):
    """Порядок include_router — контракт: кнопки не должны утекать в
    ИИ-чат (freetext). Роутеры menu/shopping/family обязаны идти раньше
    freetext-роутера в собранном Dispatcher.
    """
    from bot.handlers import freetext

    sub_routers = list(dispatcher.sub_routers)

    freetext_index = sub_routers.index(freetext.router)
    for button_router in (menu.router, shopping.router, family.router):
        assert sub_routers.index(button_router) < freetext_index
