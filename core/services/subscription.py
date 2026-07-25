"""Статус подписки семьи и уведомления об истечении.

Раньше истекшая подписка молча возвращала семью к триальным лимитам: первым
сигналом было «Бесплатный лимит исчерпан» посреди работы. Теперь семья узнает
заранее, а оператор — что пора выставлять счет.
"""
from datetime import date

from core.constants import SUB_EXPIRY_WARN_DAYS
from core.db import Family
from core.services.limits import subscription_active


def days_until_expiry(family: Family, today: date) -> int | None:
    """Сколько дней подписка еще действует. 0 — истекает сегодня, None — нет подписки.

    sub_until включительно, поэтому в день sub_until подписка еще работает.
    """
    if family.sub_until is None:
        return None
    return (family.sub_until - today).days


def expiry_notice(family: Family, today: date) -> str | None:
    """Текст уведомления семье или None, если сегодня повода нет.

    Два повода: за SUB_EXPIRY_WARN_DAYS дней (успеть продлить без разрыва) и в
    последний день. Дальше молчим: про исчерпание лимитов юзер узнает из
    denial_text, второй раз пугать незачем.
    """
    days_left = days_until_expiry(family, today)
    if days_left == SUB_EXPIRY_WARN_DAYS:
        return (
            f"Подписка заканчивается через {SUB_EXPIRY_WARN_DAYS} дня — "
            f"{family.sub_until:%d.%m.%Y}. "
            "Напишите нам, если хотите продлить."
        )
    if days_left == 0:
        return (
            "Подписка заканчивается сегодня. С завтрашнего дня вернутся "
            "бесплатные лимиты — напишите нам, если хотите продлить."
        )
    return None


def operator_notice(family: Family, today: date) -> str | None:
    """Тот же повод, но текстом для оператора: с id семьи и датой."""
    days_left = days_until_expiry(family, today)
    if days_left not in (SUB_EXPIRY_WARN_DAYS, 0):
        return None
    name = family.name or "без имени"
    when = "сегодня" if days_left == 0 else f"через {days_left} дня"
    return (
        f"Подписка семьи {family.id} ({name}) заканчивается {when} — "
        f"{family.sub_until:%d.%m.%Y}."
    )


def status_line(family: Family, today: date) -> str:
    """Строка статуса подписки для /settings."""
    if family.sub_until is None:
        return "Подписка: нет, работают бесплатные лимиты"
    if subscription_active(family, today):
        return f"Подписка: активна до {family.sub_until:%d.%m.%Y}"
    return f"Подписка: истекла {family.sub_until:%d.%m.%Y}"
