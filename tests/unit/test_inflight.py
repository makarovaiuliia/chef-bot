"""Одна LLM-операция на семью: гард от двойного тапа по кнопке."""
import asyncio

import pytest

from bot import inflight
from bot.inflight import BUSY_ALERT, llm_slot
from core.exceptions import FamilyBusy


@pytest.fixture(autouse=True)
def _clean():
    inflight.reset()
    yield
    inflight.reset()


async def test_slot_is_free_after_use():
    async with llm_slot(1):
        assert inflight.is_busy(1)
    assert not inflight.is_busy(1)


async def test_second_acquire_raises():
    async with llm_slot(1):
        with pytest.raises(FamilyBusy):
            async with llm_slot(1):
                pass


async def test_other_families_are_independent():
    async with llm_slot(1):
        async with llm_slot(2):
            assert inflight.is_busy(1) and inflight.is_busy(2)


async def test_slot_released_after_exception():
    with pytest.raises(RuntimeError):
        async with llm_slot(1):
            raise RuntimeError("генерация упала")
    assert not inflight.is_busy(1)


async def test_failed_acquire_does_not_release_the_holder():
    """Проигравший тап не должен освобождать слот победителя своим finally."""
    async with llm_slot(1):
        with pytest.raises(FamilyBusy):
            async with llm_slot(1):
                pass
        assert inflight.is_busy(1)  # держатель на месте
    assert not inflight.is_busy(1)


async def test_concurrent_tasks_only_one_wins():
    started = []

    async def work():
        try:
            async with llm_slot(7):
                started.append("in")
                await asyncio.sleep(0.01)
            return "ok"
        except FamilyBusy:
            return "busy"

    results = await asyncio.gather(work(), work(), work())

    assert sorted(results) == ["busy", "busy", "ok"]
    assert started == ["in"]
    assert not inflight.is_busy(7)


def test_alert_text_is_user_facing():
    assert BUSY_ALERT and "ё" not in BUSY_ALERT
