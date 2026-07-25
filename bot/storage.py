"""Хранилище состояния диалогов (FSM).

Состояние — это «где юзер находится» в многошаговом флоу: ответы онбординга,
дата и id черновика в /plan, ожидание города в /settings. В памяти процесса
оно не переживает рестарт: человек на шестом вопросе онбординга начинает
заново, а админ с готовым черновиком меню теряет доступ к оплаченной
генерации — id черновика был только в этой памяти.

Redis решает это ценой отдельного сервиса. Без REDIS_URL остаемся на памяти:
так работают локальная разработка и тесты.
"""
from datetime import timedelta

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config import get_settings


def build_storage() -> BaseStorage:
    settings = get_settings()
    if not settings.redis_url:
        logger.warning(
            "FSM-хранилище в памяти процесса: незаконченные диалоги не переживут "
            "рестарт. Для прода задайте REDIS_URL."
        )
        return MemoryStorage()

    # Импорт внутри ветки: пакет redis нужен только когда он реально используется.
    from aiogram.fsm.storage.redis import RedisStorage

    # TTL, чтобы заброшенные диалоги не жили в Redis вечно. Тот же срок, что у
    # чистки осиротевших черновиков меню, — иначе состояние и данные разъедутся.
    ttl = timedelta(hours=settings.fsm_ttl_hours)
    logger.info("FSM-хранилище: Redis, TTL {} ч", settings.fsm_ttl_hours)
    return RedisStorage.from_url(settings.redis_url, state_ttl=ttl, data_ttl=ttl)
