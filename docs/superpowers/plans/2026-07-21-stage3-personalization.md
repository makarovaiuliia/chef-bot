# Stage 3: Персонализация и лимиты — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Лимиты триала и месячный токен-потолок работают; дайджест ходит по таймзоне каждой семьи с настройкой в /settings; за 2 дня до конца меню админы получают напоминание с кнопкой «Спланировать»; список покупок предлагается кнопкой после утверждения; закрыт UX/тестовый бэклог этапа 2.

**Architecture:** Единая точка проверки лимитов `core/services/limits.py::ensure_within_limits` вызывается сервисами ПЕРЕД каждым LLM-вызовом (триал — по count_llm_operations, потолок — по сумме токенов за календарный месяц UTC); хендлеры ловят типизированные исключения и шлют вежливые отказы. Планировщик переписывается с одного глобального 9:00-цикла на тик каждые 15 минут с чистой функцией `families_due` (локальный час семьи == digest_hour, дедупликация по in-memory last_sent). Автосборка списка покупок из этапа 2 заменяется предложением-кнопкой (решение пользователя 2026-07-21: сборка — часть планирования, только по утвержденному меню).

**Tech Stack:** Python 3.12, aiogram 3, anthropic SDK, SQLAlchemy 2.0 async, Alembic, pytest + pytest-asyncio.

**Reference spec:** [2026-07-20-multi-family-product-design.md](../specs/2026-07-20-multi-family-product-design.md) (§3 обновлен 2026-07-21, §5, §6, §10 этап 3) + секция «Отложено финальным ревью» в [плане этапа 2](2026-07-20-stage2-planning.md).

## Global Constraints

- Python `>=3.12`, ruff `line-length = 100`, select `["E","F","I","W","UP","B","ASYNC"]`.
- Все видимые юзеру тексты — на русском; эмодзи только из `core/emoji.py`.
- **Буква «ё» запрещена** во всех `.py`/`.md` в `bot/` и `core/` (гард `tests/unit/test_no_yo.py`) — всегда «е».
- pytest `asyncio_mode = "auto"`; фикстура `db_session` (in-memory SQLite); после каждого таска `ruff check . && pytest -q` зелёные; conventional commits.
- **Триал — разовый (пожизненный) лимит на семью** (спека §6): **4 генерации меню, 15 замен, 15 рецептов** — по суммарному числу операций в `llm_usage` за все время, без сброса. Генерация профиля в онбординге — вне лимитов. Сборка списка покупок (`shopping`) — вне триал-счетчиков, но под месячным потолком (решение 2026-07-21).
- **Месячный потолок** (спека §6): `MONTHLY_TOKEN_CAP_PER_FAMILY = 500_000` токенов (tokens_in+tokens_out) за календарный месяц (UTC); проверка перед каждой LLM-операцией; отказ — с датой сброса (1-е число). Константы — в конфиге (env-переопределяемые).
- Проверка лимитов — ДО вызова LLM (неуспешные попытки и так не логируются — этап 2).
- Список покупок: после утверждения меню бот ПРЕДЛАГАЕТ собрать список кнопкой (не авто); сборка доступна только по активному (утвержденному) меню своей семьи.
- Напоминание «пора планировать»: за 2 дня до конца активного меню, только админам, только при `planning_enabled=true`; кнопка запускает флоу /plan.
- Дайджест per-family: `families.timezone`, `families.digest_hour`, `digest_enabled` (все колонки уже есть с миграции 0005); /settings — только админам (просмотр — всем членам семьи).
- Reply-клавиатура `kb_main()` не трогается; в plan.py callback-хендлеры регистрируются ДО catch-all `plan:*` (он должен остаться последним в модуле).
- Схема: единственная миграция этапа — 0006 (drop `family_members.can_plan`).

---

## File Structure (итог этапа)

```
config.py                        + trial_menu_gen_limit=4, trial_replace_limit=15,
                                   trial_recipe_limit=15, monthly_token_cap_per_family=500_000
core/exceptions.py               + LimitExceeded, TrialLimitExceeded, MonthlyCapExceeded
core/repositories.py             + sum_llm_tokens_current_month
core/services/limits.py          NEW: ensure_within_limits, denial_text
core/services/menu_planner.py    ensure перед LLM; русские дни вместо %a; parse_start_date 29.02
core/services/dish_replacer.py   ensure перед LLM
core/services/recipe_service.py  ensure перед LLM (после кэш-мисса)
core/services/shopping_list.py   ensure перед LLM (триала нет — только потолок)
core/services/reminders.py       + plan_reminder_due
core/services/digest.py          текст «пора загрузить» → «пора спланировать»
core/services/family_service.py  + update_digest_settings
core/db.py                       FamilyMember без can_plan; get_engine: пул для PG
bot/scheduler.py                 переписан: тик 15 мин, families_due, per-family дайджест
                                 + напоминание «пора планировать»
bot/handlers/plan.py             отказы лимитов; предложение списка кнопкой; plan:remind;
                                 cleanup сиротского draft в cmd_plan; ~startswith("/")
bot/handlers/menu.py             отказ лимита в cb_recipe
bot/handlers/profile.py          ~startswith("/") в on_new_text
bot/handlers/settings.py         NEW: /settings (дайджест вкл/выкл, час)
bot/keyboards.py                 + kb_shoplist_offer, kb_settings, kb_plan_reminder
bot/main.py                      + settings router; /settings в bot_commands
bot/handlers/start.py            help_text + /settings
alembic/versions/0006_drop_can_plan.py NEW
tests/...                        unit + integration на все выше + тестовый долг этапа 2
```

---

### Task 1: Лимиты — сервисный слой

**Files:**
- Modify: `config.py`, `core/exceptions.py`, `core/repositories.py`
- Create: `core/services/limits.py`
- Test: `tests/integration/test_limits.py` (новый)

**Interfaces:**
- Produces (используется Task 2):
  - `Settings.trial_menu_gen_limit: int = 4`, `trial_replace_limit: int = 15`, `trial_recipe_limit: int = 15`, `monthly_token_cap_per_family: int = 500_000` (env-переопределяемые).
  - `core.exceptions.LimitExceeded(ChefBotError)`; `TrialLimitExceeded(LimitExceeded)` с атрибутом `.operation: str`; `MonthlyCapExceeded(LimitExceeded)`.
  - `repositories.sum_llm_tokens_current_month(session, *, family_id: int, now: datetime) -> int` — SUM(tokens_in+tokens_out) с 1-го числа месяца `now` (UTC).
  - `limits.ensure_within_limits(session, *, family_id: int, operation: str, now: datetime | None = None) -> None` — сначала триал по операции (если она в лимитах), затем потолок; raises.
  - `limits.denial_text(exc: Exception) -> str` — вежливый русский текст отказа (для триала — по операции; для потолка — с «1-го числа»).

- [ ] **Step 1: Падающие тесты**

Создать `tests/integration/test_limits.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from config import get_settings
from core.db import Family, LlmUsage
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded
from core.repositories import log_llm_usage, sum_llm_tokens_current_month
from core.services import limits

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


async def _family(db_session) -> Family:
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_sum_tokens_counts_only_current_month(db_session):
    fam = await _family(db_session)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=100, tokens_out=50
    )
    # запись прошлого месяца — с явной датой
    old = LlmUsage(
        family_id=fam.id, operation="menu_gen", tokens_in=999, tokens_out=999,
        created_at=NOW - timedelta(days=40),
    )
    db_session.add(old)
    await db_session.flush()
    total = await sum_llm_tokens_current_month(db_session, family_id=fam.id, now=NOW)
    assert total == 150


async def test_trial_limit_blocks_after_n_operations(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 2)
    for _ in range(2):
        await log_llm_usage(
            db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
        )
    with pytest.raises(TrialLimitExceeded) as exc_info:
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="menu_gen", now=NOW
        )
    assert exc_info.value.operation == "menu_gen"


async def test_trial_limits_are_per_operation(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
    )
    # replace не исчерпан — проходит
    await limits.ensure_within_limits(db_session, family_id=fam.id, operation="replace", now=NOW)


async def test_shopping_has_no_trial_limit_but_hits_cap(db_session, monkeypatch):
    fam = await _family(db_session)
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 100)
    await log_llm_usage(
        db_session, family_id=fam.id, operation="shopping", tokens_in=60, tokens_out=60
    )
    # триал для shopping не проверяется, но потолок — да
    with pytest.raises(MonthlyCapExceeded):
        await limits.ensure_within_limits(
            db_session, family_id=fam.id, operation="shopping", now=NOW
        )


async def test_under_all_limits_passes(db_session):
    fam = await _family(db_session)
    await limits.ensure_within_limits(db_session, family_id=fam.id, operation="menu_gen", now=NOW)


def test_denial_texts():
    assert "лимит" in limits.denial_text(TrialLimitExceeded("menu_gen")).lower()
    assert "1-го числа" in limits.denial_text(MonthlyCapExceeded())
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/pytest tests/integration/test_limits.py -q`
Expected: FAIL — `ImportError` (нет limits, исключений, sum_llm_tokens_current_month).

- [ ] **Step 3: Реализация**

`config.py` — в `Settings` добавить:

```python
    # спека §6: разовый (пожизненный) триал на семью + месячный anti-abuse потолок
    trial_menu_gen_limit: int = 4
    trial_replace_limit: int = 15
    trial_recipe_limit: int = 15
    monthly_token_cap_per_family: int = 500_000
```

`core/exceptions.py` — добавить:

```python
class LimitExceeded(ChefBotError):
    """База: лимит триала или месячный токен-потолок исчерпан."""


class TrialLimitExceeded(LimitExceeded):
    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(operation)


class MonthlyCapExceeded(LimitExceeded):
    pass
```

`core/repositories.py` — добавить (import `datetime` уже есть, `func` есть):

```python
async def sum_llm_tokens_current_month(
    session: AsyncSession, *, family_id: int, now: datetime
) -> int:
    """Сумма токенов семьи с 1-го числа календарного месяца `now` (UTC)."""
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    stmt = (
        select(func.coalesce(func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out), 0))
        .where(LlmUsage.family_id == family_id, LlmUsage.created_at >= month_start)
    )
    return int((await session.execute(stmt)).scalar_one())
```

Создать `core/services/limits.py`:

```python
"""Триал-лимиты и месячный токен-потолок (спека §6).

Вызывается сервисами ПЕРЕД каждым LLM-вызовом. Триал — разовый (пожизненный)
лимит по числу операций; потолок — сумма токенов за календарный месяц (UTC).
Генерация профиля в онбординге сюда не ходит (вне лимитов, семьи еще нет).
Операция "shopping" не имеет триал-лимита (часть планирования), но токены
считаются в потолке.
"""
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded


def _trial_limits() -> dict[str, int]:
    s = get_settings()
    return {
        "menu_gen": s.trial_menu_gen_limit,
        "replace": s.trial_replace_limit,
        "recipe": s.trial_recipe_limit,
    }


async def ensure_within_limits(
    session: AsyncSession, *, family_id: int, operation: str, now: datetime | None = None
) -> None:
    limit = _trial_limits().get(operation)
    if limit is not None:
        used = await repositories.count_llm_operations(
            session, family_id=family_id, operation=operation
        )
        if used >= limit:
            raise TrialLimitExceeded(operation)
    now = now or datetime.now(UTC)
    tokens = await repositories.sum_llm_tokens_current_month(
        session, family_id=family_id, now=now
    )
    if tokens >= get_settings().monthly_token_cap_per_family:
        raise MonthlyCapExceeded


_OPERATION_LABELS = {
    "menu_gen": "генераций меню",
    "replace": "замен блюд",
    "recipe": "рецептов",
}


def denial_text(exc: Exception) -> str:
    """Вежливый отказ (спека §6): подписка скоро / потолок с датой сброса."""
    if isinstance(exc, TrialLimitExceeded):
        label = _OPERATION_LABELS.get(exc.operation, "операций")
        return (
            f"Бесплатный лимит {label} исчерпан. Скоро появится подписка — "
            "мы напишем, как только ее можно будет оформить."
        )
    return (
        "Месячный лимит ИИ-операций семьи исчерпан — обновится 1-го числа "
        "следующего месяца. Подписка с расширенными лимитами уже готовится."
    )
```

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add config.py core/exceptions.py core/repositories.py core/services/limits.py tests/integration/test_limits.py
git commit -m "feat(limits): trial counters and monthly token cap service"
```

---

### Task 2: Лимиты — встраивание в сервисы и хендлеры

**Files:**
- Modify: `core/services/menu_planner.py`, `core/services/dish_replacer.py`, `core/services/recipe_service.py`, `core/services/shopping_list.py`
- Modify: `bot/handlers/plan.py` (`_generate_and_show`, `_suggest_and_show`, `_build_shopping`), `bot/handlers/menu.py` (`cb_recipe`)
- Test: `tests/integration/test_limits_enforcement.py` (новый), `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Consumes: `limits.ensure_within_limits`, `limits.denial_text`, `LimitExceeded` (Task 1).
- Produces: каждый LLM-сервис бросает `TrialLimitExceeded`/`MonthlyCapExceeded` ДО вызова LLM; хендлеры показывают `denial_text` вместо технической ошибки.

- [ ] **Step 1: Падающие integration-тесты**

Создать `tests/integration/test_limits_enforcement.py`:

```python
"""Сервисы проверяют лимиты ДО вызова LLM (LLM не дергается при отказе)."""
from datetime import date

import pytest

from config import get_settings
from core.db import Family
from core.exceptions import MonthlyCapExceeded, TrialLimitExceeded
from core.repositories import log_llm_usage
from core.services import menu_planner


class ExplodingLLM:
    """LLM, который не должен быть вызван."""

    async def chat(self, **kwargs):
        raise AssertionError("LLM вызван несмотря на исчерпанный лимит")


async def test_generate_menu_blocked_by_trial(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)
    fam = Family(name="f", profile_md="п", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    await log_llm_usage(
        db_session, family_id=fam.id, operation="menu_gen", tokens_in=1, tokens_out=1
    )
    with pytest.raises(TrialLimitExceeded):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=date(2026, 7, 27),
            days_count=3, llm=ExplodingLLM(),
        )


async def test_generate_menu_blocked_by_cap(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 10)
    fam = Family(name="f", profile_md="п", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    await log_llm_usage(
        db_session, family_id=fam.id, operation="recipe", tokens_in=6, tokens_out=6
    )
    with pytest.raises(MonthlyCapExceeded):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=date(2026, 7, 27),
            days_count=3, llm=ExplodingLLM(),
        )
```

Аналогичные по одному тесту «blocked_by_trial» добавить в существующие
`tests/integration/test_dish_replacer.py` (операция `replace`, через
`suggest_replacements`, мок-LLM файла не должен быть вызван — проверить его
счетчик вызовов) и `tests/integration/test_recipe_service.py` (операция
`recipe`; ВАЖНО: кэш-хит должен отдавать рецепт ДАЖЕ при исчерпанном лимите —
отдельный ассерт: сначала сгенерировать рецепт, исчерпать лимит, повторный
`get_recipe` возвращает кэш без исключения). В
`tests/integration/test_shopping_list.py` — тест «shopping блокируется потолком»
(monkeypatch cap=10 + залогировать 20 токенов → `MonthlyCapExceeded`, LLM не
вызван, старый список не тронут).

Run: `.venv/bin/pytest tests/integration/test_limits_enforcement.py -q` → FAIL (исключение не бросается, ExplodingLLM взрывается).

- [ ] **Step 2: Встраивание в сервисы**

В каждом сервисе — импорт `from core.services import limits` и вызов ДО `llm.chat`:

`core/services/menu_planner.py::generate_menu` — после проверки `days_count`, до сборки messages:

```python
    await limits.ensure_within_limits(session, family_id=family.id, operation="menu_gen")
```

`core/services/dish_replacer.py::suggest_replacements` — после проверки meal, до user_msg:

```python
    await limits.ensure_within_limits(session, family_id=family_id, operation="replace")
```

`core/services/recipe_service.py::get_recipe` — ПОСЛЕ возврата кэша (кэш-хит бесплатный), после проверки meal, до user_msg:

```python
    await limits.ensure_within_limits(session, family_id=family_id, operation="recipe")
```

`core/services/shopping_list.py::build_from_menu` — первой строкой (операция без триала — проверится только потолок):

```python
    await limits.ensure_within_limits(session, family_id=family_id, operation="shopping")
```

- [ ] **Step 3: Отказы в хендлерах**

`bot/handlers/plan.py` — импорт `from core.exceptions import LimitExceeded, ...` (дополнить существующий) и `from core.services.limits import denial_text`.

В `_generate_and_show` — ветка ПЕРЕД `except LLMError`:

```python
    except LimitExceeded as e:
        await state.clear()
        await placeholder.edit_text(denial_text(e))
        return
```

В `_suggest_and_show` — аналогично перед `except LLMError`:

```python
    except LimitExceeded as e:
        await state.clear()
        await placeholder.edit_text(denial_text(e))
        return
```

В `_build_shopping` — перед `except LLMError` (меню уже утверждено — сообщаем это):

```python
    except LimitExceeded as e:
        await placeholder.edit_text(f"Меню утверждено. {denial_text(e)}")
        return
```

`bot/handlers/menu.py::cb_recipe` — перед `except LLMError`:

```python
    except LimitExceeded as e:
        await placeholder.edit_text(denial_text(e))
        return
```

(импорты `LimitExceeded`, `denial_text` добавить.)

- [ ] **Step 4: Хендлер-тест**

В `tests/unit/test_plan_handlers.py` добавить:

```python
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
    state.clear.assert_awaited_once()
```

- [ ] **Step 5: Полный прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/services/ bot/handlers/ tests/
git commit -m "feat(limits): enforce trial and monthly cap before every LLM operation"
```

---

### Task 3: Список покупок — по кнопке после утверждения

**Files:**
- Modify: `bot/handlers/plan.py` (`_do_approve`, `on_shoplist_retry`), `bot/keyboards.py`
- Test: `tests/unit/test_plan_keyboards.py`, `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Consumes: существующие `_build_shopping`, `get_menu_with_meals`, `MenuStatus`.
- Produces: после утверждения — сообщение-предложение с `kb_shoplist_offer(menu_id)` (callback `plan:shoplist:<menu_id>` — существующий namespace); `on_shoplist_retry` переименован в `on_build_shoplist` и дополнительно требует `menu.status == MenuStatus.active`. Автосборка удалена.

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_plan_keyboards.py`:

```python
from bot.keyboards import kb_shoplist_offer


def test_shoplist_offer_button():
    assert _datas(kb_shoplist_offer(7)) == ["plan:shoplist:7"]
```

В `tests/unit/test_plan_handlers.py`:

```python
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
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`bot/keyboards.py`:

```python
def kb_shoplist_offer(menu_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.SHOPPING} Составить список покупок", callback_data=f"plan:shoplist:{menu_id}")
    return b.as_markup()
```

`bot/handlers/plan.py::_do_approve` — заменить хвост `await _build_shopping(message, family, db_session, menu)` на:

```python
    await message.answer(
        f"{emoji.SHOPPING} Составить список покупок по меню?",
        reply_markup=kb_shoplist_offer(menu.id),
    )
```

(импорт `kb_shoplist_offer` добавить; `_build_shopping` остается — его зовет кнопка.)

`on_shoplist_retry` → переименовать в `on_build_shoplist`, docstring «Сборка списка по кнопке после утверждения (и ретрай при ошибке). Только активное меню своей семьи.», добавить к проверке статус:

```python
    if menu is None or menu.family_id != family.id or menu.status != MenuStatus.active:
        await cb.answer("Меню не найдено или не утверждено", show_alert=True)
        return
```

(импорт `MenuStatus` из `core.db` дополнить.)

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS (упавшие старые тесты `_do_approve`/`shoplist` — обновить под новое поведение: предложение вместо автосборки).

```bash
git add bot/handlers/plan.py bot/keyboards.py tests/
git commit -m "feat(plan): offer shopping list as a button after approve instead of auto-build"
```

---

### Task 4: Планировщик per-family (таймзона, digest_hour, digest_enabled)

**Files:**
- Rewrite: `bot/scheduler.py`
- Test: `tests/unit/test_scheduler.py` (переписать)

**Interfaces:**
- Consumes: `Family.timezone/digest_hour/digest_enabled` (миграция 0005), `digest.build_morning_digest`, `get_family_members`.
- Produces (используется Task 5): `families_due(families, *, now: datetime, last_sent: dict[int, date]) -> list[Family]` (чистая, тестируемая); цикл `_scheduler_loop` тикает каждые `TICK_SECONDS = 900`; после отправки помечает `last_sent[family.id] = local_today`. Семья due, когда ее локальный час == `digest_hour` и сегодня еще не слали. `digest_enabled=False` НЕ исключает семью из due (напоминание Task 5 шлется и без дайджеста) — фильтр дайджеста внутри отправки. `start_scheduler(bot, sessionmaker) -> list[asyncio.Task]` — сигнатура сохраняется (вызов в `bot/main.py` не меняется).

- [ ] **Step 1: Падающие unit-тесты**

Переписать `tests/unit/test_scheduler.py`:

```python
from datetime import UTC, date, datetime
from types import SimpleNamespace

from bot.scheduler import families_due

# 2026-07-21 02:07 UTC == 09:07 в Бангкоке (UTC+7)
NOW = datetime(2026, 7, 21, 2, 7, tzinfo=UTC)


def _family(fid, tz="Asia/Bangkok", hour=9, enabled=True):
    return SimpleNamespace(id=fid, timezone=tz, digest_hour=hour, digest_enabled=enabled)


def test_due_when_local_hour_matches():
    fams = [_family(1)]
    assert families_due(fams, now=NOW, last_sent={}) == fams


def test_not_due_wrong_hour():
    assert families_due([_family(1, hour=8)], now=NOW, last_sent={}) == []


def test_not_due_when_already_sent_today():
    bkk_today = date(2026, 7, 21)
    assert families_due([_family(1)], now=NOW, last_sent={1: bkk_today}) == []


def test_due_respects_timezone():
    # в UTC сейчас 02 часа — семья с UTC и hour=2 due, с hour=9 нет
    assert families_due([_family(1, tz="UTC", hour=2)], now=NOW, last_sent={}) != []
    assert families_due([_family(2, tz="UTC", hour=9)], now=NOW, last_sent={}) == []


def test_invalid_timezone_falls_back_to_utc():
    fams = [_family(1, tz="Каир", hour=2)]
    assert families_due(fams, now=NOW, last_sent={}) == fams


def test_digest_disabled_family_still_due():
    # семья с выключенным дайджестом остается due — для напоминания о планировании
    fams = [_family(1, enabled=False)]
    assert families_due(fams, now=NOW, last_sent={}) == fams
```

Run: → FAIL (нет `families_due`).

- [ ] **Step 2: Переписать `bot/scheduler.py`**

```python
"""Per-family планировщик: дайджест и напоминания в локальный digest_hour семьи.

Тик каждые 15 минут: для каждой семьи, чей локальный час совпал с digest_hour
и которой сегодня еще не слали, отправляется утренний дайджест (если включен).
Дедупликация — in-memory (после рестарта в тот же час возможен повтор — MVP).
"""
import asyncio
from datetime import UTC, date as DateType
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.formatting import md_to_telegram_html
from core.db import Family
from core.repositories import get_family_members
from core.services import digest

TICK_SECONDS = 900  # 15 минут


def _family_tz(family) -> ZoneInfo:
    try:
        return ZoneInfo(family.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def families_due(
    families, *, now: datetime, last_sent: dict[int, DateType]
) -> list:
    """Семьи, у которых сейчас локальный digest_hour и сегодня еще не слали."""
    due = []
    for f in families:
        local = now.astimezone(_family_tz(f))
        if local.hour == f.digest_hour and last_sent.get(f.id) != local.date():
            due.append(f)
    return due


async def _send_family_digest(
    bot: Bot, sessionmaker: async_sessionmaker, family, today: DateType
) -> None:
    async with sessionmaker() as session:
        text = await digest.build_morning_digest(
            session, family_id=family.id, today=today
        )
        members = await get_family_members(session, family.id)
    if text is None:
        return
    for member in members:
        try:
            await bot.send_message(member.telegram_user_id, md_to_telegram_html(text))
        except Exception:
            logger.exception("scheduler: send failed user_id={}", member.telegram_user_id)


async def _process_due_family(
    bot: Bot, sessionmaker: async_sessionmaker, family, today: DateType
) -> None:
    """Все рассылки семьи в ее digest-час. Точка расширения для напоминаний."""
    if family.digest_enabled:
        await _send_family_digest(bot, sessionmaker, family, today)


async def _scheduler_loop(bot: Bot, sessionmaker: async_sessionmaker) -> None:
    last_sent: dict[int, DateType] = {}
    while True:
        await asyncio.sleep(TICK_SECONDS)
        now = datetime.now(UTC)
        try:
            async with sessionmaker() as session:
                families = list((await session.execute(select(Family))).scalars().all())
        except Exception:
            logger.exception("scheduler: failed to load families")
            continue
        for family in families_due(families, now=now, last_sent=last_sent):
            local_today = now.astimezone(_family_tz(family)).date()
            try:
                await _process_due_family(bot, sessionmaker, family, local_today)
            except Exception:
                logger.exception("scheduler: family {} failed", family.id)
            last_sent[family.id] = local_today


def start_scheduler(bot: Bot, sessionmaker: async_sessionmaker) -> list[asyncio.Task]:
    """Spawn background tasks. Caller is responsible for cancelling them at shutdown."""
    return [asyncio.create_task(_scheduler_loop(bot, sessionmaker), name="digest")]


__all__ = ["start_scheduler", "families_due", "TICK_SECONDS"]
```

Проверить grep'ом импорты удаленных `seconds_until_next`/`BKK`/`DIGEST_HOUR` (tests/unit/test_scheduler.py переписан; других быть не должно — починить, если есть).

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add bot/scheduler.py tests/unit/test_scheduler.py
git commit -m "feat(digest): per-family scheduler — timezone, digest_hour, digest_enabled"
```

---

### Task 5: Напоминание «пора планировать» с кнопкой

**Files:**
- Modify: `core/services/reminders.py`, `core/services/digest.py:31-33`, `bot/scheduler.py` (`_process_due_family`), `bot/keyboards.py`, `bot/handlers/plan.py`
- Test: `tests/integration/test_reminders.py`, `tests/unit/test_plan_handlers.py`, `tests/unit/test_plan_keyboards.py`

**Interfaces:**
- Consumes: `families_due`/`_process_due_family` (Task 4), `get_admins`, `Settings.planning_enabled`, `PlanFlow`, `kb_plan_start`.
- Produces: `reminders.plan_reminder_due(session, *, family_id: int, today: date) -> bool` (ровно за 2 дня до конца активного меню); `keyboards.kb_plan_reminder()` (кнопка `plan:remind`); callback-хендлер `on_plan_reminder` в plan.py — регистрируется ДО catch-all `plan:*`.

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_reminders.py` добавить (посмотреть фикстуры файла; создание меню — как в test_slot_order.py через `create_draft_menu`+`approve_menu`):

```python
from core.services.reminders import plan_reminder_due


async def test_plan_reminder_due_exactly_two_days_before_end(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    today = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session, family_id=fam.id, start_date=today, days_count=3,
        meals=[
            {"date": today + timedelta(days=i), "slot": "dinner",
             "dish_name": f"Д{i}", "protein_kind": "chicken"}
            for i in range(3)  # последняя дата = today + 2
        ],
    )
    await approve_menu(db_session, menu.id)
    assert await plan_reminder_due(db_session, family_id=fam.id, today=today) is True
    assert await plan_reminder_due(
        db_session, family_id=fam.id, today=today - timedelta(days=1)
    ) is False  # осталось 3 дня
    assert await plan_reminder_due(
        db_session, family_id=fam.id, today=today + timedelta(days=1)
    ) is False  # остался 1 день


async def test_plan_reminder_not_due_without_menu(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    assert await plan_reminder_due(db_session, family_id=fam.id, today=date(2026, 7, 21)) is False
```

В `tests/unit/test_plan_keyboards.py`:

```python
from bot.keyboards import kb_plan_reminder


def test_plan_reminder_button():
    assert _datas(kb_plan_reminder()) == ["plan:remind"]
```

В `tests/unit/test_plan_handlers.py`:

```python
async def test_plan_reminder_callback_starts_flow():
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:remind"
    await plan_handler.on_plan_reminder(cb, state)
    state.clear.assert_awaited_once()
    state.set_state.assert_awaited_once_with(plan_handler.PlanFlow.start_date)
    assert "С какого дня" in cb.message.answer.await_args.args[0]
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`core/services/reminders.py` — добавить:

```python
from datetime import date as DateType


async def plan_reminder_due(
    session: AsyncSession, *, family_id: int, today: DateType
) -> bool:
    """True ровно за 2 дня до конца активного меню (спека §5)."""
    meals = await repositories.get_future_meals(session, family_id, today)
    if not meals:
        return False
    return (max(m.date for m in meals) - today).days == 2
```

`core/services/digest.py` — в `_build_end_of_menu_warning` заменить оба текста «пора загрузить новое» на «пора спланировать новое».

`bot/keyboards.py`:

```python
def kb_plan_reminder() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.MENU} Спланировать", callback_data="plan:remind")
    return b.as_markup()
```

`bot/handlers/plan.py` — хендлер ПЕРЕД catch-all (роутерный фильтр IsAdmin уже действует):

```python
@router.callback_query(F.data == "plan:remind")
async def on_plan_reminder(cb: CallbackQuery, state: FSMContext) -> None:
    """Кнопка из напоминания «меню заканчивается» — запускает флоу /plan."""
    await state.clear()
    await state.set_state(PlanFlow.start_date)
    await cb.message.answer("С какого дня планируем меню?", reply_markup=kb_plan_start())
    await cb.answer()
```

`bot/scheduler.py::_process_due_family` — дополнить:

```python
    if get_settings().planning_enabled:
        async with sessionmaker() as session:
            due = await reminders.plan_reminder_due(session, family_id=family.id, today=today)
            admins = await get_admins(session, family_id=family.id) if due else []
        for admin in admins:
            try:
                await bot.send_message(
                    admin.telegram_user_id,
                    "Меню заканчивается через 2 дня. Спланировать следующее?",
                    reply_markup=kb_plan_reminder(),
                )
            except Exception:
                logger.exception(
                    "scheduler: plan reminder failed admin_id={}", admin.telegram_user_id
                )
```

(импорты: `from config import get_settings`, `from core.services import digest, reminders`, `from core.services.family_service import get_admins`, `from bot.keyboards import kb_plan_reminder`.)

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS (тесты digest с текстом «пора загрузить» — обновить на «пора спланировать»).

```bash
git add core/services/ bot/ tests/
git commit -m "feat(reminders): plan-next-menu reminder 2 days before menu ends"
```

---

### Task 6: /settings — дайджест вкл/выкл и час

**Files:**
- Modify: `core/services/family_service.py`, `bot/keyboards.py`, `bot/main.py`, `bot/handlers/start.py`
- Create: `bot/handlers/settings.py`
- Test: `tests/integration/test_family_service.py`, `tests/unit/test_settings_handlers.py` (новый)

**Interfaces:**
- Consumes: `HasFamily`, `IsAdmin`, `Family.digest_enabled/digest_hour/timezone`.
- Produces: `family_service.update_digest_settings(session, *, family: Family, enabled: bool | None = None, hour: int | None = None) -> Family` (валидирует `5 <= hour <= 12`, иначе `ValueError`); роутер `bot.handlers.settings.router` (регистрируется после `family_handler`); callback-префикс `set:`; `/settings` в `bot_commands()` (безусловно) и `help_text()`.

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_family_service.py`:

```python
async def test_update_digest_settings(db_session):
    family, _ = await _make_family(db_session)
    await update_digest_settings(db_session, family=family, enabled=False)
    assert family.digest_enabled is False
    await update_digest_settings(db_session, family=family, hour=7)
    assert family.digest_hour == 7
    with pytest.raises(ValueError):
        await update_digest_settings(db_session, family=family, hour=3)
```

(импорт `update_digest_settings` дополнить.)

Создать `tests/unit/test_settings_handlers.py`:

```python
"""Хендлеры /settings: админ видит кнопки, участник — только текст."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import settings as settings_handler
from core.db import MemberRole


def _family(**kw):
    defaults = dict(id=1, digest_enabled=True, digest_hour=9, timezone="Asia/Bangkok")
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _admin():
    return SimpleNamespace(role=MemberRole.admin, telegram_user_id=1)


def _member():
    return SimpleNamespace(role=MemberRole.member, telegram_user_id=2)


async def test_admin_sees_settings_with_buttons():
    message = AsyncMock()
    await settings_handler.cmd_settings(message, _family(), _admin())
    text = message.answer.await_args.args[0]
    assert "9:00" in text and "Asia/Bangkok" in text
    assert message.answer.await_args.kwargs["reply_markup"] is not None


async def test_member_sees_settings_without_buttons():
    message = AsyncMock()
    await settings_handler.cmd_settings(message, _family(), _member())
    assert message.answer.await_args.kwargs.get("reply_markup") is None


async def test_toggle_digest(monkeypatch):
    updated = {}

    async def fake_update(session, *, family, enabled=None, hour=None):
        updated["enabled"] = enabled
        return family

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:digest:off"
    await settings_handler.on_toggle_digest(cb, _family(), db_session=None)
    assert updated["enabled"] is False
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`core/services/family_service.py`:

```python
async def update_digest_settings(
    session: AsyncSession,
    *,
    family: Family,
    enabled: bool | None = None,
    hour: int | None = None,
) -> Family:
    """Настройки утреннего дайджеста (спека §5). Час — локальный для семьи."""
    if enabled is not None:
        family.digest_enabled = enabled
    if hour is not None:
        if not 5 <= hour <= 12:
            raise ValueError(f"digest_hour вне диапазона 5..12: {hour}")
        family.digest_hour = hour
    await session.flush()
    return family
```

`bot/keyboards.py`:

```python
def kb_settings(family) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if family.digest_enabled:
        b.button(text=f"{emoji.CANCEL} Выключить дайджест", callback_data="set:digest:off")
    else:
        b.button(text=f"{emoji.DONE} Включить дайджест", callback_data="set:digest:on")
    for h in (7, 8, 9, 10):
        mark = f"{emoji.DONE} " if family.digest_hour == h else ""
        b.button(text=f"{mark}{h}:00", callback_data=f"set:hour:{h}")
    b.adjust(1, 4)
    return b.as_markup()
```

Создать `bot/handlers/settings.py`:

```python
"""Настройки семьи: утренний дайджест (вкл/выкл, час). Менять может только админ."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.filters import HasFamily, IsAdmin
from bot.keyboards import kb_settings
from core import emoji
from core.db import Family, FamilyMember
from core.services.family_service import is_admin, update_digest_settings

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily(), IsAdmin())


def _settings_text(family: Family) -> str:
    state = "включен" if family.digest_enabled else "выключен"
    return (
        f"{emoji.PROFILE} Настройки семьи\n\n"
        f"Утренний дайджест: {state}, в {family.digest_hour}:00\n"
        f"Часовой пояс: {family.timezone} (задается городом при онбординге)"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, family: Family, family_member: FamilyMember) -> None:
    if is_admin(family_member):
        await message.answer(_settings_text(family), reply_markup=kb_settings(family))
    else:
        await message.answer(_settings_text(family))


@router.callback_query(F.data.startswith("set:digest:"))
async def on_toggle_digest(cb: CallbackQuery, family: Family, db_session) -> None:
    enabled = cb.data.split(":")[-1] == "on"
    await update_digest_settings(db_session, family=family, enabled=enabled)
    await cb.message.edit_text(_settings_text(family), reply_markup=kb_settings(family))
    await cb.answer("Дайджест включен" if enabled else "Дайджест выключен")


@router.callback_query(F.data.startswith("set:hour:"))
async def on_set_hour(cb: CallbackQuery, family: Family, db_session) -> None:
    hour = int(cb.data.split(":")[-1])
    try:
        await update_digest_settings(db_session, family=family, hour=hour)
    except ValueError:
        await cb.answer("Недоступный час", show_alert=True)
        return
    await cb.message.edit_text(_settings_text(family), reply_markup=kb_settings(family))
    await cb.answer(f"Дайджест в {hour}:00")
```

`bot/main.py`: импорт + `dp.include_router(settings_handler.router)` после `family_handler`; в `bot_commands()` после `invite`: `BotCommand(command="settings", description="Настройки семьи")`.

`bot/handlers/start.py::help_text()` — после строки `/invite`:

```python
        f"{emoji.PROFILE} /settings — настройки семьи",
```

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/services/family_service.py bot/ tests/
git commit -m "feat(settings): /settings — digest on/off and hour per family"
```

---

### Task 7: UX-бэклог этапа 2 + рецепты только из /today

**Files:**
- Modify: `bot/handlers/plan.py` (`cmd_plan`, `on_custom_date`, `on_replace_hint`), `bot/handlers/profile.py` (`on_new_text`), `core/services/menu_planner.py` (`_user_message`, `parse_start_date`), `bot/handlers/menu.py` (`cmd_menu`)
- Test: `tests/unit/test_plan_dates.py`, `tests/unit/test_plan_handlers.py`, `tests/unit/test_menu_handlers.py` (новый)

**Interfaces:**
- Consumes: `delete_draft` (этап 2).
- Produces: команды не проглатываются текстовыми состояниями; повторный `/plan` удаляет сиротский черновик; промпт с русскими днями; «29.02» коротким форматом работает; **кнопки «Рецепт» только в /today** (решение пользователя 2026-07-21, спека §-решение 4: из /menu доступ к рецептам убран; callback `meal:recipe:` и `cb_recipe` остаются — их шлет /today).

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_plan_dates.py`:

```python
def test_parse_start_date_feb_29_short_form():
    # ближайший будущий 29.02 от лета 2027 — в 2028 (високосный)
    assert parse_start_date("29.02", date(2027, 7, 1)) == date(2028, 2, 29)


def test_user_message_uses_russian_weekdays():
    from types import SimpleNamespace

    from core.services.menu_planner import _user_message

    fam = SimpleNamespace(plan_slots=["lunch", "dinner"], profile_md="п")
    msg = _user_message(fam, [date(2026, 7, 27)])  # понедельник
    assert "пн" in msg and "Mon" not in msg
```

В `tests/unit/test_plan_handlers.py`:

```python
async def test_custom_date_ignores_commands():
    """Хендлер on_custom_date не должен матчить команды — проверяем фильтр."""
    from tests.unit.test_button_handlers import _registered_filters

    filters_by_handler = dict(_registered_filters(plan_handler.router))
    on_custom = filters_by_handler["on_custom_date"]
    assert any("startswith" in f and "/" in f for f in on_custom)
    on_hint = filters_by_handler["on_replace_hint"]
    assert any("startswith" in f and "/" in f for f in on_hint)
```

Создать `tests/unit/test_menu_handlers.py`:

```python
"""Рецепты доступны только из /today (решение 2026-07-21): /menu — без кнопок."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import menu as menu_handler
from core.db import MealSlot


def _meal(d: date, slot: MealSlot) -> SimpleNamespace:
    return SimpleNamespace(id=1, date=d, slot=slot, dish_name="Блюдо", side_dishes=[])


async def test_cmd_menu_has_no_recipe_buttons(monkeypatch):
    async def fake_meals(*a, **kw):
        return [_meal(date(2026, 7, 27), MealSlot.lunch)]

    monkeypatch.setattr(menu_handler.repositories, "get_future_meals", fake_meals)
    message = AsyncMock()

    await menu_handler.cmd_menu(message, SimpleNamespace(id=1), db_session=None)

    assert message.answer.await_args.kwargs.get("reply_markup") is None


async def test_cmd_today_keeps_recipe_buttons(monkeypatch):
    async def fake_meals(*a, **kw):
        return [_meal(date(2026, 7, 27), MealSlot.lunch)]

    monkeypatch.setattr(menu_handler.repositories, "get_meals_for_date", fake_meals)
    message = AsyncMock()

    await menu_handler.cmd_today(message, SimpleNamespace(id=1), db_session=None)

    assert message.answer.await_args.kwargs.get("reply_markup") is not None
```

(сигнатуры `cmd_menu`/`cmd_today` сверить с фактическим bot/handlers/menu.py — параметры family/db_session инжектятся aiogram по именам.)

В `tests/unit/test_plan_handlers.py`:

```python
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
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`bot/handlers/plan.py`:
- `cmd_plan` — добавить параметр `db_session: AsyncSession` и до `state.clear()`:

```python
    data = await state.get_data()
    orphan_id = data.get("menu_id")
    if orphan_id:
        await menu_planner.delete_draft(db_session, menu_id=orphan_id)
```

- фильтры `on_custom_date` и `on_replace_hint`: добавить `& ~F.text.startswith("/")` к существующему `F.text & ~F.text.in_({...})`.

`bot/handlers/profile.py::on_new_text` — аналогично `~F.text.startswith("/")` (профиль-текст с «/» в начале — не кейс).

`bot/handlers/menu.py::cmd_menu` — убрать `reply_markup=kb_meal_recipes(meals)` из ответа (рецепты только из /today — решение 2026-07-21); `cmd_today` НЕ трогать (кнопки остаются). Если после этого `kb_meal_recipes` используется только в cmd_today — это ок, ничего не удалять. Существующие тесты, ожидающие кнопки в /menu (если есть в tests/unit/test_menu_keyboards.py или соседних) — привести к новому поведению.

`core/services/menu_planner.py`:
- `_user_message`: заменить `d.strftime('%a')`:

```python
_RU_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
# в date_lines:
    date_lines = "\n".join(f"- {d.isoformat()} ({_RU_WEEKDAYS[d.weekday()]})" for d in dates)
```

- `parse_start_date` — короткую форму парсить без strptime-1900:

```python
    if parsed is None:
        parts = text.split(".")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            day, month = int(parts[0]), int(parts[1])
            for year in (today.year, today.year + 1, today.year + 2):
                try:
                    candidate = DateType(year, month, day)
                except ValueError:
                    continue  # 29.02 в невисокосном году
                if candidate >= today:
                    parsed = candidate
                    break
        if parsed is None:
            return None
    return parsed if parsed >= today else None
```

(диапазон до `today.year + 2` покрывает 29.02, ближайший високосный не дальше 2 лет... на деле до 4 — но `29.02` от 2027 находит 2028; от 2029 нашел бы 2032 только с +3; спека этого не требует — достаточно `(today.year, today.year + 1)` плюс отдельно ближайший високосный для 29.02? НЕТ — не усложнять: перебор `range(today.year, today.year + 5)` с `break` — простой и покрывает все.)

Использовать перебор:

```python
            for year in range(today.year, today.year + 5):
```

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS (существующие тесты parse_start_date, включая перекат года, должны остаться зелеными).

```bash
git add bot/ core/services/menu_planner.py tests/
git commit -m "fix(ux): commands in text states, orphan draft cleanup, ru weekdays, feb 29"
```

---

### Task 8: Тестовый долг этапа 2

**Files:**
- Test: `tests/unit/test_plan_handlers.py`, `tests/unit/test_main_commands.py` (новый), `tests/unit/test_freetext_flag.py`, `tests/integration/test_menu_planner.py`, `tests/unit/test_onboarding_handlers.py`, `tests/integration/test_family_flow.py`

Прод-код НЕ меняется. Если тест вскрывает баг — остановиться и доложить (DONE_WITH_CONCERNS), не чинить молча.

- [ ] **Step 1: Написать тесты (все — новые, по существующим паттернам файлов)**

`tests/unit/test_plan_handlers.py`:

```python
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


async def test_build_shopping_success_reports_count(monkeypatch):
    async def fake_build(*a, **kw):
        return [object(), object(), object()]

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", fake_build)
    message = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=3, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=None, menu=menu)

    placeholder = message.answer.return_value
    assert "3" in placeholder.edit_text.await_args.args[0]


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


async def test_pick_alternative_value_error_alerts(monkeypatch):
    async def fake_apply(*a, **kw):
        raise ValueError("Meal 5 not found")

    async def fake_meal(*a, **kw):
        return SimpleNamespace(id=5)

    monkeypatch.setattr(plan_handler, "apply_replacement", fake_apply)
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:0"
    state.get_data.return_value = {
        "replace_meal_id": 5,
        "alternatives": [{"dish_name": "Х", "side_dishes": [], "protein_kind": "chicken"}],
    }

    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)

    assert cb.answer.await_args.kwargs.get("show_alert") is True
```

(хелпер `_admin_member()` — `SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")`; если `on_pick_alternative` внутри зовет `get_meal_for_family`/др. — сверить с фактическим кодом и замокать по месту.)

Создать `tests/unit/test_main_commands.py`:

```python
"""Флаг-условные анонсы: /plan в командах и /help только при включенном флаге."""
from bot.handlers.start import help_text
from bot.main import bot_commands
from config import get_settings


def test_bot_commands_with_flag():
    cmds = [c.command for c in bot_commands(planning_enabled=True)]
    assert "plan" in cmds


def test_bot_commands_without_flag():
    cmds = [c.command for c in bot_commands(planning_enabled=False)]
    assert "plan" not in cmds


def test_help_text_follows_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    assert "/plan" in help_text()
    monkeypatch.setattr(get_settings(), "planning_enabled", False)
    assert "/plan" not in help_text()
```

`tests/unit/test_freetext_flag.py` — enabled-путь:

```python
async def test_freetext_enabled_calls_conversation(monkeypatch):
    monkeypatch.setattr(freetext, "_conversation_enabled", lambda: True)

    async def fake_handle(*a, **kw):
        return "ответ"

    monkeypatch.setattr(freetext.conversation, "handle_message", fake_handle)
    message, state = AsyncMock(), AsyncMock()
    message.text = "привет"
    state.get_state.return_value = None
    member = SimpleNamespace(telegram_user_id=1)

    await freetext.handle_free_text(
        message, state, family=SimpleNamespace(id=1, profile_md="п"),
        family_member=member, db_session=None,
    )

    thinking = message.answer.return_value
    assert "ответ" in thinking.edit_text.await_args.args[0]
```

(сверить сигнатуру `handle_free_text` по факту; импорты по месту.)

`tests/integration/test_menu_planner.py` — суммирование токенов retry по значению:

```python
async def test_retry_tokens_summed_into_single_usage_row(db_session):
    from sqlalchemy import select

    from core.db import LlmUsage

    fam = await _family(db_session)
    llm = FakeLLM(["мусор", _ok_menu(3)])  # 100/200 токенов на вызов
    await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=llm
    )
    rows = list(
        (await db_session.execute(select(LlmUsage).where(LlmUsage.family_id == fam.id)))
        .scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].tokens_in == 200 and rows[0].tokens_out == 400
```

`tests/integration/test_family_flow.py` — join-уведомления при 2+ админах:

```python
async def test_join_notifies_all_admins(db_session):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bot.handlers.family import start_with_invite

    family, admin1 = await _make_family(db_session, tg_id=111)
    _, second = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await grant_admin(db_session, family_id=family.id, member_id=second.id)

    message = AsyncMock()
    message.from_user = SimpleNamespace(id=333, full_name="Гость")
    command = SimpleNamespace(args=f"inv_{family.invite_code}")
    state = AsyncMock()

    await start_with_invite(message, command, db_session, state, family=None)

    notified = {call.args[0] for call in message.bot.send_message.await_args_list}
    assert notified == {111, 222}  # оба админа, вступивший (333) — нет
```

(имена хелперов `_make_family`/`join_by_invite`/`grant_admin` — сверить с фактическими импортами файла; сигнатуру `start_with_invite` — с bot/handlers/family.py.)

`tests/unit/test_onboarding_handlers.py` — заменить `db_session=None` на `AsyncMock()` в `test_on_profile_ok_when_already_in_family_clears_state` (хрупкость из этапа 1).

- [ ] **Step 2: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add tests/
git commit -m "test: close stage 2 test debt — approve conflicts, flags, token summing, multi-admin notify"
```

---

### Task 9: Схема и инфраструктура — drop can_plan, PG-пул

**Files:**
- Create: `alembic/versions/0006_drop_can_plan.py`
- Modify: `core/db.py` (модель `FamilyMember`, `get_engine`)
- Test: `tests/unit/test_models.py` + smoke миграции на SQLite

**Interfaces:**
- Produces: `FamilyMember` без атрибута `can_plan`; `get_engine()` для `postgresql+asyncpg://` создает engine с `pool_size=10, max_overflow=20, pool_timeout=30, pool_pre_ping=True` (LLM-вызовы держат сессию весь хендлер — этап-1 находка; для SQLite параметры пула не передаются).

- [ ] **Step 1: Проверить остаточные использования can_plan**

Run: `grep -rn "can_plan" --include="*.py" bot core tests scripts alembic | grep -v 0005`
Expected: только `core/db.py` (модель) и, возможно, `tests/unit/test_models.py`, `scripts/seed_own_family.py` — все места из вывода зачистить в Step 3 (из сид-скрипта просто убрать kwarg, если есть).

- [ ] **Step 2: Падающий тест**

В `tests/unit/test_models.py`:

```python
def test_family_member_has_no_can_plan():
    assert not hasattr(FamilyMember(family_id=1, telegram_user_id=1), "can_plan")
```

(существующие тесты, ссылающиеся на can_plan, — удалить/поправить.)

- [ ] **Step 3: Реализация**

`core/db.py` — удалить поле `can_plan` из `FamilyMember`; переписать `get_engine`:

```python
def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().db_url
        kwargs: dict = {"echo": False}
        if url.startswith("postgresql"):
            # LLM-вызовы держат сессию весь хендлер (мидлварь) — запас пула
            kwargs.update(pool_size=10, max_overflow=20, pool_timeout=30, pool_pre_ping=True)
        _engine = create_async_engine(url, **kwargs)
    return _engine
```

Создать `alembic/versions/0006_drop_can_plan.py`:

```python
"""drop family_members.can_plan — права только через role=admin (спека §4)

Revision ID: 0006_drop_can_plan
Revises: 0005_multitenant
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_drop_can_plan"
down_revision: Union[str, Sequence[str], None] = "0005_multitenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("family_members") as b:
        b.drop_column("can_plan")


def downgrade() -> None:
    with op.batch_alter_table("family_members") as b:
        b.add_column(
            sa.Column("can_plan", sa.Boolean(), nullable=False, server_default=sa.false())
        )
```

- [ ] **Step 4: Smoke миграции + прогон**

Run: `rm -f /tmp/mig_test.db && BOT_TOKEN=x ANTHROPIC_API_KEY=x DB_URL=sqlite+aiosqlite:////tmp/mig_test.db .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check .`
Expected: alembic до `0006_drop_can_plan`, тесты PASS.

- [ ] **Step 5: Commit**

```bash
git add core/db.py alembic/versions/0006_drop_can_plan.py tests/ scripts/
git commit -m "feat(db): drop can_plan column, tune PG pool for long LLM calls"
```

---

### Task 10: Финализация

**Files:**
- Modify: `docs/superpowers/ROADMAP.md`
- Test: полный прогон + ручной smoke-чеклист

- [ ] **Step 1: ROADMAP** — в секции «В работе» после ссылки на план этапа 2 добавить:

```markdown
План этапа 3:
[2026-07-21-stage3-personalization.md](plans/2026-07-21-stage3-personalization.md).
```

- [ ] **Step 2: Полный прогон**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS.

- [ ] **Step 3: Ручной smoke (живой бот, PLANNING_ENABLED=true)**

1. `/settings`: выключить дайджест, поменять час, у не-админа — просмотр без кнопок.
2. Утвердить меню → предложение «Составить список покупок?» → кнопка собирает список; повторный тап по кнопке на draft/чужом меню — alert.
3. Выставить `TRIAL_MENU_GEN_LIMIT=1` в env → вторая генерация меню — вежливый отказ про подписку; рецепт из кэша при исчерпанном лимите рецептов — отдается.
4. `MONTHLY_TOKEN_CAP_PER_FAMILY=100` → любая LLM-операция — отказ с «1-го числа».
5. Меню с концом через 2 дня + локальный digest-час → дайджест приходит по таймзоне семьи, следом напоминание с кнопкой «Спланировать» (только админам); кнопка запускает /plan.
6. `/menu` внутри «Своя дата» — команда выполняется, а не «Не понял дату».

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/ROADMAP.md
git commit -m "docs(roadmap): link stage 3 plan"
```

---

## Вне скоупа этапа 3 (роадмап)

- Суперадмин-панель (`/admin`: сводка, поднятие лимитов конкретной семье — пока лимиты только env).
- Биллинг (Telegram Stars), сбор заявок «хочу подписку» с заглушки.
- Вынос планировщика в очередь задач; webhook.
- Локализация (англ/рус) — «Среднесрочное» в роадмапе.
- Персистентная дедупликация дайджеста (сейчас in-memory: после рестарта в тот же час возможен повтор — принято для MVP).
- Stale-клавиатура `kb_plan_meals` под сообщением «Подбираю варианты...» (UX-нит из этапа 2 — кнопки безвредны: их закрывает catch-all/state-гейт).

## Отложено финальным ревью этапа 3 (2026-07-22) — бэклог этапа 4

- Гейт planning_enabled на callback'ах plan:remind (и on_build_shoplist): stale-кнопки работают после выключения флага (kill switch неполный).
- Напоминание «пора планировать» шлется семьям с исчерпанным триалом menu_gen — dead-end UX; pre-check count_llm_operations в _send_plan_reminder.
- Дубль сообщений админам в час дайджеста при 2 днях до конца меню (warning в дайджесте + отдельное напоминание) + общий helper «дней до конца меню» (digest/reminders).
- Uniqueness-констрейнт на shopping_lists.menu_id (TOCTOU двух тапов) + happy-path unit on_build_shoplist — следующей миграцией.
- Handler-тесты LimitExceeded-веток _suggest_and_show/_build_shopping/cb_recipe; рефакторинг дупe except-шейпа.
- set:* callbacks не-админа падают в никуда (спиннер, forged-only); мусорный суффикс set:digest → "off".
- Текст «Меню утверждено.» в отказе _build_shopping странен при позднем тапе; DST-тест families_due; sleep-first рестарт-окно планировщика (задокументирован).
- Конкурентный over-run лимитов (~+1) — принято для MVP, закроет суперадмин-панель.
