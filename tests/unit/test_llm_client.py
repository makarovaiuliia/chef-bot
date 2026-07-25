"""Один LLM-клиент на процесс и границы по времени на каждый вызов."""
import anthropic

from config import get_settings
from core import llm as core_llm
from core.services import (
    conversation,
    dish_replacer,
    family_service,
    menu_planner,
    recipe_service,
    shopping_list,
)


def test_client_is_a_process_singleton():
    core_llm.get_llm_client.cache_clear()
    first = core_llm.get_llm_client()
    second = core_llm.get_llm_client()
    assert first is second


def test_all_services_share_one_factory():
    """Раньше фабрика дублировалась в каждом сервисе — по httpx-пулу на модуль."""
    modules = [
        conversation,
        dish_replacer,
        family_service,
        menu_planner,
        recipe_service,
        shopping_list,
    ]
    factories = {m.get_llm_client for m in modules}
    assert factories == {core_llm.get_llm_client}


def test_timeout_and_retries_reach_the_sdk():
    core_llm.get_llm_client.cache_clear()
    settings = get_settings()
    client = core_llm.get_llm_client()._client

    assert isinstance(client, anthropic.AsyncAnthropic)
    assert client.timeout == settings.llm_timeout_seconds
    assert client.max_retries == settings.llm_max_retries


def test_defaults_are_bounded():
    """Потолок по времени = timeout * (retries + 1); держим его в пределах минут."""
    settings = get_settings()
    worst_case = settings.llm_timeout_seconds * (settings.llm_max_retries + 1)
    assert worst_case <= 300, f"один вызов может занять {worst_case} с"
    # И заметно меньше дефолтов SDK (10 минут * 3 попытки).
    assert settings.llm_timeout_seconds < 600
