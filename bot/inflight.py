"""Одна LLM-операция на семью одновременно.

Кнопки генерации остаются активными, пока бот работает: два тапа по
«Сгенерировать заново» давали две параллельные генерации, два списания лимита
и осиротевший черновик меню. У списка покупок гонка была закрыта unique-
констрейнтом на shopping_lists.menu_id, у остальных операций — ничем.

Состояние в памяти процесса: слот держится только на время работы хендлера, а
после рестарта никакая операция уже не выполняется — восстанавливать нечего.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.exceptions import FamilyBusy

BUSY_ALERT = "Уже работаю над предыдущим запросом — подождите пару секунд."

_busy: set[int] = set()


@asynccontextmanager
async def llm_slot(family_id: int) -> AsyncIterator[None]:
    """Занять единственный слот семьи или упасть с FamilyBusy.

    Проверка и захват идут одной синхронной парой операций до первого await,
    поэтому второй тап не может проскочить между ними в рамках одного процесса.
    """
    if family_id in _busy:
        raise FamilyBusy
    _busy.add(family_id)
    try:
        yield
    finally:
        _busy.discard(family_id)


def is_busy(family_id: int) -> bool:
    return family_id in _busy


def reset() -> None:
    """Только для тестов."""
    _busy.clear()
