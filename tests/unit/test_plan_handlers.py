"""Хендлер-тесты /plan на AsyncMock (без aiogram-харнесса)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import plan as plan_handler
from core.exceptions import LLMInvalidResponse, MealNotFound


def _family(**kw):
    return SimpleNamespace(
        id=1, timezone="UTC", plan_slots=["lunch", "dinner"], profile_md="п",
        sub_until=None, **kw
    )


def _admin_member(**kw):
    return SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin", **kw)


async def test_generation_failure_shows_retry(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad json twice")

    monkeypatch.setattr(plan_handler.menu_planner, "generate_menu", boom)
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"start_date": "2026-07-27", "days": 5}
    member = SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")

    await plan_handler._generate_and_show(message, state, _family(), member, db_session=None)

    placeholder = message.answer.return_value
    placeholder.edit_text.assert_awaited_once()
    assert "Не получилось" in placeholder.edit_text.await_args.args[0]


async def test_generation_trial_denial_shows_polite_text(monkeypatch):
    from core.exceptions import TrialLimitExceeded

    async def blocked(*a, **kw):
        raise TrialLimitExceeded("menu_gen")

    monkeypatch.setattr(plan_handler.menu_planner, "generate_menu", blocked)
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"start_date": "2026-07-27", "days": 5}
    member = SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")

    await plan_handler._generate_and_show(message, state, _family(), member, db_session=None)

    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "лимит" in text.lower() and "подписка" in text.lower()
    assert placeholder.edit_text.await_args.kwargs.get("reply_markup") is not None
    state.clear.assert_awaited_once()


async def test_suggest_trial_denial_shows_polite_text_with_button(monkeypatch):
    from core.exceptions import TrialLimitExceeded

    async def blocked(*a, **kw):
        raise TrialLimitExceeded("replace")

    monkeypatch.setattr(plan_handler, "suggest_replacements", blocked)
    monkeypatch.setattr(
        plan_handler.repositories,
        "get_meal_for_family",
        AsyncMock(return_value=SimpleNamespace(dish_name="Рыба")),
    )
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"replace_meal_id": 1}

    await plan_handler._suggest_and_show(message, state, _family(), db_session=None, hint=None)

    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "лимит" in text.lower() and "подписка" in text.lower()
    assert placeholder.edit_text.await_args.kwargs.get("reply_markup") is not None
    state.clear.assert_awaited_once()


async def test_custom_date_rejects_garbage():
    message, state = AsyncMock(), AsyncMock()
    message.text = "вчера"
    await plan_handler.on_custom_date(message, state, _family())
    assert "Не понял дату" in message.answer.await_args.args[0]
    state.update_data.assert_not_awaited()


async def test_pick_alternative_out_of_range_alerts():
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:5"
    state.get_data.return_value = {"alternatives": [], "replace_meal_id": 1}
    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_pick_alternative_vanished_meal_alerts(monkeypatch):
    async def boom(*a, **kw):
        raise MealNotFound("meal gone")

    monkeypatch.setattr(plan_handler, "apply_replacement", boom)
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:0"
    state.get_data.return_value = {
        "alternatives": [{"dish_name": "Рыба", "side_dishes": [], "protein_kind": "fish"}],
        "replace_meal_id": 1,
    }

    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)

    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    cb.message.edit_text.assert_not_awaited()


async def test_pick_alternative_value_error_alerts(monkeypatch):
    async def boom(*a, **kw):
        raise ValueError("Meal 5 not found")

    monkeypatch.setattr(plan_handler, "apply_replacement", boom)
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:0"
    state.get_data.return_value = {
        "replace_meal_id": 5,
        "alternatives": [{"dish_name": "Х", "side_dishes": [], "protein_kind": "chicken"}],
    }

    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)

    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_pick_alternative_negative_index_alerts(monkeypatch):
    apply_mock = AsyncMock()
    monkeypatch.setattr(plan_handler, "apply_replacement", apply_mock)
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:-1"
    state.get_data.return_value = {
        "alternatives": [{"dish_name": "Рыба", "side_dishes": [], "protein_kind": "fish"}],
        "replace_meal_id": 1,
    }

    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)

    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    apply_mock.assert_not_awaited()


async def test_suggest_llm_error_returns_to_pick(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad json")

    monkeypatch.setattr(plan_handler, "suggest_replacements", boom)
    monkeypatch.setattr(
        plan_handler.repositories,
        "get_meal_for_family",
        AsyncMock(return_value=SimpleNamespace()),
    )
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"replace_meal_id": 1}

    await plan_handler._suggest_and_show(message, state, _family(), db_session=None, hint=None)

    placeholder = message.answer.return_value
    placeholder.edit_text.assert_awaited_once()
    assert "Не получилось" in placeholder.edit_text.await_args.args[0]
    state.set_state.assert_awaited_with(plan_handler.PlanFlow.replace_pick)


async def test_on_approve_with_conflicts_asks_confirmation(monkeypatch):
    menu = SimpleNamespace(id=7, family_id=1, days_count=3,
                           start_date=date(2026, 7, 27), meals=[])

    async def fake_draft(*a, **kw):
        return menu

    async def fake_preview(*a, **kw):
        return {date(2026, 7, 27)}

    monkeypatch.setattr(plan_handler, "_draft_menu", fake_draft)
    monkeypatch.setattr(plan_handler.menu_planner, "preview_approve", fake_preview)
    cb, state = AsyncMock(), AsyncMock()

    await plan_handler.on_approve(cb, state, _family(), _admin_member(), db_session=None)

    text = cb.message.edit_text.await_args.args[0]
    assert "Перезаписать" in text
    state.set_state.assert_awaited_once_with(plan_handler.PlanFlow.approve_confirm)


async def test_do_approve_offers_shoplist_instead_of_building(monkeypatch):
    built = False

    async def fake_build(*a, **kw):
        nonlocal built
        built = True

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", fake_build)
    commit = AsyncMock()
    monkeypatch.setattr(plan_handler.menu_planner, "commit_approve", commit)
    notify = AsyncMock()
    monkeypatch.setattr(plan_handler, "_notify_admins", notify)

    message, state = AsyncMock(), AsyncMock()
    menu = SimpleNamespace(id=7, days_count=5, start_date=date(2026, 7, 27), meals=[])
    member = SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")

    await plan_handler._do_approve(
        message, state, _family(), member, None, menu, date(2026, 7, 27)
    )

    assert built is False  # сборка не запускается автоматически
    offer_text = message.answer.await_args.args[0]
    assert "список покупок" in offer_text.lower()
    assert message.answer.await_args.kwargs["reply_markup"] is not None


async def test_build_shopping_success_reports_count(monkeypatch):
    async def fake_build(*a, **kw):
        return [object(), object(), object()]

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", fake_build)
    message = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=3, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=None, menu=menu)

    placeholder = message.answer.return_value
    assert "3" in placeholder.edit_text.await_args.args[0]


async def test_build_shopping_monthly_cap_denial_no_approved_prefix(monkeypatch):
    from core.exceptions import MonthlyCapExceeded

    async def blocked(*a, **kw):
        raise MonthlyCapExceeded

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", blocked)
    message = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=3, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=None, menu=menu)

    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "Меню утверждено" not in text
    assert "лимит" in text.lower()
    assert placeholder.edit_text.await_args.kwargs.get("reply_markup") is not None


async def test_build_shoplist_rejects_draft_menu(monkeypatch):
    from core.db import MenuStatus

    menu = SimpleNamespace(id=7, family_id=1, status=MenuStatus.draft, meals=[])

    async def fake_get(*a, **kw):
        return menu

    monkeypatch.setattr(plan_handler.repositories, "get_menu_with_meals", fake_get)
    cb = AsyncMock()
    cb.data = "plan:shoplist:7"

    await plan_handler.on_build_shoplist(cb, _family(), db_session=None)

    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_build_shoplist_already_built_alerts_without_rebuilding(monkeypatch):
    from core.db import MenuStatus

    menu = SimpleNamespace(id=7, family_id=1, status=MenuStatus.active, meals=[])

    async def fake_get(*a, **kw):
        return menu

    monkeypatch.setattr(plan_handler.repositories, "get_menu_with_meals", fake_get)

    async def fake_has_list(*a, **kw):
        return True

    monkeypatch.setattr(plan_handler.shopping_list, "has_list_for_menu", fake_has_list)
    build = AsyncMock()
    monkeypatch.setattr(plan_handler, "_build_shopping", build)
    cb = AsyncMock()
    cb.data = "plan:shoplist:7"

    await plan_handler.on_build_shoplist(cb, _family(), db_session=None)

    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
    build.assert_not_awaited()


async def test_build_shoplist_foreign_menu_alerts(monkeypatch):
    from core.db import MenuStatus

    foreign = SimpleNamespace(id=7, family_id=999, status=MenuStatus.active, meals=[])

    async def fake_get(*a, **kw):
        return foreign

    monkeypatch.setattr(plan_handler.repositories, "get_menu_with_meals", fake_get)
    cb = AsyncMock()
    cb.data = "plan:shoplist:7"

    await plan_handler.on_build_shoplist(cb, _family(), db_session=None)

    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_shopping_failure_keeps_menu_approved_and_offers_retry(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad")

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", boom)
    message = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=5, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=None, menu=menu)

    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "утверждено" in text and "список покупок" in text
    assert placeholder.edit_text.await_args.kwargs["reply_markup"] is not None


async def test_custom_date_ignores_commands():
    """Хендлер on_custom_date не должен матчить команды — проверяем фильтр."""
    from tests.unit.test_button_handlers import _registered_filters

    filters_by_handler = dict(_registered_filters(plan_handler.router))
    on_custom = filters_by_handler["on_custom_date"]
    assert any("startswith" in f and "/" in f for f in on_custom)
    on_hint = filters_by_handler["on_replace_hint"]
    assert any("startswith" in f and "/" in f for f in on_hint)


async def test_cmd_plan_deletes_orphan_draft(monkeypatch):
    deleted = {}

    async def fake_delete(session, *, menu_id):
        deleted["menu_id"] = menu_id

    monkeypatch.setattr(plan_handler.menu_planner, "delete_draft", fake_delete)
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"menu_id": 42}

    await plan_handler.cmd_plan(message, state, _family(), db_session=None)

    assert deleted["menu_id"] == 42
    state.clear.assert_awaited_once()


async def test_plan_reminder_callback_starts_flow():
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:remind"
    state.get_data.return_value = {}
    await plan_handler.on_plan_reminder(cb, state, db_session=None)
    state.clear.assert_awaited_once()
    state.set_state.assert_awaited_once_with(plan_handler.PlanFlow.start_date)
    assert "С какого дня" in cb.message.answer.await_args.args[0]


async def test_plan_reminder_deletes_orphan_draft(monkeypatch):
    deleted = {}

    async def fake_delete(session, *, menu_id):
        deleted["menu_id"] = menu_id

    monkeypatch.setattr(plan_handler.menu_planner, "delete_draft", fake_delete)
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:remind"
    state.get_data.return_value = {"menu_id": 42}

    await plan_handler.on_plan_reminder(cb, state, db_session=None)

    assert deleted["menu_id"] == 42
    state.clear.assert_awaited_once()


async def test_shoptext_renders_from_db_when_list_exists(monkeypatch):
    from core.db import MenuStatus

    menu = SimpleNamespace(id=7, family_id=1, status=MenuStatus.active, meals=[])

    async def fake_get(*a, **kw):
        return menu

    async def fake_has(*a, **kw):
        return True

    async def fake_items(*a, **kw):
        return [SimpleNamespace(name="Рис", quantity="500 г")]

    generated = False

    async def fake_generate(*a, **kw):
        nonlocal generated
        generated = True
        return []

    monkeypatch.setattr(plan_handler.repositories, "get_menu_with_meals", fake_get)
    monkeypatch.setattr(plan_handler.shopping_list, "has_list_for_menu", fake_has)
    monkeypatch.setattr(plan_handler.repositories, "items_for_menu", fake_items)
    monkeypatch.setattr(plan_handler.shopping_list, "generate_items", fake_generate)
    cb = AsyncMock()
    cb.data = "plan:shoptext:7"

    await plan_handler.on_shoplist_text(cb, _family(), db_session=None)

    assert generated is False  # без LLM — рендер из БД
    text = cb.message.answer.await_args.args[0]
    assert "Рис" in text


async def test_build_shopping_race_integrity_error_shows_polite_message(monkeypatch):
    """Доп. требование ревью Task 2: двойной тап -> проигравший ловит IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    async def boom(*a, **kw):
        raise IntegrityError("insert", {}, Exception("unique violation"))

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", boom)
    message = AsyncMock()
    db_session = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=3, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=db_session, menu=menu)

    # регресс ревью: после пойманного IntegrityError сессия в must-rollback
    # состоянии — без явного rollback() commit из session_scope() поднимет
    # PendingRollbackError необработанным.
    db_session.rollback.assert_awaited_once()
    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "список" in text.lower() and "/list" in text


async def test_build_shoplist_happy_path_builds(monkeypatch):
    """Бэклог этапа 3: happy-path — активное свое меню без списка запускает сборку."""
    from core.db import MenuStatus

    menu = SimpleNamespace(id=7, family_id=1, status=MenuStatus.active, meals=[])

    async def fake_get(*a, **kw):
        return menu

    async def fake_has(*a, **kw):
        return False

    built = {}

    async def fake_build(message, family, db_session, m):
        built["menu_id"] = m.id

    monkeypatch.setattr(plan_handler.repositories, "get_menu_with_meals", fake_get)
    monkeypatch.setattr(plan_handler.shopping_list, "has_list_for_menu", fake_has)
    monkeypatch.setattr(plan_handler, "_build_shopping", fake_build)
    cb = AsyncMock()
    cb.data = "plan:shoplist:7"

    await plan_handler.on_build_shoplist(cb, _family(), db_session=None)

    assert built["menu_id"] == 7
