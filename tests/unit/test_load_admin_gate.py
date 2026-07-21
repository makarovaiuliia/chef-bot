"""Regression: /load остается за router-level гейтом IsAdmin.

Стайл — как в test_button_handlers.py (структурная проверка filter-объектов),
но здесь смотрим не на per-handler фильтры хендлеров, а на router-level
фильтры (router.message.filter(...) / router.callback_query.filter(...)),
которые применяются ко всем хендлерам роутера через check_root_filters.
"""
from bot.filters import IsAdmin
from bot.handlers import load


def _root_filter_types(observer) -> list[type]:
    """Типы фильтров, зарегистрированных на уровне роутера через .filter(...)."""
    return [f.callback.__class__ for f in observer._handler.filters]


def test_load_message_router_requires_admin():
    assert IsAdmin in _root_filter_types(load.router.message)


def test_load_callback_query_router_requires_admin():
    assert IsAdmin in _root_filter_types(load.router.callback_query)
