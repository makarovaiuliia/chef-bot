"""Выбор FSM-хранилища: Redis в проде, память — локально и в тестах."""
from datetime import timedelta

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.main import create_dispatcher
from bot.storage import build_storage
from config import get_settings


def test_memory_storage_without_redis_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", None, raising=False)
    assert isinstance(build_storage(), MemoryStorage)


def test_empty_redis_url_falls_back_to_memory(monkeypatch):
    """Пустая переменная окружения — не «настроенный Redis», а ее отсутствие."""
    monkeypatch.setattr(get_settings(), "redis_url", "", raising=False)
    assert isinstance(build_storage(), MemoryStorage)


def test_redis_storage_when_url_set(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "redis_url", "redis://localhost:6379/0", raising=False
    )
    storage = build_storage()
    assert isinstance(storage, RedisStorage)


def test_redis_storage_gets_ttl(monkeypatch):
    """Заброшенный диалог должен истекать, а не лежать в Redis вечно."""
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(settings, "fsm_ttl_hours", 12, raising=False)

    storage = build_storage()

    assert storage.state_ttl == timedelta(hours=12)
    assert storage.data_ttl == timedelta(hours=12)


def test_dispatcher_without_storage_uses_memory(dispatcher):
    """create_dispatcher() без аргумента остается пригодным для тестов.

    Повторно вызвать create_dispatcher нельзя — роутеры модульные синглтоны,
    поэтому проверяем диспетчер из сессионной фикстуры.
    """
    assert isinstance(dispatcher.fsm.storage, MemoryStorage)


def test_create_dispatcher_takes_storage():
    import inspect

    assert "storage" in inspect.signature(create_dispatcher).parameters
