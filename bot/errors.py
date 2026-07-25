"""Глобальный обработчик ошибок.

Без него необработанное исключение = молча проглоченный апдейт: юзер остается
перед «Готовлю меню...» навсегда, а оператор узнает о баге только если сам
заглянет в логи. Обработчик делает три вещи: пишет трейс, извиняется юзеру и
шлет алерт суперадминам с дросселем против шторма одинаковых ошибок.
"""
import time
import traceback

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ErrorEvent, Update
from loguru import logger

from config import get_settings

USER_MESSAGE = (
    "Что-то сломалось на нашей стороне. Попробуйте еще раз через минуту — "
    "если не поможет, напишите нам."
)

# Не баги: юзер удалил сообщение, текст не изменился, callback старше 48 часов.
# Логируем в INFO и не будим оператора.
_BENIGN_FRAGMENTS = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "message can't be edited",
    "query is too old",
)

# Один и тот же тип ошибки алертим не чаще раза в 5 минут: при системном сбое
# иначе получим шторм сообщений и упремся в лимиты Telegram. Дроссель в памяти
# процесса — после рестарта максимум один лишний алерт, это приемлемо.
ALERT_THROTTLE_SECONDS = 300
_last_alert: dict[str, float] = {}

_TRACEBACK_TAIL_CHARS = 1500


def is_benign(exc: BaseException) -> bool:
    """Ошибка на стороне Telegram, на которую мы не можем и не должны реагировать."""
    if isinstance(exc, TelegramForbiddenError):
        return True  # юзер заблокировал бота
    return isinstance(exc, TelegramBadRequest) and any(
        fragment in str(exc).lower() for fragment in _BENIGN_FRAGMENTS
    )


def should_alert(key: str, now: float) -> bool:
    """Дроссель алертов по ключу. Побочный эффект: отмечает время отправки."""
    last = _last_alert.get(key)
    if last is not None and now - last < ALERT_THROTTLE_SECONDS:
        return False
    _last_alert[key] = now
    return True


def reset_throttle() -> None:
    """Только для тестов: очистить память дросселя."""
    _last_alert.clear()


def describe_update(update: Update | None) -> str:
    """Короткое человекочитаемое описание апдейта для алерта."""
    if update is None:
        return "апдейт неизвестен"
    message = getattr(update, "message", None)
    if message is not None:
        user = getattr(message, "from_user", None)
        text = (getattr(message, "text", None) or "")[:80]
        return f"message от {getattr(user, 'id', '?')}: {text!r}"
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        user = getattr(callback, "from_user", None)
        return f"callback от {getattr(user, 'id', '?')}: {callback.data!r}"
    return f"апдейт {type(update).__name__}"


async def _apologize(update: Update | None, bot: Bot) -> None:
    """Сказать юзеру, что сломалось, и снять спиннер на кнопке."""
    if update is None:
        return
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        await callback.answer()
        if callback.message is not None:
            await bot.send_message(callback.message.chat.id, USER_MESSAGE)
        return
    message = getattr(update, "message", None)
    if message is not None:
        await bot.send_message(message.chat.id, USER_MESSAGE)


async def _alert_superadmins(update: Update | None, exc: BaseException, bot: Bot) -> None:
    superadmins = get_settings().superadmin_ids
    if not superadmins:
        return
    if not should_alert(type(exc).__name__, time.monotonic()):
        logger.info("error alert throttled: {}", type(exc).__name__)
        return
    tail = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )[-_TRACEBACK_TAIL_CHARS:]
    text = (
        f"⚠️ Необработанная ошибка: {type(exc).__name__}\n"
        f"{describe_update(update)}\n\n"
        f"<pre>{tail}</pre>"
    )
    for admin_id in superadmins:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.warning("errors: alert delivery failed id={}", admin_id)


async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    """Точка входа dp.errors. Никогда не выбрасывает исключение сама."""
    exc = event.exception
    update = getattr(event, "update", None)

    if is_benign(exc):
        logger.info("benign telegram error on {}: {}", describe_update(update), exc)
        return True

    logger.opt(exception=exc).error("unhandled error on {}", describe_update(update))
    try:
        await _apologize(update, bot)
    except Exception:
        # Отправка юзеру тоже падает, если он заблокировал бота — это не повод
        # ронять обработчик и терять алерт оператору.
        logger.warning("errors: apology delivery failed")
    try:
        await _alert_superadmins(update, exc, bot)
    except Exception:
        logger.exception("errors: alerting failed")
    return True
