"""Глобальный обработчик ошибок: извинение юзеру, алерт оператору, дроссель."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot import errors
from config import get_settings


@pytest.fixture(autouse=True)
def _clean_throttle():
    errors.reset_throttle()
    yield
    errors.reset_throttle()


@pytest.fixture
def superadmin(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "superadmin_ids", [999], raising=False)
    return 999


def _message_update(text="привет", chat_id=555, user_id=111):
    return SimpleNamespace(
        message=SimpleNamespace(
            text=text,
            chat=SimpleNamespace(id=chat_id),
            from_user=SimpleNamespace(id=user_id),
        ),
        callback_query=None,
    )


def _callback_update(data="plan:days:3", chat_id=555, user_id=111):
    callback = AsyncMock()
    callback.data = data
    callback.from_user = SimpleNamespace(id=user_id)
    callback.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))
    return SimpleNamespace(message=None, callback_query=callback)


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=SimpleNamespace(), message=message)


# --- безобидные ошибки Telegram ---


@pytest.mark.parametrize(
    "text",
    [
        "Bad Request: message is not modified",
        "Bad Request: message to edit not found",
        "Bad Request: query is too old and response timeout expired",
    ],
)
def test_benign_telegram_errors(text):
    assert errors.is_benign(_bad_request(text)) is True


def test_blocked_by_user_is_benign():
    exc = TelegramForbiddenError(method=SimpleNamespace(), message="bot was blocked")
    assert errors.is_benign(exc) is True


def test_real_bad_request_is_not_benign():
    assert errors.is_benign(_bad_request("Bad Request: chat not found")) is False


def test_arbitrary_exception_is_not_benign():
    assert errors.is_benign(ValueError("нежданчик")) is False


async def test_benign_error_stays_silent(superadmin):
    bot = AsyncMock()
    event = SimpleNamespace(
        exception=_bad_request("message is not modified"), update=_message_update()
    )

    assert await errors.on_error(event, bot) is True
    bot.send_message.assert_not_awaited()  # ни юзеру, ни оператору


# --- реальные ошибки ---


async def test_message_error_apologizes_and_alerts(superadmin):
    bot = AsyncMock()
    event = SimpleNamespace(exception=ValueError("бум"), update=_message_update())

    await errors.on_error(event, bot)

    targets = [call.args[0] for call in bot.send_message.await_args_list]
    assert targets == [555, 999]  # сначала юзеру, потом оператору
    alert = bot.send_message.await_args_list[1].args[1]
    assert "ValueError" in alert and "111" in alert


async def test_callback_error_stops_spinner(superadmin):
    bot = AsyncMock()
    update = _callback_update()
    event = SimpleNamespace(exception=RuntimeError("бум"), update=update)

    await errors.on_error(event, bot)

    update.callback_query.answer.assert_awaited()  # спиннер снят
    assert bot.send_message.await_args_list[0].args[0] == 555
    assert "plan:days:3" in bot.send_message.await_args_list[1].args[1]


async def test_second_same_error_is_throttled(superadmin):
    bot = AsyncMock()
    event = SimpleNamespace(exception=ValueError("бум"), update=_message_update())

    await errors.on_error(event, bot)
    await errors.on_error(event, bot)

    operator_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 999]
    user_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 555]
    assert len(operator_calls) == 1  # алерт подавлен дросселем
    assert len(user_calls) == 2  # но юзеру ответили оба раза


async def test_different_error_types_alert_separately(superadmin):
    bot = AsyncMock()
    update = _message_update()

    await errors.on_error(SimpleNamespace(exception=ValueError("a"), update=update), bot)
    await errors.on_error(SimpleNamespace(exception=KeyError("b"), update=update), bot)

    operator_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 999]
    assert len(operator_calls) == 2


async def test_failing_apology_does_not_block_alert(superadmin):
    """Юзер заблокировал бота — оператор все равно должен узнать об ошибке."""
    bot = AsyncMock()
    bot.send_message.side_effect = [RuntimeError("blocked"), None]
    event = SimpleNamespace(exception=ValueError("бум"), update=_message_update())

    assert await errors.on_error(event, bot) is True
    assert bot.send_message.await_args_list[1].args[0] == 999


async def test_no_superadmins_configured_is_safe(monkeypatch):
    monkeypatch.setattr(get_settings(), "superadmin_ids", [], raising=False)
    bot = AsyncMock()
    event = SimpleNamespace(exception=ValueError("бум"), update=_message_update())

    assert await errors.on_error(event, bot) is True
    assert [c.args[0] for c in bot.send_message.await_args_list] == [555]


async def test_missing_update_does_not_crash(superadmin):
    bot = AsyncMock()
    event = SimpleNamespace(exception=ValueError("бум"), update=None)

    assert await errors.on_error(event, bot) is True
    assert bot.send_message.await_args_list[0].args[0] == 999  # только алерт


def test_error_handler_registered_in_dispatcher(dispatcher):
    assert dispatcher.errors.handlers, "dp.errors должен быть зарегистрирован"
