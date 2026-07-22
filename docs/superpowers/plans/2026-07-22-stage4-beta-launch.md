# Stage 4: Полировка и запуск беты — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот готов к раздаче внешним семьям: оператор видит метрики и семьи через /admin, отказы лимитов собирают заявки «хочу подписку», список покупок доставляется на выбор (в /list или текстом) и чистится одной кнопкой, kill-switch планирования полный, тексты не отсылают внешних юзеров к JSON-файлам.

**Architecture:** Суперадмин — отдельный слой доверия поверх семейной модели (config.superadmin_ids + фильтр IsSuperadmin + изолированный bot/handlers/admin.py; НЕ смешивать с family_members.role — роадмап). Заявки на подписку — таблица subscription_requests (уникальна по family_id, идемпотентная кнопка на каждом отказе лимитов). Сервис shopping_list разделяется на generate_items (LLM, без записи) + save_items (запись) — это дает текстовую доставку без дублирования LLM-логики; build_from_menu сохраняет сигнатуру. Одна миграция 0007 (subscription_requests + uniqueness на shopping_lists.menu_id).

**Tech Stack:** Python 3.12, aiogram 3, anthropic SDK, SQLAlchemy 2.0 async, Alembic, pytest + pytest-asyncio.

**Reference:** спека §10 этап 4 («тексты, /help, базовые метрики, онбординг первых внешних семей»), ROADMAP «Суперадмин-панель» и «Биллинг» (заявки), секция «Отложено финальным ревью этапа 3» в [плане этапа 3](2026-07-21-stage3-personalization.md), решения пользователя 2026-07-21 (список текстом; полная очистка).

## Global Constraints

- Python `>=3.12`, ruff `line-length = 100`; после каждого таска `.venv/bin/ruff check . && .venv/bin/pytest -q` зелёные; conventional commits.
- Все видимые юзеру тексты — на русском; эмодзи только из `core/emoji.py`; **«ё» запрещена** во всех `.py`/`.md` в `bot/` и `core/` (гард `tests/unit/test_no_yo.py`).
- **Суперадмин — отдельный слой доверия** (роадмап): `superadmin_ids` в конфиге, вне семейной модели; НЕ смешивать с `family_members.role`; `/admin` НЕ анонсируется в `bot_commands()` и `help_text()` (скрытая команда).
- Заявка «хочу подписку» — одна на семью (unique по family_id), кнопка идемпотентна; кнопка появляется на КАЖДОМ отказе лимитов (триал и потолок).
- Kill-switch: при `planning_enabled=False` ВСЕ plan-callbacks (включая `plan:shoplist:*`, `plan:shoptext:*`, `plan:remind`) отвечают заглушкой, а не работают.
- Оценка $ в /admin — ориентир по константам (Sonnet: 3 $/Mtok in, 15 $/Mtok out), не биллинг.
- Схема: единственная миграция этапа — 0007 (`down_revision = "0006_drop_can_plan"`).
- catch-all `plan:*` остается ПОСЛЕДНИМ хендлером в bot/handlers/plan.py; новые plan-callbacks регистрируются до него.
- В `bot/handlers/settings.py` роутерный фильтр callback'ов сейчас `HasFamily(), IsAdmin()` — Task 7 перенесет IsAdmin на уровень хендлеров (чтобы не-админ получал alert, а не спиннер).

---

## File Structure (итог этапа)

```
config.py                        + superadmin_ids (comma-string env SUPERADMIN_IDS)
core/constants.py                + PRICE_USD_PER_MTOK_IN=3.0, PRICE_USD_PER_MTOK_OUT=15.0
core/db.py                       + SubscriptionRequest; ShoppingList.menu_id unique в модели
core/repositories.py             + add_subscription_request, count_subscription_requests,
                                   admin_month_summary, families_overview, items_for_menu
core/services/reminders.py       + days_until_menu_end (общий helper), plan_reminder_due через него
core/services/digest.py          warning через helper; при planning_enabled не дублирует «2 дня»
core/services/shopping_list.py   generate_items/save_items split; clear_all_open; format_items_text
bot/scheduler.py                 _send_plan_reminder: пропуск семей с исчерпанным menu_gen-триалом
bot/filters.py                   + IsSuperadmin
bot/keyboards.py                 kb_shoplist_offer — 2 кнопки; + kb_want_subscription,
                                   kb_shop_clear_confirm; kb_shopping_list + кнопка очистки
bot/handlers/plan.py             kill-switch на callbacks; plan:shoptext; kb подписки на отказах
bot/handlers/menu.py             empty-тексты без «пришли JSON»; kb подписки на отказе рецепта
bot/handlers/shopping.py         очистка списка с подтверждением
bot/handlers/settings.py         IsAdmin на хендлерах + catch-all set:* для не-админов
bot/handlers/subscription.py     NEW: callback sub:want
bot/handlers/admin.py            NEW: /admin (сводка + семьи + заявки)
bot/main.py                      + admin router (ПЕРВЫМ), subscription router
alembic/versions/0007_subscriptions_uq_shoplist.py NEW
tests/...
```

---

### Task 1: Kill-switch, dead-end напоминания, дубль дайджеста

**Files:**
- Modify: `bot/handlers/plan.py` (`on_build_shoplist`, `on_plan_reminder`), `bot/scheduler.py` (`_send_plan_reminder`), `core/services/reminders.py`, `core/services/digest.py:22-34`
- Test: `tests/unit/test_plan_handlers.py`, `tests/unit/test_scheduler.py`, `tests/integration/test_reminders.py`, `tests/integration/test_digest.py`

**Interfaces:**
- Produces: `reminders.days_until_menu_end(session, *, family_id: int, today: date) -> int | None` (None — нет активного меню; иначе `(last_date - today).days`); `plan_reminder_due` реализован через него; `digest._build_end_of_menu_warning` через него же и НЕ добавляет строку при `days == 2 and get_settings().planning_enabled` (напоминание с кнопкой берет этот случай на себя); scheduler не шлет напоминание семьям с исчерпанным триалом menu_gen; plan-callbacks гейтятся `_planning_enabled()`.

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_reminders.py` (фикстуры меню — по образцу существующих тестов файла):

```python
from core.services.reminders import days_until_menu_end


async def test_days_until_menu_end(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    assert await days_until_menu_end(db_session, family_id=fam.id, today=date(2026, 7, 22)) is None
    today = date(2026, 7, 22)
    menu = await create_draft_menu(
        db_session, family_id=fam.id, start_date=today, days_count=3,
        meals=[
            {"date": today + timedelta(days=i), "slot": "dinner",
             "dish_name": f"Д{i}", "protein_kind": "chicken"}
            for i in range(3)
        ],
    )
    await approve_menu(db_session, menu.id)
    assert await days_until_menu_end(db_session, family_id=fam.id, today=today) == 2
```

В `tests/integration/test_digest.py` (по паттерну файла; monkeypatch settings-атрибута как в test_limits):

```python
async def test_digest_skips_two_day_warning_when_planning_enabled(db_session, monkeypatch):
    # при включенном планировании «2 дня» покрывает напоминание с кнопкой — в дайджесте молчим
    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    # ...семья + активное меню, last_date = today + 2 (как в существующих warning-тестах файла)
    text = await digest.build_morning_digest(db_session, family_id=fam.id, today=today)
    assert "заканчивается" not in text


async def test_digest_keeps_two_day_warning_when_planning_disabled(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "planning_enabled", False)
    # ...та же фикстура
    text = await digest.build_morning_digest(db_session, family_id=fam.id, today=today)
    assert "заканчивается через 2 дня" in text
```

(строку «завтра» (days==1) не трогаем — тест на нее в файле должен остаться зеленым.)

В `tests/unit/test_scheduler.py`:

```python
async def test_reminder_skipped_when_trial_exhausted(monkeypatch):
    from bot import scheduler

    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    monkeypatch.setattr(get_settings(), "trial_menu_gen_limit", 1)

    async def fake_due(session, *, family_id, today):
        return True

    async def fake_count(session, *, family_id, operation):
        return 1  # лимит исчерпан

    monkeypatch.setattr(scheduler.reminders, "plan_reminder_due", fake_due)
    monkeypatch.setattr(scheduler, "count_llm_operations", fake_count)
    bot = AsyncMock()

    await scheduler._send_plan_reminder(bot, _fake_sessionmaker(), _family(1), date(2026, 7, 22))

    bot.send_message.assert_not_awaited()
```

Хелпер сессий (добавить в файл, session внутри не используется — все обращения замокан(ы)):

```python
from contextlib import asynccontextmanager


def _fake_sessionmaker():
    @asynccontextmanager
    async def _session():
        yield None

    return _session
```

В `tests/unit/test_plan_handlers.py`:

```python
async def test_plan_callbacks_stub_when_flag_off(monkeypatch):
    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: False)
    cb = AsyncMock()
    cb.data = "plan:remind"
    await plan_handler.on_plan_reminder(cb, AsyncMock(), db_session=None)
    assert cb.answer.await_args.kwargs.get("show_alert") is True

    cb2 = AsyncMock()
    cb2.data = "plan:shoplist:7"
    await plan_handler.on_build_shoplist(cb2, _family(), db_session=None)
    assert cb2.answer.await_args.kwargs.get("show_alert") is True


async def test_build_shoplist_happy_path_builds(monkeypatch):
    """Бэклог этапа 3: happy-path — активное свое меню без списка запускает сборку."""
    from core.db import MenuStatus

    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: True)
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
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`core/services/reminders.py`:

```python
async def days_until_menu_end(
    session: AsyncSession, *, family_id: int, today: DateType
) -> int | None:
    """Дней до последней даты активного меню; None — активного меню нет."""
    meals = await repositories.get_future_meals(session, family_id, today)
    if not meals:
        return None
    return (max(m.date for m in meals) - today).days


async def plan_reminder_due(
    session: AsyncSession, *, family_id: int, today: DateType
) -> bool:
    """True ровно за 2 дня до конца активного меню (спека §5)."""
    return await days_until_menu_end(session, family_id=family_id, today=today) == 2
```

`core/services/digest.py::_build_end_of_menu_warning` — переписать через helper:

```python
from config import get_settings
from core.services import reminders


async def _build_end_of_menu_warning(
    session: AsyncSession, family_id: int, today: DateType
) -> str | None:
    upcoming = await reminders.days_until_menu_end(session, family_id=family_id, today=today)
    if upcoming == 2 and not get_settings().planning_enabled:
        return f"{emoji.WARNING} Меню заканчивается через 2 дня — пора спланировать новое."
    if upcoming == 1:
        return f"{emoji.WARNING} Меню заканчивается завтра — пора спланировать новое."
    return None
```

`bot/scheduler.py::_send_plan_reminder` — пропуск исчерпанного триала (импорт `from core.repositories import count_llm_operations, get_family_members`):

```python
    async with sessionmaker() as session:
        due = await reminders.plan_reminder_due(session, family_id=family.id, today=today)
        if due:
            used = await count_llm_operations(
                session, family_id=family.id, operation="menu_gen"
            )
            if used >= get_settings().trial_menu_gen_limit:
                due = False  # триал исчерпан — не зовем в dead-end
        admins = await get_admins(session, family_id=family.id) if due else []
```

`bot/handlers/plan.py` — в начало `on_build_shoplist` и `on_plan_reminder`:

```python
    if not _planning_enabled():
        await cb.answer("Планирование сейчас выключено", show_alert=True)
        return
```

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add bot/ core/services/ tests/
git commit -m "fix(plan): full planning kill-switch, no dead-end reminders, no digest duplication"
```

---

### Task 2: Миграция 0007 — subscription_requests + uniqueness списка

**Files:**
- Modify: `core/db.py`
- Create: `alembic/versions/0007_subscriptions_uq_shoplist.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: модель `SubscriptionRequest(id, family_id FK unique, telegram_user_id BigInteger, created_at)`; `ShoppingList.menu_id` уникален (закрывает TOCTOU двойного тапа из бэклога).

- [ ] **Step 1: Падающий тест**

В `tests/unit/test_models.py`:

```python
def test_subscription_request_model():
    from core.db import SubscriptionRequest

    r = SubscriptionRequest(family_id=1, telegram_user_id=42)
    assert r.family_id == 1


def test_shopping_list_menu_id_unique():
    from core.db import ShoppingList

    assert ShoppingList.__table__.c.menu_id.unique
```

Run: → FAIL (ImportError / unique is None).

- [ ] **Step 2: Модели в `core/db.py`**

`ShoppingList.menu_id` — добавить `unique=True`:

```python
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False, unique=True)
```

Новая модель (рядом с LlmUsage):

```python
class SubscriptionRequest(Base):
    """Заявка «хочу подписку» с заглушки лимитов — одна на семью (проверка спроса)."""

    __tablename__ = "subscription_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("families.id"), nullable=False, unique=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[CreatedAt]
```

- [ ] **Step 3: Миграция `alembic/versions/0007_subscriptions_uq_shoplist.py`**

```python
"""subscription requests table + unique shopping list per menu

Revision ID: 0007_subscriptions_uq_shoplist
Revises: 0006_drop_can_plan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_subscriptions_uq_shoplist"
down_revision: Union[str, Sequence[str], None] = "0006_drop_can_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "family_id", sa.Integer(), sa.ForeignKey("families.id"),
            nullable=False, unique=True,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("shopping_lists") as b:
        b.create_unique_constraint("uq_shopping_lists_menu_id", ["menu_id"])


def downgrade() -> None:
    with op.batch_alter_table("shopping_lists") as b:
        b.drop_constraint("uq_shopping_lists_menu_id", type_="unique")
    op.drop_table("subscription_requests")
```

- [ ] **Step 4: Smoke + прогон + Commit**

Run: `rm -f /tmp/mig_test.db && BOT_TOKEN=x ANTHROPIC_API_KEY=x DB_URL=sqlite+aiosqlite:////tmp/mig_test.db .venv/bin/alembic upgrade head && BOT_TOKEN=x ANTHROPIC_API_KEY=x DB_URL=sqlite+aiosqlite:////tmp/mig_test.db .venv/bin/alembic downgrade -1 && BOT_TOKEN=x ANTHROPIC_API_KEY=x DB_URL=sqlite+aiosqlite:////tmp/mig_test.db .venv/bin/alembic upgrade head && .venv/bin/pytest -q && .venv/bin/ruff check .`
Expected: alembic до 0007 (туда-обратно-туда), тесты PASS. ВНИМАНИЕ: существующие integration-тесты, где одна семья дважды строит список по РАЗНЫМ меню, — не задеты (uq по menu_id); если какой-то тест строит два списка по одному menu_id — он теперь падает IntegrityError, поправить фикстуру.

```bash
git add core/db.py alembic/versions/0007_subscriptions_uq_shoplist.py tests/unit/test_models.py
git commit -m "feat(db): subscription_requests table, unique shopping list per menu"
```

---

### Task 3: Заявки «хочу подписку» на отказах лимитов

**Files:**
- Modify: `config.py`, `core/repositories.py`, `bot/keyboards.py`, `bot/main.py`, `bot/handlers/plan.py` (3 denial-места), `bot/handlers/menu.py` (`cb_recipe`)
- Create: `bot/handlers/subscription.py`
- Test: `tests/integration/test_subscription.py` (новый), `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Consumes: `SubscriptionRequest` (Task 2), `denial_text` (этап 3).
- Produces (используется Task 4):
  - `Settings.superadmin_ids: list[int]` (env `SUPERADMIN_IDS="111,222"`, comma-string, пусто по умолчанию).
  - `repositories.add_subscription_request(session, *, family_id: int, telegram_user_id: int) -> bool` — True если заявка новая, False если по семье уже есть (без исключений).
  - `repositories.count_subscription_requests(session) -> int`.
  - `keyboards.kb_want_subscription()` — кнопка «Хочу подписку» (callback `sub:want`).
  - Роутер `bot.handlers.subscription.router` (HasFamily; любой член семьи); уведомление всем superadmin_ids о новой заявке.
  - Все 4 denial-места (генерация/замена/список/рецепт) шлют `denial_text(e)` с `reply_markup=kb_want_subscription()`; в `_build_shopping` текст отказа — просто `denial_text(e)` (префикс «Меню утверждено.» убран — странен при позднем тапе, бэклог).

- [ ] **Step 1: Падающие тесты**

Создать `tests/integration/test_subscription.py`:

```python
"""Заявки «хочу подписку»: одна на семью, идемпотентная кнопка."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.db import Family
from core.repositories import add_subscription_request, count_subscription_requests


async def _family(db_session) -> Family:
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_add_subscription_request_idempotent(db_session):
    fam = await _family(db_session)
    assert await add_subscription_request(
        db_session, family_id=fam.id, telegram_user_id=1
    ) is True
    assert await add_subscription_request(
        db_session, family_id=fam.id, telegram_user_id=2
    ) is False  # вторая заявка той же семьи не создается
    assert await count_subscription_requests(db_session) == 1


async def test_want_subscription_handler_notifies_superadmins(db_session, monkeypatch):
    from bot.handlers import subscription as sub_handler
    from config import get_settings

    monkeypatch.setattr(get_settings(), "superadmin_ids", [999])
    fam = await _family(db_session)
    cb = AsyncMock()
    cb.from_user = SimpleNamespace(id=1, full_name="Юля")

    await sub_handler.on_want_subscription(cb, fam, db_session)

    cb.answer.assert_awaited()
    sent_to = {call.args[0] for call in cb.bot.send_message.await_args_list}
    assert sent_to == {999}

    # повторный тап — вежливо, без второго уведомления
    cb2 = AsyncMock()
    cb2.from_user = SimpleNamespace(id=2, full_name="Вова")
    await sub_handler.on_want_subscription(cb2, fam, db_session)
    cb2.bot.send_message.assert_not_awaited()
```

В `tests/unit/test_plan_handlers.py` — обновить `test_generation_trial_denial_shows_polite_text`: дополнительно `assert placeholder.edit_text.await_args.kwargs.get("reply_markup") is not None`; добавить аналогичные denial-тесты для `_suggest_and_show` и `_build_shopping` (monkeypatch `suggest_replacements`/`shopping_list.build_from_menu` → raise TrialLimitExceeded("replace")/MonthlyCapExceeded(); ассерты: текст denial + reply_markup не None; для `_build_shopping` — текст БЕЗ «Меню утверждено»). В `tests/unit/test_menu_handlers.py` — такой же denial-тест для `cb_recipe` (monkeypatch `recipe_service.get_recipe` → TrialLimitExceeded("recipe"); ассерт: placeholder.edit_text с denial-текстом и reply_markup не None; get_meal_for_family замокать на SimpleNamespace(id=1)).

Run: → FAIL.

- [ ] **Step 2: Конфиг**

`config.py`:

```python
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    ...  # существующие поля
    # суперадмины — операторы продукта, ОТДЕЛЬНЫЙ слой доверия, не роль семьи (роадмап)
    superadmin_ids: Annotated[list[int], NoDecode] = []

    @field_validator("superadmin_ids", mode="before")
    @classmethod
    def _parse_superadmin_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.split(",") if x.strip()]
        return v
```

`.env.example`: добавить `SUPERADMIN_IDS=` с комментарием «Telegram ID операторов через запятую».

- [ ] **Step 3: Репозиторий**

`core/repositories.py`:

```python
async def add_subscription_request(
    session: AsyncSession, *, family_id: int, telegram_user_id: int
) -> bool:
    """Заявка «хочу подписку». True — новая; False — по семье уже есть."""
    existing = (
        await session.execute(
            select(SubscriptionRequest.id).where(
                SubscriptionRequest.family_id == family_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(
        SubscriptionRequest(family_id=family_id, telegram_user_id=telegram_user_id)
    )
    await session.flush()
    return True


async def count_subscription_requests(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(SubscriptionRequest)
    )
    return int(result.scalar_one())
```

(импорт `SubscriptionRequest` из core.db дополнить.)

- [ ] **Step 4: Клавиатура, хендлер, разводка**

`bot/keyboards.py`:

```python
def kb_want_subscription() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Хочу подписку", callback_data="sub:want")
    return b.as_markup()
```

Создать `bot/handlers/subscription.py`:

```python
"""Заявки «хочу подписку» с заглушек лимитов (роадмап: проверка спроса до биллинга)."""
import html

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily
from config import get_settings
from core.db import Family
from core.repositories import add_subscription_request

router = Router()
router.callback_query.filter(HasFamily())


@router.callback_query(F.data == "sub:want")
async def on_want_subscription(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    created = await add_subscription_request(
        db_session, family_id=family.id, telegram_user_id=cb.from_user.id
    )
    if not created:
        await cb.answer("Вы уже в списке — напишем, как только подписка появится!")
        return
    await cb.answer("Записали! Напишем, как только подписку можно будет оформить.")
    family_name = html.escape(family.name) if family.name else str(family.id)
    for admin_id in get_settings().superadmin_ids:
        try:
            await cb.bot.send_message(
                admin_id,
                f"Заявка на подписку: семья «{family_name}» (id={family.id}), "
                f"от юзера {cb.from_user.id}",
            )
        except Exception:
            logger.warning("subscription: superadmin notify failed id={}", admin_id)
```

`bot/main.py`: импорт + `dp.include_router(subscription_handler.router)` после `settings_handler`.

Denial-места — добавить `reply_markup=kb_want_subscription()`:
- `bot/handlers/plan.py::_generate_and_show`: `await placeholder.edit_text(denial_text(e), reply_markup=kb_want_subscription())`
- `bot/handlers/plan.py::_suggest_and_show`: то же.
- `bot/handlers/plan.py::_build_shopping`: `await placeholder.edit_text(denial_text(e), reply_markup=kb_want_subscription())` (префикс «Меню утверждено. » убрать).
- `bot/handlers/menu.py::cb_recipe`: то же.
(импорт `kb_want_subscription` в оба файла.)

- [ ] **Step 5: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add config.py .env.example core/repositories.py bot/ tests/
git commit -m "feat(subscription): want-subscription requests from limit denials"
```

---

### Task 4: Суперадмин /admin — метрики и семьи

**Files:**
- Modify: `core/constants.py`, `core/repositories.py`, `bot/filters.py`, `bot/main.py`
- Create: `bot/handlers/admin.py`
- Test: `tests/unit/test_filters.py`, `tests/integration/test_admin_metrics.py` (новый), `tests/unit/test_admin_handlers.py` (новый)

**Interfaces:**
- Consumes: `Settings.superadmin_ids`, `count_subscription_requests` (Task 3), `sum_llm_tokens_current_month`-граница (этап 3: строгое `>` с эпсилоном).
- Produces:
  - `core.constants.PRICE_USD_PER_MTOK_IN = 3.0`, `PRICE_USD_PER_MTOK_OUT = 15.0` (ориентир Sonnet, только для сводки /admin).
  - `bot.filters.IsSuperadmin` — `event.from_user.id in get_settings().superadmin_ids` (НЕ зависит от family).
  - `repositories.admin_month_summary(session, *, now: datetime) -> dict` — ключи: `families` (int), `ops` (dict[str, int] — операции за месяц), `tokens_in`, `tokens_out` (int, за месяц).
  - `repositories.families_overview(session, *, now: datetime) -> list[dict]` — по семье: `id`, `name`, `members`, `timezone`, `tokens_month`.
  - Роутер `bot.handlers.admin.router` — регистрируется в `create_dispatcher` ПЕРВЫМ (до family_handler); `/admin` не в bot_commands/help.

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_filters.py`:

```python
async def test_is_superadmin(monkeypatch):
    from bot.filters import IsSuperadmin
    from config import get_settings

    monkeypatch.setattr(get_settings(), "superadmin_ids", [42])
    yes = SimpleNamespace(from_user=SimpleNamespace(id=42))
    no = SimpleNamespace(from_user=SimpleNamespace(id=7))
    assert await IsSuperadmin()(yes) is True
    assert await IsSuperadmin()(no) is False
    assert await IsSuperadmin()(SimpleNamespace(from_user=None)) is False
```

Создать `tests/integration/test_admin_metrics.py`:

```python
"""Метрики /admin: сводка за календарный месяц и обзор семей."""
from datetime import UTC, datetime

from core.db import Family, FamilyMember, MemberRole
from core.repositories import (
    admin_month_summary,
    families_overview,
    log_llm_usage,
)

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


async def test_admin_month_summary(db_session):
    fam1, fam2 = Family(name="a"), Family(name="b")
    db_session.add_all([fam1, fam2])
    await db_session.flush()
    await log_llm_usage(db_session, family_id=fam1.id, operation="menu_gen",
                        tokens_in=100, tokens_out=200)
    await log_llm_usage(db_session, family_id=fam2.id, operation="recipe",
                        tokens_in=10, tokens_out=20)

    s = await admin_month_summary(db_session, now=NOW)

    assert s["families"] == 2
    assert s["ops"] == {"menu_gen": 1, "recipe": 1}
    assert s["tokens_in"] == 110 and s["tokens_out"] == 220


async def test_families_overview(db_session):
    fam = Family(name="a", timezone="Asia/Bangkok")
    db_session.add(fam)
    await db_session.flush()
    db_session.add(FamilyMember(family_id=fam.id, telegram_user_id=1,
                                role=MemberRole.admin))
    await db_session.flush()
    await log_llm_usage(db_session, family_id=fam.id, operation="menu_gen",
                        tokens_in=5, tokens_out=7)

    rows = await families_overview(db_session, now=NOW)

    assert rows[0]["id"] == fam.id
    assert rows[0]["members"] == 1
    assert rows[0]["tokens_month"] == 12
```

Создать `tests/unit/test_admin_handlers.py`:

```python
"""Хендлер /admin: сводка форматируется и отправляется."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from bot.handlers import admin as admin_handler


async def test_cmd_admin_sends_summary(monkeypatch):
    async def fake_summary(session, *, now):
        return {"families": 3, "ops": {"menu_gen": 5, "recipe": 2},
                "tokens_in": 1_000_000, "tokens_out": 200_000}

    async def fake_overview(session, *, now):
        return [{"id": 1, "name": "Тест", "members": 2,
                 "timezone": "UTC", "tokens_month": 500}]

    async def fake_requests(session):
        return 1

    monkeypatch.setattr(admin_handler.repositories, "admin_month_summary", fake_summary)
    monkeypatch.setattr(admin_handler.repositories, "families_overview", fake_overview)
    monkeypatch.setattr(
        admin_handler.repositories, "count_subscription_requests", fake_requests
    )
    message = AsyncMock()

    await admin_handler.cmd_admin(message, db_session=None)

    text = message.answer.await_args.args[0]
    assert "Семей: 3" in text and "menu_gen: 5" in text and "Тест" in text
    assert "$" in text  # оценка стоимости присутствует
```

Run: → FAIL.

- [ ] **Step 2: Константы, фильтр, репозитории**

`core/constants.py`:

```python
# Ориентир цены Sonnet для сводки /admin (не биллинг): $ за миллион токенов
PRICE_USD_PER_MTOK_IN = 3.0
PRICE_USD_PER_MTOK_OUT = 15.0
```

`bot/filters.py`:

```python
from config import get_settings


class IsSuperadmin(Filter):
    """Оператор продукта (config.superadmin_ids) — отдельный слой доверия, не роль семьи."""

    async def __call__(self, event: TelegramObject, **_: Any) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in get_settings().superadmin_ids
```

`core/repositories.py` (использовать ту же эпсилон-границу месяца, что в `sum_llm_tokens_current_month` — вынести приватный helper `_month_boundary(now) -> datetime` и переиспользовать в обоих местах):

```python
def _month_boundary(now: datetime) -> datetime:
    """Граница календарного месяца для created_at-фильтров.

    Строгое > с эпсилоном: SQLite сравнивает datetime текстово, bound-параметр
    несет .000000, а CURRENT_TIMESTAMP пишет без микросекунд.
    """
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    return month_start - timedelta(microseconds=1)


async def admin_month_summary(session: AsyncSession, *, now: datetime) -> dict:
    boundary = _month_boundary(now)
    families = int(
        (await session.execute(select(func.count()).select_from(Family))).scalar_one()
    )
    ops_rows = (
        await session.execute(
            select(LlmUsage.operation, func.count())
            .where(LlmUsage.created_at > boundary)
            .group_by(LlmUsage.operation)
        )
    ).all()
    tokens_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LlmUsage.tokens_in), 0),
                func.coalesce(func.sum(LlmUsage.tokens_out), 0),
            ).where(LlmUsage.created_at > boundary)
        )
    ).one()
    return {
        "families": families,
        "ops": {op: int(cnt) for op, cnt in ops_rows},
        "tokens_in": int(tokens_row[0]),
        "tokens_out": int(tokens_row[1]),
    }


async def families_overview(session: AsyncSession, *, now: datetime) -> list[dict]:
    boundary = _month_boundary(now)
    rows = (
        await session.execute(
            select(
                Family.id,
                Family.name,
                Family.timezone,
                func.count(func.distinct(FamilyMember.id)),
                func.coalesce(func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out), 0),
            )
            .select_from(Family)
            .outerjoin(FamilyMember, FamilyMember.family_id == Family.id)
            .outerjoin(
                LlmUsage,
                (LlmUsage.family_id == Family.id) & (LlmUsage.created_at > boundary),
            )
            .group_by(Family.id, Family.name, Family.timezone)
            .order_by(Family.id)
        )
    ).all()
    return [
        {"id": r[0], "name": r[1], "timezone": r[2], "members": int(r[3]),
         "tokens_month": int(r[4])}
        for r in rows
    ]
```

ВНИМАНИЕ (для имплементера): outerjoin двух таблиц одновременно даст декартово раздувание SUM при >1 участника И >1 usage-записи. Правильно — подзапросами:

```python
    members_sq = (
        select(FamilyMember.family_id, func.count().label("members"))
        .group_by(FamilyMember.family_id)
        .subquery()
    )
    tokens_sq = (
        select(
            LlmUsage.family_id,
            func.sum(LlmUsage.tokens_in + LlmUsage.tokens_out).label("tokens"),
        )
        .where(LlmUsage.created_at > boundary)
        .group_by(LlmUsage.family_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Family.id, Family.name, Family.timezone,
                func.coalesce(members_sq.c.members, 0),
                func.coalesce(tokens_sq.c.tokens, 0),
            )
            .outerjoin(members_sq, members_sq.c.family_id == Family.id)
            .outerjoin(tokens_sq, tokens_sq.c.family_id == Family.id)
            .order_by(Family.id)
        )
    ).all()
```

Использовать вариант с подзапросами; добавить в test_families_overview вторую usage-запись и второго участника той же семьи и ассертить точные значения (members == 2, tokens_month == сумма) — это ловит декартову ошибку.

`sum_llm_tokens_current_month` — переписать границу через `_month_boundary(now)` (поведение не меняется, тесты этапа 3 остаются зелеными).

- [ ] **Step 3: Хендлер `bot/handlers/admin.py`**

```python
"""Суперадмин /admin: сводка и семьи. Отдельный слой доверия (config.superadmin_ids)."""
import html
from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import IsSuperadmin
from core import repositories
from core.constants import PRICE_USD_PER_MTOK_IN, PRICE_USD_PER_MTOK_OUT

router = Router()
router.message.filter(IsSuperadmin())


def _usd(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * PRICE_USD_PER_MTOK_IN
        + tokens_out / 1_000_000 * PRICE_USD_PER_MTOK_OUT
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    summary = await repositories.admin_month_summary(db_session, now=now)
    overview = await repositories.families_overview(db_session, now=now)
    requests = await repositories.count_subscription_requests(db_session)

    ops_lines = [f"  {op}: {cnt}" for op, cnt in sorted(summary["ops"].items())]
    usd = _usd(summary["tokens_in"], summary["tokens_out"])
    lines = [
        f"<b>Сводка за месяц ({now.strftime('%m.%Y')})</b>",
        f"Семей: {summary['families']}",
        f"Заявок на подписку: {requests}",
        "Операции:",
        *(ops_lines or ["  нет"]),
        f"Токены: {summary['tokens_in']:,} in / {summary['tokens_out']:,} out",
        f"Оценка стоимости: ${usd:.2f} (ориентир Sonnet)",
        "",
        "<b>Семьи</b> (id · имя · участников · tz · токены/мес):",
    ]
    for f in overview:
        name = html.escape(f["name"]) if f["name"] else "—"
        lines.append(
            f"{f['id']} · {name} · {f['members']} · {f['timezone']} · "
            f"{f['tokens_month']:,}"
        )
    await message.answer("\n".join(lines))
```

`bot/main.py`: импорт + `dp.include_router(admin_handler.router)` ПЕРВЫМ (строкой выше family_handler; комментарий «суперадмин — вне семейной модели»). `/admin` в bot_commands НЕ добавлять.

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/ bot/ tests/
git commit -m "feat(admin): /admin superadmin summary — families, ops, tokens, cost estimate"
```

---

### Task 5: Список покупок текстом (вторая кнопка доставки)

**Files:**
- Modify: `core/services/shopping_list.py`, `core/repositories.py`, `bot/keyboards.py` (`kb_shoplist_offer`), `bot/handlers/plan.py`
- Test: `tests/integration/test_shopping_list.py`, `tests/unit/test_plan_keyboards.py`, `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Produces:
  - `shopping_list.ItemDraft(BaseModel)`: `name: str`, `quantity: str = ""` (переименованный публичный `_ItemSchema`).
  - `shopping_list.generate_items(session, *, family_id, menu, profile_md, llm=None) -> list[ItemDraft]` — LLM + парс + `llm_usage("shopping")`; БД не пишет; лимиты проверяет.
  - `shopping_list.save_items(session, *, family_id, menu, items: list[ItemDraft]) -> list[ShoppingItem]` — close_stale + ShoppingList + items (без LLM).
  - `shopping_list.build_from_menu(...)` — прежняя сигнатура/поведение = generate + save.
  - `shopping_list.format_items_text(items) -> str` — «• name — quantity» построчно (работает и с ItemDraft, и с ShoppingItem — по атрибутам name/quantity).
  - `repositories.items_for_menu(session, *, menu_id: int) -> list[ShoppingItem]` — пункты списка данного меню.
  - `keyboards.kb_shoplist_offer(menu_id)` — ДВЕ кнопки: «В список /list» (`plan:shoplist:<id>`) и «Показать текстом» (`plan:shoptext:<id>`).
  - Хендлер `on_shoplist_text` в plan.py (`plan:shoptext:`, ДО catch-all): если список в БД уже есть — рендер из БД без LLM; иначе `generate_items` → текст (БЕЗ записи в БД — кнопка «В список» останется рабочей и вызовет LLM снова, потолок стережет).

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_shopping_list.py` (FakeLLM файла уже есть):

```python
async def test_generate_items_no_db_writes(db_session):
    fam, menu = await _family_with_menu(db_session)
    items = await shopping_list.generate_items(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    assert [i.name for i in items] == ["Куриные бёдра", "Рис"]
    assert await shopping_list.has_list_for_menu(db_session, menu_id=menu.id) is False
    assert await get_open_shopping_items(db_session, family_id=fam.id) == []
    # usage залогирован
    assert await count_llm_operations(db_session, family_id=fam.id, operation="shopping") == 1


async def test_save_items_persists_and_closes_stale(db_session):
    fam, menu = await _family_with_menu(db_session)
    drafts = [shopping_list.ItemDraft(name="Морковь", quantity="1 кг")]
    saved = await shopping_list.save_items(
        db_session, family_id=fam.id, menu=menu, items=drafts
    )
    assert saved[0].shopping_list_id is not None
    assert await shopping_list.has_list_for_menu(db_session, menu_id=menu.id) is True


def test_format_items_text():
    drafts = [
        shopping_list.ItemDraft(name="Рис", quantity="500 г"),
        shopping_list.ItemDraft(name="Соль", quantity=""),
    ]
    text = shopping_list.format_items_text(drafts)
    assert "• Рис — 500 г" in text and "• Соль" in text and "— \n" not in text
```

(существующие тесты build_from_menu должны остаться зелеными без правок — поведение не меняется.)

В `tests/unit/test_plan_keyboards.py` — обновить `test_shoplist_offer_button`:

```python
def test_shoplist_offer_two_buttons():
    assert _datas(kb_shoplist_offer(7)) == ["plan:shoplist:7", "plan:shoptext:7"]
```

В `tests/unit/test_plan_handlers.py`:

```python
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
```

Run: → FAIL.

- [ ] **Step 2: Сервис**

`core/services/shopping_list.py` — переименовать `_ItemSchema` → `ItemDraft` (публичный; `_ShoppingSchema.items: list[ItemDraft]`), разделить `build_from_menu`:

```python
async def generate_items(
    session: AsyncSession,
    *,
    family_id: int,
    menu: Menu,
    profile_md: str,
    llm: LLMClient | None = None,
) -> list[ItemDraft]:
    """LLM-сборка пунктов по меню (operation="shopping"). БД не трогает."""
    await limits.ensure_within_limits(session, family_id=family_id, operation="shopping")
    llm = llm or get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("shopping_list_builder", profile_md=profile_md),
        messages=[{"role": "user", "content": f"Меню:\n{_menu_as_text(menu)}"}],
        max_tokens=2048,
    )
    try:
        parsed = _ShoppingSchema.model_validate(parse_json_response(resp.text))
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse shopping list: {e}") from e
    await repositories.log_llm_usage(
        session, family_id=family_id, operation="shopping",
        tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
    )
    return parsed.items


async def save_items(
    session: AsyncSession, *, family_id: int, menu: Menu, items: list[ItemDraft]
) -> list[ShoppingItem]:
    """Записать собранные пункты: закрыть устаревшие, создать список меню."""
    await close_stale_menu_items(session, family_id=family_id)
    sl = ShoppingList(menu_id=menu.id)
    session.add(sl)
    await session.flush()
    rows = [
        ShoppingItem(
            shopping_list_id=sl.id, family_id=family_id, name=i.name, quantity=i.quantity
        )
        for i in items
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def build_from_menu(
    session: AsyncSession,
    *,
    family_id: int,
    menu: Menu,
    profile_md: str,
    llm: LLMClient | None = None,
) -> list[ShoppingItem]:
    """LLM-сборка + запись (кнопка «В список»)."""
    items = await generate_items(
        session, family_id=family_id, menu=menu, profile_md=profile_md, llm=llm
    )
    return await save_items(session, family_id=family_id, menu=menu, items=items)


def format_items_text(items) -> str:
    """Текстовый список для «мгновенной закупки» — по атрибутам name/quantity."""
    lines = []
    for i in items:
        suffix = f" — {i.quantity}" if i.quantity else ""
        lines.append(f"• {i.name}{suffix}")
    return "\n".join(lines)
```

`core/repositories.py`:

```python
async def items_for_menu(session: AsyncSession, *, menu_id: int) -> list[ShoppingItem]:
    stmt = (
        select(ShoppingItem)
        .join(ShoppingList, ShoppingItem.shopping_list_id == ShoppingList.id)
        .where(ShoppingList.menu_id == menu_id)
        .order_by(ShoppingItem.id)
    )
    return list((await session.execute(stmt)).scalars().all())
```

(импорт `ShoppingList` дополнить.)

- [ ] **Step 3: Клавиатура и хендлер**

`bot/keyboards.py::kb_shoplist_offer` — заменить:

```python
def kb_shoplist_offer(menu_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.SHOPPING} В список /list", callback_data=f"plan:shoplist:{menu_id}")
    b.button(text=f"{emoji.MENU} Показать текстом", callback_data=f"plan:shoptext:{menu_id}")
    b.adjust(1)
    return b.as_markup()
```

`bot/handlers/plan.py` — новый хендлер сразу после `on_build_shoplist` (до `plan:remind` и catch-all):

```python
@router.callback_query(F.data.startswith("plan:shoptext:"))
async def on_shoplist_text(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    """Список текстом — для мгновенной закупки без чек-листа (решение 2026-07-21)."""
    if not _planning_enabled():
        await cb.answer("Планирование сейчас выключено", show_alert=True)
        return
    menu_id = int(cb.data.split(":")[-1])
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    if menu is None or menu.family_id != family.id or menu.status != MenuStatus.active:
        await cb.answer("Меню не найдено или не утверждено", show_alert=True)
        return
    if await shopping_list.has_list_for_menu(db_session, menu_id=menu.id):
        items = await repositories.items_for_menu(db_session, menu_id=menu.id)
        await cb.answer()
        await cb.message.answer(
            f"{emoji.SHOPPING} Список покупок:\n{shopping_list.format_items_text(items)}"
        )
        return
    await cb.answer()
    placeholder = await cb.message.answer(f"{emoji.SHOPPING} Собираю список покупок...")
    try:
        drafts = await shopping_list.generate_items(
            db_session, family_id=family.id, menu=menu, profile_md=family.profile_md or ""
        )
    except LimitExceeded as e:
        await placeholder.edit_text(denial_text(e), reply_markup=kb_want_subscription())
        return
    except LLMError:
        logger.exception("plan: shoptext build failed menu_id={}", menu.id)
        await placeholder.edit_text(
            "Список собрать не получилось.",
            reply_markup=kb_retry(f"plan:shoptext:{menu.id}"),
        )
        return
    await placeholder.edit_text(
        f"{emoji.SHOPPING} Список покупок:\n{shopping_list.format_items_text(drafts)}\n\n"
        "Нужен чек-лист — нажмите «В список /list» выше."
    )
```

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/ bot/ tests/
git commit -m "feat(shopping): deliver list as plain text on demand, split generate/save"
```

---

### Task 6: Полная очистка списка покупок

**Files:**
- Modify: `core/services/shopping_list.py`, `bot/keyboards.py` (`kb_shopping_list` + новая kb), `bot/handlers/shopping.py`
- Test: `tests/integration/test_shopping_list.py`, `tests/unit/test_shopping_handlers.py` (новый)

**Interfaces:**
- Produces: `shopping_list.clear_all_open(session, *, family_id: int) -> int` — закрывает ВСЕ открытые пункты (и ручные, и menu-bound; решение пользователя 2026-07-21); в `/list` при непустом списке кнопка «Очистить все» (`shop:clear`) → подтверждение (`kb_shop_clear_confirm`: `shop:clear:yes` / `shop:clear:no`); доступно любому члену семьи (как весь /list).

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_shopping_list.py`:

```python
async def test_clear_all_open_closes_manual_and_menu_bound(db_session):
    fam, menu = await _family_with_menu(db_session)
    await shopping_list.add_manual_item(db_session, family_id=fam.id, name="Молоко")
    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    closed = await shopping_list.clear_all_open(db_session, family_id=fam.id)
    assert closed == 3  # молоко + 2 из меню
    assert await get_open_shopping_items(db_session, family_id=fam.id) == []
```

Создать `tests/unit/test_shopping_handlers.py`:

```python
"""Очистка списка: кнопка → подтверждение → очистка."""
from unittest.mock import AsyncMock

from bot.handlers import shopping as shopping_handler
from bot.keyboards import kb_shop_clear_confirm, kb_shopping_list


def _datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_clear_button_present_only_with_items():
    item = type("I", (), {"id": 1, "name": "Рис", "quantity": "", "bought": False})()
    assert "shop:clear" in _datas(kb_shopping_list([item]))
    assert "shop:clear" not in _datas(kb_shopping_list([]))


def test_clear_confirm_keyboard():
    assert _datas(kb_shop_clear_confirm()) == ["shop:clear:yes", "shop:clear:no"]


async def test_clear_yes_calls_service(monkeypatch):
    cleared = {}

    async def fake_clear(session, *, family_id):
        cleared["family_id"] = family_id
        return 5

    monkeypatch.setattr(shopping_handler.shopping_list, "clear_all_open", fake_clear)
    cb = AsyncMock()
    cb.data = "shop:clear:yes"
    family = type("F", (), {"id": 1})()

    await shopping_handler.cb_clear_yes(cb, family, db_session=None)

    assert cleared["family_id"] == 1
    assert "5" in cb.message.edit_text.await_args.args[0]
```

Run: → FAIL.

- [ ] **Step 2: Сервис и клавиатуры**

`core/services/shopping_list.py`:

```python
async def clear_all_open(session: AsyncSession, *, family_id: int) -> int:
    """Закрыть ВСЕ открытые пункты семьи — и ручные, и menu-bound (полная очистка)."""
    items = await repositories.get_open_shopping_items(session, family_id=family_id)
    for item in items:
        await repositories.mark_shopping_item_bought(session, item.id, bought=True)
    return len(items)
```

`bot/keyboards.py::kb_shopping_list` — после кнопки «Добавить» при непустом items:

```python
    if items:
        b.button(text=f"{emoji.CANCEL} Очистить все", callback_data="shop:clear")
```

и:

```python
def kb_shop_clear_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Да, очистить", callback_data="shop:clear:yes")
    b.button(text=f"{emoji.CANCEL} Нет", callback_data="shop:clear:no")
    b.adjust(2)
    return b.as_markup()
```

- [ ] **Step 3: Хендлеры `bot/handlers/shopping.py`**

ВНИМАНИЕ: регистрировать `shop:clear:yes`/`shop:clear:no` ДО `shop:clear` (aiogram F.data == точное совпадение — порядок не важен для exact-match, но `shop:clear` использовать exact `F.data == "shop:clear"`, чтобы не съедал yes/no):

```python
@router.callback_query(F.data == "shop:clear")
async def cb_clear(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "Закрыть все пункты списка? Это действие нельзя отменить.",
        reply_markup=kb_shop_clear_confirm(),
    )
    await cb.answer()


@router.callback_query(F.data == "shop:clear:yes")
async def cb_clear_yes(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    closed = await shopping_list.clear_all_open(db_session, family_id=family.id)
    await cb.message.edit_text(
        f"{emoji.DONE} Список очищен: закрыто пунктов — {closed}."
    )
    await cb.answer()


@router.callback_query(F.data == "shop:clear:no")
async def cb_clear_no(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    await cb.message.edit_text(
        f"<b>{emoji.SHOPPING} Список покупок</b>", reply_markup=kb_shopping_list(items)
    )
    await cb.answer()
```

(импорт `kb_shop_clear_confirm` дополнить.)

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/services/shopping_list.py bot/ tests/
git commit -m "feat(shopping): clear entire list with confirmation"
```

---

### Task 7: /settings-хвосты и тексты для внешних семей

**Files:**
- Modify: `bot/handlers/settings.py`, `bot/handlers/menu.py:44-66`, `tests/unit/test_scheduler.py`
- Test: `tests/unit/test_settings_handlers.py`, `tests/unit/test_menu_handlers.py`

**Interfaces:**
- Produces: не-админ на `set:*` получает alert (не спиннер); `set:digest:` принимает только on/off; empty-тексты /menu и /today не упоминают JSON: при `planning_enabled` — зовут /plan (админам) или говорят «попросите администратора спланировать», при выключенном — «меню загружает администратор»; DST-тест `families_due`.

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_settings_handlers.py`:

```python
async def test_non_admin_set_callback_gets_alert():
    cb = AsyncMock()
    cb.data = "set:hour:9"
    await settings_handler.on_set_denied(cb)
    assert cb.answer.await_args.kwargs.get("show_alert") is True


async def test_garbage_digest_suffix_alerts(monkeypatch):
    called = False

    async def fake_update(*a, **kw):
        nonlocal called
        called = True

    monkeypatch.setattr(settings_handler, "update_digest_settings", fake_update)
    cb = AsyncMock()
    cb.data = "set:digest:whatever"
    await settings_handler.on_toggle_digest(cb, _family(), db_session=None)
    assert called is False
    assert cb.answer.await_args.kwargs.get("show_alert") is True
```

В `tests/unit/test_menu_handlers.py`:

```python
async def test_cmd_menu_empty_no_json_mention(monkeypatch):
    async def no_meals(*a, **kw):
        return []

    monkeypatch.setattr(menu_handler.repositories, "get_future_meals", no_meals)
    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    message = AsyncMock()
    await menu_handler.cmd_menu(message, SimpleNamespace(id=1), db_session=None)
    text = message.answer.await_args.args[0]
    assert "JSON" not in text and "/plan" in text
```

(аналогичный тест для cmd_today; и вариант planning_enabled=False → «администратор», без «/plan».)

В `tests/unit/test_scheduler.py` — DST:

```python
def test_due_across_dst_transition():
    # Europe/Berlin: зимой UTC+1 (9:00 = 08:00 UTC), летом UTC+2 (9:00 = 07:00 UTC)
    fam = [_family(1, tz="Europe/Berlin", hour=9)]
    winter = datetime(2026, 1, 15, 8, 5, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 7, 5, tzinfo=UTC)
    assert families_due(fam, now=winter, last_sent={}) == fam
    assert families_due(fam, now=summer, last_sent={}) == fam
```

Run: → FAIL.

- [ ] **Step 2: Реализация**

`bot/handlers/settings.py`:
- роутерный фильтр callback'ов сменить на `router.callback_query.filter(HasFamily())`;
- на хендлеры `on_toggle_digest` и `on_set_hour` навесить `IsAdmin()` в декораторы: `@router.callback_query(F.data.startswith("set:digest:"), IsAdmin())` и `@router.callback_query(F.data.startswith("set:hour:"), IsAdmin())`;
- в `on_toggle_digest` — строгий суффикс:

```python
    suffix = cb.data.split(":")[-1]
    if suffix not in {"on", "off"}:
        await cb.answer("Недоступное значение", show_alert=True)
        return
    enabled = suffix == "on"
```

- В КОНЦЕ файла — catch-all для не-админов (и любых прочих set:*):

```python
@router.callback_query(F.data.startswith("set:"))
async def on_set_denied(cb: CallbackQuery) -> None:
    await cb.answer("Настройки меняет администратор семьи", show_alert=True)
```

`bot/handlers/menu.py` — empty-тексты (импорт `from config import get_settings`):

```python
def _empty_menu_text() -> str:
    if get_settings().planning_enabled:
        return "Меню пока нет. Спланировать: /plan (доступно администратору семьи)."
    return "Меню пока нет — его загружает администратор семьи."
```

`cmd_menu`: `await message.answer(_empty_menu_text())`; `cmd_today`: `await message.answer(f"На сегодня ничего не запланировано. {_empty_menu_text()}")`.

- [ ] **Step 3: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add bot/ tests/
git commit -m "fix(ux): settings alerts for non-admins, beta-friendly empty texts, dst test"
```

---

### Task 8: Финализация

**Files:**
- Modify: `docs/superpowers/ROADMAP.md`
- Test: полный прогон + ручной smoke-чеклист

- [ ] **Step 1: ROADMAP**

- В «В работе» добавить строку «План этапа 4: [2026-07-22-stage4-beta-launch.md](plans/2026-07-22-stage4-beta-launch.md).»
- Секцию «Суперадмин-панель»: пометить «MVP сделан в этапе 4 (сводка+семьи+заявки); Позже: set_limit/отключение семьи (нужна таблица оверрайдов), broadcast, веб-дашборд».
- В «Биллинг»: пометить «сбор заявок сделан в этапе 4 (subscription_requests)».
- Удалить/пометить сделанные пункты «Доставка списка на выбор» и «Полная очистка списка».

- [ ] **Step 2: Полный прогон**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

- [ ] **Step 3: Ручной smoke (живой бот, PLANNING_ENABLED=true, SUPERADMIN_IDS=ваш id)**

1. Исчерпать триал (TRIAL_MENU_GEN_LIMIT=1) → отказ с кнопкой «Хочу подписку» → тап → «Записали», вам приходит уведомление; повторный тап — «уже в списке», без второго уведомления.
2. /admin — сводка с числами и списком семей; от обычного юзера /admin молчит.
3. Утвердить меню → две кнопки: «Показать текстом» дает текст без записи в /list; «В список /list» — пишет чек-лист; повторно «текстом» — рендер из БД (мгновенно).
4. /list → «Очистить все» → подтверждение → пусто; «Нет» — список возвращается.
5. PLANNING_ENABLED=false → все кнопки старых plan-сообщений отвечают «Планирование сейчас выключено».
6. /menu на пустом меню — текст без «JSON».
7. Не-админ тапает кнопки в /settings — alert, не спиннер.
8. Семья с исчерпанным триалом menu_gen не получает утреннее напоминание «Спланировать».

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/ROADMAP.md
git commit -m "docs(roadmap): stage 4 done — superadmin mvp, subscription requests"
```

---

## Вне скоупа этапа 4 (остается в роадмапе)

- Суперадмин: set_limit per family (таблица оверрайдов лимитов), отключение семьи, broadcast, веб-дашборд.
- Биллинг (Telegram Stars) — заявки уже собираются.
- Онбординг-апгрейд: стиль готовки, инфо-подсказки (решение пользователя 2026-07-22: не в этот этап).
- Лимиты в conversation.py — перед включением conversation_enabled (ROADMAP-заметка).
- Фидбек по блюдам, магазины, локализация, webhook, очередь задач.
