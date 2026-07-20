# Stage 1: Multitenant Core + Postgres — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Любой Telegram-юзер может через `/start` пройти онбординг, получить сгенерированный профиль семьи, пригласить членов семьи и управлять правами — без allowlist, на Postgres.

**Architecture:** Профиль семьи переезжает из статичного `core/prompts/base_context.md` в `families.profile_md` (БД); промпты собираются per-family. Allowlist-middleware заменяется на lenient-резолвер (family может быть `None`) + фильтр `HasFamily` на «рабочих» роутерах. Онбординг — FSM-визард (aiogram MemoryStorage), финал которого создаёт семью через `family_service.create_family`. Роли: `admin` / `member` + флаг `can_plan`.

**Tech Stack:** Python 3.12, aiogram 3, anthropic SDK, SQLAlchemy 2.0 async, Alembic, asyncpg (prod) / aiosqlite (dev+тесты), pytest + pytest-asyncio.

**Reference spec:** [docs/superpowers/specs/2026-07-20-multi-family-product-design.md](../specs/2026-07-20-multi-family-product-design.md)

## Global Constraints

- Python `>=3.12`, ruff `line-length = 100`, select `["E","F","I","W","UP","B","ASYNC"]`.
- Все видимые юзеру тексты — на русском; эмодзи только из `core/emoji.py`.
- pytest: `asyncio_mode = "auto"`; integration-тесты используют фикстуру `db_session` из `tests/conftest.py` (in-memory SQLite).
- После каждого таска: `ruff check . && pytest -q` — зелёные.
- Коммиты — conventional commits (`feat:`, `refactor:`, `chore:`...), каждый таск = минимум один коммит.
- Enum-колонки новых полей — `sa.Enum(..., native_enum=False)` или `String` (НЕ создавать новые native PG enum'ы: кросс-диалектные миграции).
- Спека, §6: лимиты триала в этом этапе НЕ реализуются (этап 3); но `llm_usage` создаётся и пишется уже сейчас.
- Дайджест-планировщик остаётся глобальным (BKK 9:00) — per-family время это этап 3.

---

## File Structure (итог этапа)

```
config.py                        -- minus allowlist_telegram_ids, vova_telegram_id
core/db.py                       -- + MemberRole, LlmUsage; Family/FamilyMember поля; MealSlot.breakfast; Store enum → str
core/llm.py                      -- build_system_blocks(task, profile_md=...)
core/repositories.py             -- + log_llm_usage, count_llm_operations
core/services/family_service.py  -- переписан: resolve/create/join/invite/rights
core/services/onboarding.py      -- NEW: ответы опроса → LLM → профиль+таймзона
core/services/shopping_list.py   -- build_added_notifications (без Вовы)
core/prompts/profile_generator.md -- NEW
bot/middlewares.py               -- без AllowlistMiddleware; lenient resolver
bot/filters.py                   -- NEW: HasFamily, IsAdmin
bot/fsm.py                       -- + Onboarding, ProfileEdit states
bot/keyboards.py                 -- + мультиселект, онбординг, /family клавиатуры
bot/handlers/start.py            -- /start: онбординг или join по deep-link
bot/handlers/onboarding.py       -- NEW: FSM-визард
bot/handlers/profile.py          -- NEW: /profile
bot/handlers/family.py           -- NEW: /family, /invite
bot/main.py                      -- роутеры, команды, без Allowlist
alembic/versions/0005_multitenant.py -- NEW
scripts/seed_own_family.py       -- NEW: сид своей семьи
tests/...                        -- unit + integration на всё выше
```

---

### Task 1: Схема БД — модели + миграция 0005

**Files:**
- Modify: `core/db.py`
- Modify: `core/services/shopping_list.py:51` (сигнатура `add_item`: `Store` → `str | None`)
- Create: `alembic/versions/0005_multitenant.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `MemberRole` (StrEnum: `admin|member`), `MealSlot.breakfast`, поля `Family.profile_md/timezone/digest_hour/digest_enabled/plan_slots/invite_code`, `FamilyMember.role/can_plan`, модель `LlmUsage(family_id, operation, tokens_in, tokens_out, created_at)`, `ShoppingItem.store: str | None`. Класс `Store` удалён.

- [ ] **Step 1: Проверить имена native-enum'ов в старых миграциях**

Run: `grep -n "sa.Enum\|name=" alembic/versions/0002_menus_meals.py alembic/versions/0003_shopping.py`
Expected: увидеть имена enum-типов для `MealSlot` (ожидаем `mealslot`) и `Store` (ожидаем `store`). Если имена другие — использовать фактические в Step 5.

- [ ] **Step 2: Написать падающие тесты моделей**

Добавить в `tests/unit/test_models.py`:

```python
from core.db import Family, FamilyMember, LlmUsage, MealSlot, MemberRole, ShoppingItem


def test_member_role_values():
    assert MemberRole.admin == "admin"
    assert MemberRole.member == "member"


def test_meal_slot_has_breakfast():
    assert MealSlot.breakfast == "breakfast"


def test_family_defaults():
    # column defaults применяются на flush; проверяем определения колонок
    cols = Family.__table__.c
    assert cols.timezone.default.arg == "UTC"
    assert cols.digest_hour.default.arg == 9
    assert cols.plan_slots.default.arg() == ["lunch", "dinner"]  # zero-arg lambda из модели


def test_shopping_item_store_is_plain_string():
    item = ShoppingItem(family_id=1, name="молоко", store="пятёрочка")
    assert item.store == "пятёрочка"


def test_llm_usage_model_columns():
    u = LlmUsage(family_id=1, operation="profile", tokens_in=100, tokens_out=200)
    assert u.operation == "profile"
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `pytest tests/unit/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'MemberRole'`

- [ ] **Step 4: Изменить `core/db.py`**

Удалить класс `Store` целиком. Добавить/изменить:

```python
class MealSlot(enum.StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"


class MemberRole(enum.StrEnum):
    admin = "admin"
    member = "member"
```

В `Family` добавить поля:

```python
    profile_md: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )
    digest_hour: Mapped[int] = mapped_column(
        Integer, default=9, server_default="9", nullable=False
    )
    digest_enabled: Mapped[bool] = mapped_column(
        default=True, server_default=sa_true(), nullable=False
    )
    plan_slots: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["lunch", "dinner"], nullable=False
    )
    invite_code: Mapped[str | None] = mapped_column(String(32), unique=True)
```

(импортировать `from sqlalchemy import true as sa_true, false as sa_false`)

В `FamilyMember` добавить:

```python
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, native_enum=False, length=10),
        default=MemberRole.member,
        server_default="member",
        nullable=False,
    )
    can_plan: Mapped[bool] = mapped_column(
        default=False, server_default=sa_false(), nullable=False
    )
```

В `ShoppingItem` заменить колонку `store`:

```python
    store: Mapped[str | None] = mapped_column(String(100))
```

Добавить модель:

```python
class LlmUsage(Base):
    """Учёт LLM-операций per family: триал-лимиты считаются по этой таблице."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # menu_gen|replace|recipe|profile
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[CreatedAt]
```

В `core/services/shopping_list.py` строка 51: заменить `store: Store = Store.other` на `store: str | None = None` и убрать импорт `Store`.

- [ ] **Step 5: Написать миграцию `alembic/versions/0005_multitenant.py`**

```python
"""multitenant: family profile & settings, roles, llm_usage, store→string, breakfast

Revision ID: 0005_multitenant
Revises: 0004_conversations
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_multitenant"
down_revision: Union[str, Sequence[str], None] = "0004_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("families") as b:
        b.add_column(sa.Column("profile_md", sa.Text(), nullable=True))
        b.add_column(
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC")
        )
        b.add_column(
            sa.Column("digest_hour", sa.Integer(), nullable=False, server_default="9")
        )
        b.add_column(
            sa.Column(
                "digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        b.add_column(
            sa.Column(
                "plan_slots",
                sa.JSON(),
                nullable=False,
                server_default='["lunch", "dinner"]',
            )
        )
        b.add_column(sa.Column("invite_code", sa.String(32), nullable=True))
        b.create_unique_constraint("uq_families_invite_code", ["invite_code"])

    with op.batch_alter_table("family_members") as b:
        b.add_column(
            sa.Column(
                "role",
                sa.Enum("admin", "member", name="memberrole", native_enum=False, length=10),
                nullable=False,
                server_default="member",
            )
        )
        b.add_column(
            sa.Column("can_plan", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # первый участник каждой существующей семьи становится админом
    op.execute(
        "UPDATE family_members SET role = 'admin' WHERE id IN "
        "(SELECT MIN(id) FROM family_members GROUP BY family_id)"
    )

    # store: native enum → просто строка
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "shopping_items",
            "store",
            type_=sa.String(100),
            postgresql_using="store::text",
            nullable=True,
            server_default=None,
        )
        op.execute("DROP TYPE IF EXISTS store")
        # breakfast в существующий native enum meal-слотов
        op.execute("ALTER TYPE mealslot ADD VALUE IF NOT EXISTS 'breakfast'")
    else:
        with op.batch_alter_table("shopping_items") as b:
            b.alter_column(
                "store",
                type_=sa.String(100),
                existing_type=sa.String(20),
                nullable=True,
                server_default=None,
            )
        # sqlite хранит enum как строку — breakfast не требует DDL

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_usage_family_op", "llm_usage", ["family_id", "operation"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_family_op")
    op.drop_table("llm_usage")
    with op.batch_alter_table("family_members") as b:
        b.drop_column("can_plan")
        b.drop_column("role")
    with op.batch_alter_table("families") as b:
        b.drop_constraint("uq_families_invite_code", type_="unique")
        b.drop_column("invite_code")
        b.drop_column("plan_slots")
        b.drop_column("digest_enabled")
        b.drop_column("digest_hour")
        b.drop_column("timezone")
        b.drop_column("profile_md")
```

Если имена enum'ов из Step 1 отличаются от `mealslot`/`store` — подставить фактические.

- [ ] **Step 6: Тесты и миграция на SQLite**

Run: `pytest -q && rm -f /tmp/mig_test.db && DB_URL=sqlite+aiosqlite:////tmp/mig_test.db alembic upgrade head`
Expected: тесты PASS; alembic доходит до `0005_multitenant` без ошибок. Возможные падения других тестов из-за удалённого `Store` — починить импорты в упавших файлах (заменить `Store.xxx` на строку `"xxx"`).

- [ ] **Step 7: Commit**

```bash
git add core/db.py core/services/shopping_list.py alembic/versions/0005_multitenant.py tests/
git commit -m "feat(db): multitenant schema — family profile/settings, roles, llm_usage"
```

---

### Task 2: family_service — мультитенантные операции

**Files:**
- Rewrite: `core/services/family_service.py`
- Modify: `core/exceptions.py` (добавить доменные ошибки)
- Test: `tests/integration/test_family_service.py` (переписать)

**Interfaces:**
- Consumes: модели Task 1 (`MemberRole`, поля Family/FamilyMember).
- Produces (используется тасками 3, 7, 9):
  - `resolve_member(session, telegram_user_id: int) -> tuple[Family, FamilyMember] | None`
  - `create_family(session, *, telegram_user_id: int, display_name: str | None, profile_md: str, timezone: str, plan_slots: list[str]) -> tuple[Family, FamilyMember]` — создатель получает `role=admin`, `can_plan=True`, семье выдаётся `invite_code`
  - `join_by_invite(session, *, invite_code: str, telegram_user_id: int, display_name: str | None) -> tuple[Family, FamilyMember]` — raises `InvalidInviteCode`, `AlreadyInFamily`
  - `regenerate_invite(session, *, family: Family) -> str`
  - `set_can_plan(session, *, member_id: int, value: bool) -> FamilyMember`
  - `transfer_admin(session, *, family_id: int, to_member_id: int) -> None`
  - `is_admin(member: FamilyMember) -> bool`
  - `has_plan_rights(member: FamilyMember) -> bool` (admin ИЛИ can_plan)
  - `get_admin(session, *, family_id: int) -> FamilyMember | None`
- Удаляются: `is_authorized`, `get_or_create_family` (их вызовы чинятся в Task 3 — до тех пор `bot/` не трогаем, тесты `bot/` могут быть красными только если импортируют удалённое; проверить и при необходимости заглушить импорт в Task 3).

- [ ] **Step 1: Написать падающие тесты**

Переписать `tests/integration/test_family_service.py`:

```python
import pytest

from core.exceptions import AlreadyInFamily, InvalidInviteCode
from core.services.family_service import (
    create_family,
    get_admin,
    has_plan_rights,
    is_admin,
    join_by_invite,
    regenerate_invite,
    resolve_member,
    set_can_plan,
    transfer_admin,
)


async def _make_family(db_session, tg_id=111):
    return await create_family(
        db_session,
        telegram_user_id=tg_id,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["lunch", "dinner"],
    )


async def test_create_family_sets_admin_and_invite(db_session):
    family, member = await _make_family(db_session)
    assert is_admin(member)
    assert has_plan_rights(member)
    assert family.invite_code
    assert family.profile_md == "# Профиль"
    assert family.plan_slots == ["lunch", "dinner"]


async def test_resolve_member_roundtrip(db_session):
    family, member = await _make_family(db_session)
    resolved = await resolve_member(db_session, 111)
    assert resolved is not None
    assert resolved[0].id == family.id
    assert await resolve_member(db_session, 999) is None


async def test_join_by_invite(db_session):
    family, _ = await _make_family(db_session)
    fam2, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    assert fam2.id == family.id
    assert not is_admin(joined)
    assert not has_plan_rights(joined)


async def test_join_invalid_code_raises(db_session):
    with pytest.raises(InvalidInviteCode):
        await join_by_invite(
            db_session, invite_code="nope", telegram_user_id=222, display_name=None
        )


async def test_join_twice_raises(db_session):
    family, _ = await _make_family(db_session)
    with pytest.raises(AlreadyInFamily):
        await join_by_invite(
            db_session, invite_code=family.invite_code, telegram_user_id=111, display_name=None
        )


async def test_set_can_plan_and_transfer_admin(db_session):
    family, admin = await _make_family(db_session)
    _, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await set_can_plan(db_session, member_id=joined.id, value=True)
    assert has_plan_rights(joined)

    await transfer_admin(db_session, family_id=family.id, to_member_id=joined.id)
    current_admin = await get_admin(db_session, family_id=family.id)
    assert current_admin.id == joined.id
    assert not is_admin(admin)


async def test_regenerate_invite_changes_code(db_session):
    family, _ = await _make_family(db_session)
    old = family.invite_code
    new = await regenerate_invite(db_session, family=family)
    assert new != old and family.invite_code == new
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/integration/test_family_service.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Добавить ошибки в `core/exceptions.py`**

```python
class FamilyError(Exception):
    """Base for family-domain errors."""


class InvalidInviteCode(FamilyError):
    pass


class AlreadyInFamily(FamilyError):
    pass
```

- [ ] **Step 4: Переписать `core/services/family_service.py`**

```python
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family, FamilyMember, MemberRole
from core.exceptions import AlreadyInFamily, InvalidInviteCode


def _new_invite_code() -> str:
    return secrets.token_urlsafe(9)


def is_admin(member: FamilyMember) -> bool:
    return member.role == MemberRole.admin


def has_plan_rights(member: FamilyMember) -> bool:
    return is_admin(member) or member.can_plan


async def resolve_member(
    session: AsyncSession, telegram_user_id: int
) -> tuple[Family, FamilyMember] | None:
    member = (
        await session.execute(
            select(FamilyMember).where(FamilyMember.telegram_user_id == telegram_user_id)
        )
    ).scalar_one_or_none()
    if member is None:
        return None
    family = (
        await session.execute(select(Family).where(Family.id == member.family_id))
    ).scalar_one()
    return family, member


async def create_family(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str | None,
    profile_md: str,
    timezone: str,
    plan_slots: list[str],
) -> tuple[Family, FamilyMember]:
    family = Family(
        name=display_name or "Семья",
        profile_md=profile_md,
        timezone=timezone,
        plan_slots=plan_slots,
        invite_code=_new_invite_code(),
    )
    session.add(family)
    await session.flush()
    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        role=MemberRole.admin,
        can_plan=True,
    )
    session.add(member)
    await session.flush()
    return family, member


async def join_by_invite(
    session: AsyncSession,
    *,
    invite_code: str,
    telegram_user_id: int,
    display_name: str | None,
) -> tuple[Family, FamilyMember]:
    if await resolve_member(session, telegram_user_id) is not None:
        raise AlreadyInFamily
    family = (
        await session.execute(select(Family).where(Family.invite_code == invite_code))
    ).scalar_one_or_none()
    if family is None:
        raise InvalidInviteCode
    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
    )
    session.add(member)
    await session.flush()
    return family, member


async def regenerate_invite(session: AsyncSession, *, family: Family) -> str:
    family.invite_code = _new_invite_code()
    await session.flush()
    return family.invite_code


async def set_can_plan(
    session: AsyncSession, *, member_id: int, value: bool
) -> FamilyMember:
    member = (
        await session.execute(select(FamilyMember).where(FamilyMember.id == member_id))
    ).scalar_one()
    member.can_plan = value
    await session.flush()
    return member


async def get_admin(session: AsyncSession, *, family_id: int) -> FamilyMember | None:
    return (
        await session.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.role == MemberRole.admin,
            )
        )
    ).scalar_one_or_none()


async def transfer_admin(
    session: AsyncSession, *, family_id: int, to_member_id: int
) -> None:
    current = await get_admin(session, family_id=family_id)
    if current is not None:
        current.role = MemberRole.member
    new_admin = (
        await session.execute(select(FamilyMember).where(FamilyMember.id == to_member_id))
    ).scalar_one()
    new_admin.role = MemberRole.admin
    new_admin.can_plan = True
    await session.flush()
```

- [ ] **Step 5: Тесты зелёные (family_service)**

Run: `pytest tests/integration/test_family_service.py -q`
Expected: PASS. `pytest -q` целиком может падать на `bot/middlewares.py` (импортирует удалённые функции) — это чинится в Task 3; если падает сбор тестов, в этом коммите допустимо временно оставить в family_service алиасы-заглушки НЕЛЬЗЯ — вместо этого сразу переходить к Task 3 и коммитить оба таска подряд, если полный прогон требует.

- [ ] **Step 6: Commit**

```bash
git add core/services/family_service.py core/exceptions.py tests/integration/test_family_service.py
git commit -m "feat(family): multitenant family service — create/join/invite/roles"
```

---

### Task 3: Доступ без allowlist — middleware, фильтры, конфиг

**Files:**
- Modify: `bot/middlewares.py`, `bot/main.py`, `config.py`, `.env.example`, `tests/conftest.py`, `tests/unit/test_config.py`
- Create: `bot/filters.py`
- Modify: `bot/handlers/menu.py`, `bot/handlers/shopping.py`, `bot/handlers/load.py`, `bot/handlers/freetext.py` (фильтр на роутер)
- Test: `tests/unit/test_filters.py`

**Interfaces:**
- Consumes: `resolve_member` из Task 2.
- Produces: `HasFamily` (aiogram Filter; `data["family"]` может быть `None`), `IsAdmin` (Filter поверх `family_member`). Мидлварь кладёт в data: `family: Family | None`, `family_member: FamilyMember | None`, `db_session`.
- ВНИМАНИЕ: `vova_telegram_id` из config НЕ удалять в этом таске (используется shopping-уведомлениями до Task 9). Удаляется только `allowlist_telegram_ids`.

- [ ] **Step 1: Падающий тест фильтров**

Создать `tests/unit/test_filters.py`:

```python
from types import SimpleNamespace

from bot.filters import HasFamily, IsAdmin
from core.db import FamilyMember, MemberRole


async def test_has_family_false_when_none():
    assert await HasFamily()(SimpleNamespace(), family=None) is False


async def test_has_family_true():
    assert await HasFamily()(SimpleNamespace(), family=SimpleNamespace(id=1)) is True


async def test_is_admin():
    admin = FamilyMember(family_id=1, telegram_user_id=1, role=MemberRole.admin)
    member = FamilyMember(family_id=1, telegram_user_id=2, role=MemberRole.member)
    assert await IsAdmin()(SimpleNamespace(), family_member=admin) is True
    assert await IsAdmin()(SimpleNamespace(), family_member=member) is False
```

Run: `pytest tests/unit/test_filters.py -q` → FAIL (нет модуля).

- [ ] **Step 2: Создать `bot/filters.py`**

```python
from typing import Any

from aiogram.filters import Filter
from aiogram.types import TelegramObject

from core.services.family_service import is_admin


class HasFamily(Filter):
    """Пропускает апдейт только если юзер уже состоит в семье."""

    async def __call__(self, event: TelegramObject, family: Any = None, **_: Any) -> bool:
        return family is not None


class IsAdmin(Filter):
    async def __call__(
        self, event: TelegramObject, family_member: Any = None, **_: Any
    ) -> bool:
        return family_member is not None and is_admin(family_member)
```

- [ ] **Step 3: Переписать `bot/middlewares.py`**

Удалить `AllowlistMiddleware`. `FamilyResolverMiddleware`:

```python
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from core.db import session_scope
from core.services.family_service import resolve_member


class FamilyResolverMiddleware(BaseMiddleware):
    """Резолвит семью юзера. family/family_member могут быть None —
    доступ к рабочим командам отсекает фильтр HasFamily."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        async with session_scope() as session:
            resolved = await resolve_member(session, user.id)
            family, member = resolved if resolved else (None, None)
            data["family"] = family
            data["family_member"] = member
            data["db_session"] = session
            return await handler(event, data)
```

- [ ] **Step 4: Навесить фильтры на рабочие роутеры**

В каждом из `bot/handlers/menu.py`, `bot/handlers/shopping.py`, `bot/handlers/load.py`, `bot/handlers/freetext.py` сразу после создания `router = Router()` добавить:

```python
from bot.filters import HasFamily

router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())
```

- [ ] **Step 5: Конфиг и main**

`config.py`: удалить поле `allowlist_telegram_ids` и валидатор `_parse_ids` (импорты `Annotated`, `NoDecode`, `field_validator` — почистить, если больше не нужны). `vova_telegram_id` оставить.
`bot/main.py`: удалить импорт и обе регистрации `AllowlistMiddleware`.
`tests/conftest.py`: удалить строку `os.environ.setdefault("ALLOWLIST_TELEGRAM_IDS", ...)`.
`tests/unit/test_config.py`: удалить/заменить тесты про allowlist (оставить smoke: `get_settings()` создаётся с BOT_TOKEN/ANTHROPIC_API_KEY из env).
`.env.example`: удалить строку `ALLOWLIST_TELEGRAM_IDS=...`.

- [ ] **Step 6: Полный прогон**

Run: `ruff check . && pytest -q`
Expected: PASS (включая ранее красные импорты из Task 2).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(bot): drop allowlist — lenient family resolver + HasFamily filter"
```

---

### Task 4: Per-family сборка промпта

**Files:**
- Modify: `core/llm.py:81-94`, `core/services/recipe_service.py`, `core/services/dish_replacer.py`, `core/services/conversation.py`, их вызовы в `bot/handlers/` и `core/tools.py`
- Test: `tests/unit/test_llm_parsing.py` (добавить тест сборки блоков)

**Interfaces:**
- Produces: `build_system_blocks(task_prompt_name: str, *, profile_md: str) -> list[dict]` — блок задачи (cached) + блок «Контекст семьи» из profile_md (cached). Сервисы получают новый обязательный kwarg `profile_md: str`:
  - `recipe_service.get_recipe(session, *, meal_id, profile_md)`
  - `dish_replacer.replace_meal(..., profile_md)`
  - `conversation.handle_message(..., profile_md)`
- `core/prompts/base_context.md` больше НЕ загружается в рантайме (остаётся как сид для скрипта в Task 10).

- [ ] **Step 1: Падающий тест**

Добавить в `tests/unit/test_llm_parsing.py`:

```python
from core.llm import build_system_blocks


def test_build_system_blocks_uses_profile():
    blocks = build_system_blocks("recipe", profile_md="# Семья\nБез лука.")
    assert len(blocks) == 2
    assert "Без лука" in blocks[1]["text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


def test_build_system_blocks_empty_profile_placeholder():
    blocks = build_system_blocks("recipe", profile_md="")
    assert "не заполнен" in blocks[1]["text"]
```

Run: `pytest tests/unit/test_llm_parsing.py -q` → FAIL (TypeError: unexpected keyword).

- [ ] **Step 2: Переписать `build_system_blocks` в `core/llm.py`**

```python
def build_system_blocks(task_prompt_name: str, *, profile_md: str) -> list[dict]:
    """Task prompt (cached) + per-family profile (cached)."""
    profile_text = profile_md.strip() or "(профиль семьи не заполнен)"
    return [
        {
            "type": "text",
            "text": load_prompt(task_prompt_name),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"# Контекст семьи\n\n{profile_text}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
```

- [ ] **Step 3: Обновить сервисы и вызовы**

Run: `grep -rn "build_system_blocks\|get_recipe\|replace_meal\|handle_message" core bot --include="*.py" | grep -v __pycache__`

В каждом из трёх сервисов: добавить обязательный kwarg `profile_md: str` в публичную функцию и передать его в `build_system_blocks(...)`. В местах вызова из `bot/handlers/*` и `core/tools.py` передать `profile_md=family.profile_md or ""` (объект `family` уже есть в data хендлеров; в `core/tools.py` — прокинуть через контекст диспетчера тем же путём, каким туда попадает session/family_id).

- [ ] **Step 4: Обновить интеграционные тесты сервисов**

В `tests/integration/test_recipe_service.py`, `test_dish_replacer.py`, `test_conversation.py` добавить `profile_md="тестовый профиль"` в вызовы. Прогнать: `pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(llm): assemble prompts from per-family profile_md"
```

---

### Task 5: Учёт LLM-операций (llm_usage)

**Files:**
- Modify: `core/repositories.py`
- Test: `tests/integration/test_llm_usage.py` (новый)

**Interfaces:**
- Consumes: модель `LlmUsage` из Task 1.
- Produces (используется Task 7 и этапом 3):
  - `log_llm_usage(session, *, family_id: int, operation: str, tokens_in: int, tokens_out: int) -> None`
  - `count_llm_operations(session, *, family_id: int, operation: str) -> int`

- [ ] **Step 1: Падающий тест**

Создать `tests/integration/test_llm_usage.py`:

```python
from core.db import Family
from core.repositories import count_llm_operations, log_llm_usage


async def test_log_and_count(db_session):
    family = Family(name="f")
    db_session.add(family)
    await db_session.flush()

    assert await count_llm_operations(db_session, family_id=family.id, operation="profile") == 0
    await log_llm_usage(
        db_session, family_id=family.id, operation="profile", tokens_in=10, tokens_out=20
    )
    await log_llm_usage(
        db_session, family_id=family.id, operation="menu_gen", tokens_in=1, tokens_out=2
    )
    assert await count_llm_operations(db_session, family_id=family.id, operation="profile") == 1
    assert await count_llm_operations(db_session, family_id=family.id, operation="menu_gen") == 1
```

Run: `pytest tests/integration/test_llm_usage.py -q` → FAIL.

- [ ] **Step 2: Реализация в `core/repositories.py`**

```python
from core.db import LlmUsage  # добавить к существующим импортам


async def log_llm_usage(
    session: AsyncSession,
    *,
    family_id: int,
    operation: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    session.add(
        LlmUsage(
            family_id=family_id,
            operation=operation,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    await session.flush()


async def count_llm_operations(
    session: AsyncSession, *, family_id: int, operation: str
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(LlmUsage)
        .where(LlmUsage.family_id == family_id, LlmUsage.operation == operation)
    )
    return int(result.scalar_one())
```

(`func` уже импортируется в db.py; в repositories добавить `from sqlalchemy import func` при отсутствии.)

- [ ] **Step 3: Прогон + Commit**

Run: `pytest tests/integration/test_llm_usage.py -q` → PASS

```bash
git add core/repositories.py tests/integration/test_llm_usage.py
git commit -m "feat(usage): llm_usage logging and per-operation counters"
```

---

### Task 6: Онбординг-сервис — ответы → LLM → профиль + таймзона

**Files:**
- Create: `core/services/onboarding.py`, `core/prompts/profile_generator.md`
- Test: `tests/integration/test_onboarding.py`

**Interfaces:**
- Consumes: `LLMClient`, `parse_json_response`, `load_prompt` из `core/llm.py`; `LLMInvalidResponse` из `core/exceptions.py`.
- Produces (используется Task 7):
  - `OnboardingAnswers` (dataclass: `household: str`, `slots: list[str]`, `restrictions: list[str]`, `cook_minutes: int`, `preferences: list[str]`, `extra: str | None`, `city: str | None`)
  - `ProfileResult` (dataclass: `profile_md: str`, `timezone: str`, `tokens_in: int`, `tokens_out: int`)
  - `answers_to_prompt(answers: OnboardingAnswers) -> str`
  - `generate_profile(llm: LLMClient, answers: OnboardingAnswers) -> ProfileResult` — 1 автоматический retry при невалидном JSON, затем `LLMInvalidResponse` наружу.

- [ ] **Step 1: Написать промпт `core/prompts/profile_generator.md`**

```markdown
# Задача: профиль семьи

Ты — помощник сервиса планирования семейного меню. По ответам из опроса составь
текстовый «профиль семьи» на русском языке в markdown. Этот профиль дальше
используется как контекст при генерации меню, рецептов и списков покупок.

Структура профиля (заголовки — как ниже, разделы без данных пропускай):

## Состав семьи
## Приёмы пищи для планирования
## Ограничения по продуктам
## Правила планирования
## Предпочтения

Правила:
- Пиши кратко, списками, без воды. Не выдумывай факты, которых нет в ответах.
- В «Правила планирования» включи лимит активной готовки из ответов.
- Определи таймзону IANA по названию города (например «Бангкок» → Asia/Bangkok).
  Если город не указан или не распознан — используй "UTC".

Ответ верни СТРОГО одним JSON-объектом без пояснений:

{"profile_md": "<markdown-текст профиля>", "timezone": "<IANA-таймзона>"}
```

- [ ] **Step 2: Падающие тесты (LLM мокается фейк-клиентом)**

Создать `tests/integration/test_onboarding.py`:

```python
import json

import pytest

from core.exceptions import LLMInvalidResponse
from core.llm import LLMResponse
from core.services.onboarding import (
    OnboardingAnswers,
    answers_to_prompt,
    generate_profile,
)

ANSWERS = OnboardingAnswers(
    household="2 взрослых",
    slots=["lunch", "dinner"],
    restrictions=["без лука", "без глютена"],
    cook_minutes=40,
    preferences=["курица", "рыба"],
    extra="не любим кинзу",
    city="Бангкок",
)


class FakeLLM:
    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(text=self._texts.pop(0), tokens_in=10, tokens_out=20)


def test_answers_to_prompt_contains_all_answers():
    prompt = answers_to_prompt(ANSWERS)
    for chunk in ("2 взрослых", "без лука", "40", "курица", "кинзу", "Бангкок"):
        assert chunk in prompt


async def test_generate_profile_happy_path():
    ok = json.dumps({"profile_md": "# Профиль", "timezone": "Asia/Bangkok"})
    llm = FakeLLM([ok])
    result = await generate_profile(llm, ANSWERS)
    assert result.profile_md == "# Профиль"
    assert result.timezone == "Asia/Bangkok"
    assert result.tokens_in == 10


async def test_generate_profile_retries_once_on_bad_json():
    ok = json.dumps({"profile_md": "p", "timezone": "UTC"})
    llm = FakeLLM(["не json", ok])
    result = await generate_profile(llm, ANSWERS)
    assert llm.calls == 2
    assert result.profile_md == "p"


async def test_generate_profile_fails_after_two_bad():
    llm = FakeLLM(["мусор", "мусор"])
    with pytest.raises(LLMInvalidResponse):
        await generate_profile(llm, ANSWERS)
```

Run: `pytest tests/integration/test_onboarding.py -q` → FAIL.

- [ ] **Step 3: Реализовать `core/services/onboarding.py`**

```python
"""Онбординг: превращает ответы опроса в текст профиля семьи через LLM."""
from dataclasses import dataclass

from core.exceptions import LLMInvalidResponse
from core.llm import LLMClient, load_prompt, parse_json_response

SLOT_LABELS = {"breakfast": "завтрак", "lunch": "обед", "dinner": "ужин"}


@dataclass
class OnboardingAnswers:
    household: str
    slots: list[str]
    restrictions: list[str]
    cook_minutes: int
    preferences: list[str]
    extra: str | None
    city: str | None


@dataclass
class ProfileResult:
    profile_md: str
    timezone: str
    tokens_in: int
    tokens_out: int


def answers_to_prompt(answers: OnboardingAnswers) -> str:
    slots = ", ".join(SLOT_LABELS.get(s, s) for s in answers.slots)
    lines = [
        f"Состав семьи: {answers.household}",
        f"Планируемые приёмы пищи: {slots}",
        f"Ограничения: {', '.join(answers.restrictions) or 'нет'}",
        f"Лимит активной готовки: {answers.cook_minutes} минут",
        f"Предпочтения: {', '.join(answers.preferences) or 'нет'}",
    ]
    if answers.extra:
        lines.append(f"Дополнительно: {answers.extra}")
    if answers.city:
        lines.append(f"Город: {answers.city}")
    return "\n".join(lines)


async def generate_profile(llm: LLMClient, answers: OnboardingAnswers) -> ProfileResult:
    system_blocks = [{"type": "text", "text": load_prompt("profile_generator")}]
    messages = [{"role": "user", "content": answers_to_prompt(answers)}]
    tokens_in = tokens_out = 0
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry
        resp = await llm.chat(system_blocks=system_blocks, messages=messages)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            data = parse_json_response(resp.text)
            return ProfileResult(
                profile_md=str(data["profile_md"]),
                timezone=str(data.get("timezone") or "UTC"),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except (LLMInvalidResponse, KeyError) as e:
            last_error = e if isinstance(e, LLMInvalidResponse) else LLMInvalidResponse(str(e))
    raise last_error
```

- [ ] **Step 4: Прогон + Commit**

Run: `pytest tests/integration/test_onboarding.py -q` → PASS

```bash
git add core/services/onboarding.py core/prompts/profile_generator.md tests/integration/test_onboarding.py
git commit -m "feat(onboarding): survey answers → LLM-generated family profile"
```

---

### Task 7: Онбординг-визард в боте + новый /start

**Files:**
- Modify: `bot/fsm.py`, `bot/keyboards.py`, `bot/handlers/start.py`, `bot/main.py`
- Create: `bot/handlers/onboarding.py`
- Test: `tests/unit/test_onboarding_keyboards.py`

**Interfaces:**
- Consumes: `OnboardingAnswers`, `generate_profile` (Task 6); `create_family` (Task 2); `log_llm_usage` (Task 5); `HasFamily` (Task 3).
- Produces: роутер `bot.handlers.onboarding.router` (регистрируется в main ПЕРВЫМ, до menu/shopping); функции клавиатур `kb_multiselect`, `kb_household`, `kb_cook_minutes`, `kb_profile_confirm`, `kb_skip`. Callback-префикс визарда: `onb:`.
- FSM: `Onboarding` StatesGroup: `household, slots, restrictions, cook_minutes, preferences, extra, city, confirm`.
- Deep-link `inv_<код>` обрабатывается в Task 9; здесь `/start` без аргументов.

- [ ] **Step 1: Падающий тест клавиатур**

Создать `tests/unit/test_onboarding_keyboards.py`:

```python
from bot.keyboards import kb_household, kb_multiselect, kb_profile_confirm

SLOT_OPTIONS = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}


def test_multiselect_marks_selected():
    kb = kb_multiselect("onb:slot", SLOT_OPTIONS, selected={"lunch"})
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Обед" in t and "✅" in t for t in texts)
    assert any("Завтрак" in t and "✅" not in t for t in texts)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "onb:slot:lunch" in datas
    assert "onb:slot:done" in datas


def test_household_and_confirm_keyboards():
    kb = kb_household()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "onb:hh:2" in datas
    kb2 = kb_profile_confirm()
    datas2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert "onb:profile:ok" in datas2 and "onb:profile:edit" in datas2
```

Run: `pytest tests/unit/test_onboarding_keyboards.py -q` → FAIL.

- [ ] **Step 2: Клавиатуры в `bot/keyboards.py`**

```python
def kb_multiselect(
    prefix: str, options: dict[str, str], selected: set[str]
) -> InlineKeyboardMarkup:
    """Тогл-кнопки: prefix:<key>; кнопка завершения: prefix:done."""
    b = InlineKeyboardBuilder()
    for key, label in options.items():
        mark = f"{emoji.DONE} " if key in selected else ""
        b.button(text=f"{mark}{label}", callback_data=f"{prefix}:{key}")
    b.button(text="Готово ➡️", callback_data=f"{prefix}:done")
    b.adjust(1)
    return b.as_markup()


def kb_household() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in ("1", "2", "3", "4+"):
        b.button(text=n, callback_data=f"onb:hh:{n}")
    b.adjust(4)
    return b.as_markup()


def kb_cook_minutes() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in ("20", "40", "60"):
        b.button(text=f"{m} мин", callback_data=f"onb:cook:{m}")
    b.adjust(3)
    return b.as_markup()


def kb_skip(callback: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Пропустить ➡️", callback_data=callback)
    return b.as_markup()


def kb_profile_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Всё верно", callback_data="onb:profile:ok")
    b.button(text="✏️ Редактировать", callback_data="onb:profile:edit")
    b.adjust(2)
    return b.as_markup()
```

Run: `pytest tests/unit/test_onboarding_keyboards.py -q` → PASS.

- [ ] **Step 3: FSM-состояния в `bot/fsm.py`**

```python
class Onboarding(StatesGroup):
    household = State()
    slots = State()
    restrictions = State()
    cook_minutes = State()
    preferences = State()
    extra = State()
    city = State()
    confirm = State()
    edit_profile = State()
```

- [ ] **Step 4: Хендлеры `bot/handlers/onboarding.py`**

Полный визард. Опции мультиселектов — модульные константы; выбранное хранится в FSM data.

```python
"""Онбординг нового юзера: опрос → генерация профиля → создание семьи."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger

from bot.fsm import Onboarding
from bot.keyboards import (
    kb_cook_minutes,
    kb_household,
    kb_multiselect,
    kb_profile_confirm,
    kb_skip,
)
from core import emoji
from core.exceptions import LLMInvalidResponse
from core.repositories import log_llm_usage
from core.services.family_service import create_family
from core.services.onboarding import OnboardingAnswers, generate_profile

router = Router()

SLOT_OPTIONS = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}
RESTRICTION_OPTIONS = {
    "lactose": "Без лактозы",
    "gluten": "Без глютена",
    "onion_garlic": "Без лука/чеснока",
    "nuts": "Без орехов",
    "pork": "Без свинины",
}
PREFERENCE_OPTIONS = {
    "chicken": "Курица",
    "fish": "Рыба/морепродукты",
    "beef": "Говядина",
    "pork": "Свинина",
    "veg": "Больше овощей",
    "euro": "Европейская кухня",
    "asia": "Азиатская кухня",
}


async def start_onboarding(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Onboarding.household)
    await message.answer(
        "Настроим бота под вашу семью — 6 коротких вопросов.\n\n"
        "1/6. Сколько человек в семье?",
        reply_markup=kb_household(),
    )


@router.callback_query(Onboarding.household, F.data.startswith("onb:hh:"))
async def on_household(cb: CallbackQuery, state: FSMContext) -> None:
    count = cb.data.split(":")[-1]
    await state.update_data(household=f"{count} чел.", slots=[])
    await state.set_state(Onboarding.slots)
    await cb.message.edit_text(
        "2/6. Какие приёмы пищи планировать?",
        reply_markup=kb_multiselect("onb:slot", SLOT_OPTIONS, set()),
    )
    await cb.answer()


async def _toggle(cb: CallbackQuery, state: FSMContext, key: str, field: str,
                  prefix: str, options: dict[str, str]) -> None:
    data = await state.get_data()
    selected: list[str] = data.get(field, [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(**{field: selected})
    await cb.message.edit_reply_markup(
        reply_markup=kb_multiselect(prefix, options, set(selected))
    )
    await cb.answer()


@router.callback_query(Onboarding.slots, F.data.startswith("onb:slot:"))
async def on_slot(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "slots", "onb:slot", SLOT_OPTIONS)
        return
    data = await state.get_data()
    if not data.get("slots"):
        await cb.answer("Выберите хотя бы один приём пищи", show_alert=True)
        return
    await state.update_data(restrictions=[])
    await state.set_state(Onboarding.restrictions)
    await cb.message.edit_text(
        "3/6. Аллергии и исключения? Отметьте кнопками и/или напишите своё сообщением.",
        reply_markup=kb_multiselect("onb:restr", RESTRICTION_OPTIONS, set()),
    )
    await cb.answer()


@router.callback_query(Onboarding.restrictions, F.data.startswith("onb:restr:"))
async def on_restriction(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "restrictions", "onb:restr", RESTRICTION_OPTIONS)
        return
    await state.set_state(Onboarding.cook_minutes)
    await cb.message.edit_text(
        "4/6. Сколько времени готовы тратить на активную готовку одного блюда?",
        reply_markup=kb_cook_minutes(),
    )
    await cb.answer()


@router.message(Onboarding.restrictions, F.text)
async def on_restriction_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    restrictions = data.get("restrictions", [])
    restrictions.append(message.text.strip())
    await state.update_data(restrictions=restrictions)
    await message.answer(
        f"Записал: {message.text.strip()}. Отметьте ещё или жмите «Готово» выше."
    )


@router.callback_query(Onboarding.cook_minutes, F.data.startswith("onb:cook:"))
async def on_cook(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cook_minutes=int(cb.data.split(":")[-1]), preferences=[])
    await state.set_state(Onboarding.preferences)
    await cb.message.edit_text(
        "5/6. Что любите? Отметьте кнопками и/или напишите своё сообщением.",
        reply_markup=kb_multiselect("onb:pref", PREFERENCE_OPTIONS, set()),
    )
    await cb.answer()


@router.callback_query(Onboarding.preferences, F.data.startswith("onb:pref:"))
async def on_pref(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":")[-1]
    if key != "done":
        await _toggle(cb, state, key, "preferences", "onb:pref", PREFERENCE_OPTIONS)
        return
    await state.set_state(Onboarding.extra)
    await cb.message.edit_text(
        "6/6. Что ещё важно знать? (техника, стиль питания, нелюбимые продукты...)\n"
        "Напишите сообщением или пропустите.",
        reply_markup=kb_skip("onb:extra:skip"),
    )
    await cb.answer()


@router.message(Onboarding.preferences, F.text)
async def on_pref_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prefs = data.get("preferences", [])
    prefs.append(message.text.strip())
    await state.update_data(preferences=prefs)
    await message.answer(
        f"Записал: {message.text.strip()}. Отметьте ещё или жмите «Готово» выше."
    )


async def _ask_city(target_message: Message, state: FSMContext) -> None:
    await state.set_state(Onboarding.city)
    await target_message.answer(
        "И последнее: в каком городе живёте? (нужно для времени напоминаний)",
        reply_markup=kb_skip("onb:city:skip"),
    )


@router.message(Onboarding.extra, F.text)
async def on_extra_text(message: Message, state: FSMContext) -> None:
    await state.update_data(extra=message.text.strip())
    await _ask_city(message, state)


@router.callback_query(Onboarding.extra, F.data == "onb:extra:skip")
async def on_extra_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(extra=None)
    await _ask_city(cb.message, state)
    await cb.answer()


@router.message(Onboarding.city, F.text)
async def on_city_text(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip())
    await _generate_and_show(message, state)


@router.callback_query(Onboarding.city, F.data == "onb:city:skip")
async def on_city_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=None)
    await _generate_and_show(cb.message, state)
    await cb.answer()


def _labels(keys: list[str], options: dict[str, str]) -> list[str]:
    return [options.get(k, k) for k in keys]


async def _generate_and_show(message: Message, state: FSMContext) -> None:
    from core.services.onboarding import get_llm_client  # локальный импорт для моков

    data = await state.get_data()
    answers = OnboardingAnswers(
        household=data["household"],
        slots=data["slots"],
        restrictions=_labels(data.get("restrictions", []), RESTRICTION_OPTIONS),
        cook_minutes=data.get("cook_minutes", 40),
        preferences=_labels(data.get("preferences", []), PREFERENCE_OPTIONS),
        extra=data.get("extra"),
        city=data.get("city"),
    )
    placeholder = await message.answer(f"{emoji.WAIT} Составляю профиль семьи...")
    try:
        result = await generate_profile(get_llm_client(), answers)
    except LLMInvalidResponse:
        logger.exception("onboarding: profile generation failed")
        await placeholder.edit_text(
            "Не получилось составить профиль. Попробуйте ещё раз: /start"
        )
        await state.clear()
        return
    await state.update_data(
        profile_md=result.profile_md,
        timezone=result.timezone,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    await state.set_state(Onboarding.confirm)
    await placeholder.edit_text(
        f"Вот профиль вашей семьи:\n\n{result.profile_md}\n\n"
        "Его всегда можно изменить командой /profile.",
        reply_markup=kb_profile_confirm(),
    )


@router.callback_query(Onboarding.confirm, F.data == "onb:profile:ok")
async def on_profile_ok(cb: CallbackQuery, state: FSMContext, db_session) -> None:
    data = await state.get_data()
    family, _member = await create_family(
        db_session,
        telegram_user_id=cb.from_user.id,
        display_name=cb.from_user.full_name,
        profile_md=data["profile_md"],
        timezone=data["timezone"],
        plan_slots=data["slots"],
    )
    await log_llm_usage(
        db_session,
        family_id=family.id,
        operation="profile",
        tokens_in=data.get("tokens_in", 0),
        tokens_out=data.get("tokens_out", 0),
    )
    await state.clear()
    await cb.message.edit_text(
        f"{emoji.DONE} Готово! Семья создана.\n\n"
        "Пригласить близких: /invite\n"
        "Профиль семьи: /profile\n"
        "Справка: /help"
    )
    await cb.answer()


@router.callback_query(Onboarding.confirm, F.data == "onb:profile:edit")
async def on_profile_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Onboarding.edit_profile)
    await cb.message.answer(
        "Пришлите новую версию профиля целиком (текущий текст выше — скопируйте и поправьте):",
        reply_markup=ForceReply(),
    )
    await cb.answer()


@router.message(Onboarding.edit_profile, F.text)
async def on_profile_edited(message: Message, state: FSMContext) -> None:
    await state.update_data(profile_md=message.text)
    await state.set_state(Onboarding.confirm)
    await message.answer(
        f"Обновлённый профиль:\n\n{message.text}",
        reply_markup=kb_profile_confirm(),
    )
```

В `core/services/onboarding.py` добавить фабрику (по образцу других сервисов):

```python
def get_llm_client() -> LLMClient:
    return LLMClient()
```

Проверить наличие `emoji.WAIT` в `core/emoji.py` — если нет, добавить `WAIT = "⏳"` (по фактическому стилю файла).

- [ ] **Step 5: Новый `/start` + fallback в `bot/handlers/start.py`**

```python
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.onboarding import start_onboarding
from core import emoji

router = Router()

_HELP_TEXT = (
    "Я — семейный помощник для меню и покупок.\n\n"
    "Команды:\n"
    f"{emoji.MENU} /menu — текущее меню\n"
    f"{emoji.TODAY} /today — что готовить сегодня\n"
    f"{emoji.SHOPPING} /list — список покупок\n"
    f"{emoji.ADD} /add — добавить пункт в список\n"
    "👤 /profile — профиль семьи\n"
    "👪 /family — управление семьёй\n"
    "✉️ /invite — пригласить в семью\n"
    f"{emoji.HELP} /help — справка"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, family=None) -> None:
    # deep-link inv_<код> обрабатывается в bot/handlers/family.py (роутер регистрируется раньше)
    if family is not None:
        await message.answer(_HELP_TEXT)
        return
    await start_onboarding(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)
```

И fallback для юзеров без семьи — добавить в КОНЕЦ `bot/handlers/onboarding.py`:

```python
@router.message()
async def no_family_fallback(message: Message, family=None) -> None:
    if family is None:
        await message.answer("Сначала настроим бота: нажмите /start")
```

- [ ] **Step 6: Регистрация в `bot/main.py`**

Порядок роутеров (важно):

```python
    dp.include_router(family_handler.router)      # /start inv_ deep-link (Task 9; до Task 9 строку не добавлять)
    dp.include_router(start_handler.router)       # /start, /help
    dp.include_router(menu_handler.router)
    dp.include_router(shopping_handler.router)
    dp.include_router(load_handler.router)
    dp.include_router(freetext_handler.router)    # HasFamily: catch-all для «семейных»
    dp.include_router(onboarding_handler.router)  # FSM + fallback для юзеров без семьи — ПОСЛЕДНИЙ
```

В `BOT_COMMANDS` добавить `profile`, `family`, `invite` (описания на русском).

- [ ] **Step 7: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add -A
git commit -m "feat(bot): onboarding wizard — survey, profile generation, family creation"
```

---

### Task 8: /profile — просмотр и редактирование

**Files:**
- Create: `bot/handlers/profile.py`
- Modify: `bot/fsm.py` (state), `bot/main.py` (роутер — после start, до menu)
- Test: `tests/integration/test_profile_flow.py`

**Interfaces:**
- Consumes: `IsAdmin`, `HasFamily` (Task 3).
- Produces: `update_profile(session, *, family, profile_md: str) -> None` в `core/services/family_service.py`.

- [ ] **Step 1: Падающий тест сервисной части**

Создать `tests/integration/test_profile_flow.py`:

```python
from core.services.family_service import create_family, update_profile


async def test_update_profile(db_session):
    family, _ = await create_family(
        db_session, telegram_user_id=1, display_name="A",
        profile_md="старый", timezone="UTC", plan_slots=["dinner"],
    )
    await update_profile(db_session, family=family, profile_md="новый")
    assert family.profile_md == "новый"
```

Run → FAIL. Добавить в `core/services/family_service.py`:

```python
async def update_profile(session: AsyncSession, *, family: Family, profile_md: str) -> None:
    family.profile_md = profile_md
    await session.flush()
```

Run → PASS.

- [ ] **Step 2: Хендлеры `bot/handlers/profile.py`**

```python
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import HasFamily, IsAdmin
from bot.fsm import ProfileEdit
from core import emoji
from core.services.family_service import get_admin, update_profile

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily())


def _kb_edit():
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Редактировать", callback_data="profile:edit")
    return b.as_markup()


@router.message(Command("profile"))
async def cmd_profile(message: Message, family, family_member) -> None:
    from core.services.family_service import is_admin

    text = f"Профиль семьи:\n\n{family.profile_md or '(профиль пуст)'}"
    if is_admin(family_member):
        await message.answer(text, reply_markup=_kb_edit())
    else:
        await message.answer(text)


@router.callback_query(F.data == "profile:edit", IsAdmin())
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileEdit.waiting_text)
    await cb.message.answer(
        "Пришлите новую версию профиля целиком:", reply_markup=ForceReply()
    )
    await cb.answer()


@router.callback_query(F.data == "profile:edit")
async def on_edit_denied(cb: CallbackQuery, db_session, family) -> None:
    admin = await get_admin(db_session, family_id=family.id)
    name = admin.display_name if admin else "администратор"
    await cb.answer(f"Профиль может менять только {name}", show_alert=True)


@router.message(ProfileEdit.waiting_text, F.text, IsAdmin())
async def on_new_text(
    message: Message, state: FSMContext, db_session, family
) -> None:
    await update_profile(db_session, family=family, profile_md=message.text)
    await state.clear()
    await message.answer(f"{emoji.DONE} Профиль обновлён.")
```

В `bot/fsm.py`:

```python
class ProfileEdit(StatesGroup):
    waiting_text = State()
```

В `bot/main.py` включить роутер после `start_handler`.

- [ ] **Step 3: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add -A
git commit -m "feat(bot): /profile view and admin-only editing"
```

---

### Task 9: Инвайты, /family, уведомления админу

**Files:**
- Create: `bot/handlers/family.py`
- Modify: `core/services/shopping_list.py` (генерализация уведомлений), `bot/handlers/shopping.py`, `config.py` (удалить `vova_telegram_id`), `bot/main.py`, `bot/keyboards.py`
- Test: `tests/unit/test_shopping_notifications.py` (переписать), `tests/integration/test_family_flow.py` (join)

**Interfaces:**
- Consumes: `join_by_invite`, `regenerate_invite`, `set_can_plan`, `transfer_admin`, `get_admin`, `is_admin` (Task 2); `get_family_members` (`core/repositories.py:212`).
- Produces: `build_added_notifications(adder: FamilyMember, members: list[FamilyMember], names: list[str]) -> list[tuple[int, str]]` в `core/services/shopping_list.py` — уведомление «X добавил в список» всем, кроме добавившего. Функция `build_notifications` (Вова-версия) удаляется.

- [ ] **Step 1: Переписать тесты уведомлений**

`tests/unit/test_shopping_notifications.py` — заменить содержимое:

```python
from core.db import FamilyMember
from core.services.shopping_list import build_added_notifications


def _member(tg_id: int, name: str) -> FamilyMember:
    return FamilyMember(family_id=1, telegram_user_id=tg_id, display_name=name)


def test_notifies_everyone_except_adder():
    adder = _member(1, "Вова")
    members = [adder, _member(2, "Юля"), _member(3, "Мама")]
    pairs = build_added_notifications(adder, members, ["молоко", "хлеб"])
    ids = [tg for tg, _ in pairs]
    assert ids == [2, 3]
    assert all("Вова добавил в список: молоко, хлеб" in text for _, text in pairs)


def test_no_names_no_notifications():
    adder = _member(1, "Вова")
    assert build_added_notifications(adder, [adder, _member(2, "Юля")], []) == []
```

Run → FAIL.

- [ ] **Step 2: Генерализовать в `core/services/shopping_list.py`**

Удалить `build_notifications` (и параметр `vova_id`). Добавить:

```python
def build_added_notifications(
    adder: FamilyMember,
    members: list[FamilyMember],
    names: list[str],
) -> list[tuple[int, str]]:
    """(telegram_id, text) для всех членов семьи, кроме добавившего."""
    if not names:
        return []
    who = adder.display_name or "Кто-то"
    text = f"{emoji.SHOPPING} {who} добавил в список: {', '.join(names)}"
    return [
        (m.telegram_user_id, text)
        for m in members
        if m.telegram_user_id != adder.telegram_user_id
    ]
```

В `bot/handlers/shopping.py`: переименовать `_notify_vova_added` → `_notify_added`, убрать чтение `vova_telegram_id` из settings, передавать `family_member` (добавившего) в `build_added_notifications`. Из `config.py` удалить `vova_telegram_id`.

Run: `pytest tests/unit/test_shopping_notifications.py -q` → PASS.

- [ ] **Step 3: Тест join-флоу**

Создать `tests/integration/test_family_flow.py`:

```python
from core.services.family_service import create_family, get_admin, join_by_invite


async def test_join_notifies_admin_target(db_session):
    family, admin = await create_family(
        db_session, telegram_user_id=1, display_name="Юля",
        profile_md="p", timezone="UTC", plan_slots=["dinner"],
    )
    _, member = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=2, display_name="Вова"
    )
    found_admin = await get_admin(db_session, family_id=family.id)
    assert found_admin.telegram_user_id == 1
    assert member.family_id == family.id
```

Run → PASS (использует Task 2; тест фиксирует контракт для хендлера).

- [ ] **Step 4: Хендлеры `bot/handlers/family.py`**

```python
"""Инвайты, join по deep-link и /family (управление участниками)."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import HasFamily, IsAdmin
from core import emoji
from core.exceptions import AlreadyInFamily, InvalidInviteCode
from core.repositories import get_family_members
from core.services.family_service import (
    get_admin,
    is_admin,
    join_by_invite,
    regenerate_invite,
    set_can_plan,
    transfer_admin,
)

router = Router()

INVITE_PREFIX = "inv_"


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(INVITE_PREFIX)))
async def start_with_invite(
    message: Message, command: CommandObject, db_session, family=None
) -> None:
    if family is not None:
        await message.answer("Вы уже состоите в семье.")
        return
    code = command.args.removeprefix(INVITE_PREFIX)
    try:
        joined_family, member = await join_by_invite(
            db_session,
            invite_code=code,
            telegram_user_id=message.from_user.id,
            display_name=message.from_user.full_name,
        )
    except InvalidInviteCode:
        await message.answer("Ссылка-приглашение недействительна. Попросите новую.")
        return
    except AlreadyInFamily:
        await message.answer("Вы уже состоите в семье.")
        return
    await message.answer(
        f"{emoji.DONE} Вы присоединились к семье «{joined_family.name}»!\n"
        "Список покупок: /list, меню: /menu"
    )
    admin = await get_admin(db_session, family_id=joined_family.id)
    if admin and admin.telegram_user_id != member.telegram_user_id:
        await message.bot.send_message(
            admin.telegram_user_id,
            f"👪 {member.display_name or 'Новый участник'} присоединился к семье",
        )


@router.message(Command("invite"), HasFamily(), IsAdmin())
async def cmd_invite(message: Message, family) -> None:
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start={INVITE_PREFIX}{family.invite_code}"
    await message.answer(
        f"Ссылка-приглашение в семью (перешлите близким):\n{link}"
    )


@router.message(Command("invite"), HasFamily())
async def cmd_invite_denied(message: Message, db_session, family) -> None:
    admin = await get_admin(db_session, family_id=family.id)
    name = admin.display_name if admin else "администратор"
    await message.answer(f"Приглашать может только администратор ({name}).")


def _kb_family(members, admin_id: int):
    b = InlineKeyboardBuilder()
    for m in members:
        if m.id == admin_id:
            continue
        mark = emoji.DONE if m.can_plan else emoji.UNCHECKED
        b.button(
            text=f"{mark} план: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:plan:{m.id}",
        )
        b.button(
            text=f"👑 сделать админом: {m.display_name or m.telegram_user_id}",
            callback_data=f"fam:admin:{m.id}",
        )
    b.button(text="🔄 Новая инвайт-ссылка", callback_data="fam:reinvite")
    b.adjust(1)
    return b.as_markup()


@router.message(Command("family"), HasFamily(), IsAdmin())
async def cmd_family(message: Message, db_session, family, family_member) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    lines = [
        f"{'👑 ' if is_admin(m) else ''}{m.display_name or m.telegram_user_id}"
        + (" — может планировать" if m.can_plan and not is_admin(m) else "")
        for m in members
    ]
    await message.answer(
        "Семья «{}»:\n{}".format(family.name, "\n".join(lines)),
        reply_markup=_kb_family(members, admin_id=family_member.id),
    )


@router.message(Command("family"), HasFamily())
async def cmd_family_member_view(message: Message, db_session, family) -> None:
    members = await get_family_members(db_session, family_id=family.id)
    lines = [
        f"{'👑 ' if is_admin(m) else ''}{m.display_name or m.telegram_user_id}"
        for m in members
    ]
    await message.answer("Семья «{}»:\n{}".format(family.name, "\n".join(lines)))


@router.callback_query(F.data.startswith("fam:plan:"), IsAdmin())
async def on_toggle_plan(cb: CallbackQuery, db_session, family, family_member) -> None:
    member_id = int(cb.data.split(":")[-1])
    members = await get_family_members(db_session, family_id=family.id)
    target = next((m for m in members if m.id == member_id), None)
    if target is None:
        await cb.answer("Участник не найден", show_alert=True)
        return
    updated = await set_can_plan(db_session, member_id=member_id, value=not target.can_plan)
    members = await get_family_members(db_session, family_id=family.id)
    await cb.message.edit_reply_markup(
        reply_markup=_kb_family(members, admin_id=family_member.id)
    )
    state = "может планировать" if updated.can_plan else "больше не планирует"
    await cb.answer(f"{updated.display_name or 'Участник'} {state}")


@router.callback_query(F.data.startswith("fam:admin:"), IsAdmin())
async def on_transfer_admin(cb: CallbackQuery, db_session, family) -> None:
    member_id = int(cb.data.split(":")[-1])
    await transfer_admin(db_session, family_id=family.id, to_member_id=member_id)
    await cb.message.edit_text("Права администратора переданы. /family — актуальный состав.")
    await cb.answer()


@router.callback_query(F.data == "fam:reinvite", IsAdmin())
async def on_reinvite(cb: CallbackQuery, db_session, family) -> None:
    await regenerate_invite(db_session, family=family)
    me = await cb.bot.get_me()
    link = f"https://t.me/{me.username}?start={INVITE_PREFIX}{family.invite_code}"
    await cb.message.answer(f"Новая ссылка-приглашение:\n{link}")
    await cb.answer("Старая ссылка больше не работает")
```

Примечание: у join-хендлера НЕТ фильтра HasFamily (юзер ещё без семьи), поэтому фильтры навешаны на конкретные хендлеры, а не на роутер целиком.

- [ ] **Step 5: Регистрация и уведомление админа о покупках**

`bot/main.py`: включить `family_handler.router` ПЕРВЫМ (до `start_handler`, чтобы deep-link перехватывался раньше обычного /start).
Проверить сигнатуру `get_family_members` в `core/repositories.py:212` — если параметр называется иначе (`family_id` позиционный), привести вызовы к фактической сигнатуре.

- [ ] **Step 6: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add -A
git commit -m "feat(family): invites via deep-link, /family management, admin notifications"
```

---

### Task 10: Postgres, сид своей семьи, финальная прогонка

**Files:**
- Modify: `pyproject.toml`, `.env.example`, `alembic/env.py` (проверка), `Dockerfile` (проверка)
- Create: `scripts/seed_own_family.py`
- Test: ручной smoke на Postgres в docker

**Interfaces:**
- Consumes: `create_family` (Task 2), миграции (Task 1).
- Produces: рабочая схема на Postgres; скрипт сида семьи владельца.

- [ ] **Step 1: Зависимость asyncpg**

В `pyproject.toml` dependencies добавить: `"asyncpg>=0.29",`. Установить: `uv sync` (или `pip install -e .` — по фактическому окружению).

- [ ] **Step 2: Проверить alembic/env.py**

Run: `grep -n "db_url\|get_settings\|sqlalchemy.url" alembic/env.py`
Expected: env.py берёт URL из настроек/переменной DB_URL. Если URL захардкожен в `alembic.ini` — переключить env.py на `get_settings().db_url`.

- [ ] **Step 3: Smoke-тест миграций на Postgres**

```bash
docker run -d --name chefbot-pg -e POSTGRES_PASSWORD=dev -p 5433:5432 postgres:16
sleep 3
DB_URL=postgresql+asyncpg://postgres:dev@localhost:5433/postgres alembic upgrade head
docker exec chefbot-pg psql -U postgres -c "\dt"
```

Expected: все миграции 0001→0005 проходят; в списке таблиц есть `families, family_members, menus, meals, recipes, shopping_lists, shopping_items, claude_conversations, llm_usage`. Типичные проблемы: native enum'ы в 0002/0003 (имена типов), `CURRENT_TIMESTAMP` server_default — чинить в миграциях, НЕ в моделях. После проверки: `docker rm -f chefbot-pg`.

- [ ] **Step 4: Скрипт сида своей семьи `scripts/seed_own_family.py`**

```python
"""Одноразовый сид семьи владельца после перехода на Postgres.

Usage:
    DB_URL=postgresql+asyncpg://... python scripts/seed_own_family.py \
        --admin-id 123456 --member-id 789012 --name "Наша семья"
"""
import argparse
import asyncio
from pathlib import Path

from core.db import FamilyMember, session_scope
from core.services.family_service import create_family

BASE_CONTEXT = Path(__file__).parent.parent / "core" / "prompts" / "base_context.md"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-id", type=int, required=True)
    parser.add_argument("--member-id", type=int, action="append", default=[])
    parser.add_argument("--name", default="Наша семья")
    args = parser.parse_args()

    profile_md = BASE_CONTEXT.read_text(encoding="utf-8")
    async with session_scope() as session:
        family, admin = await create_family(
            session,
            telegram_user_id=args.admin_id,
            display_name=args.name,
            profile_md=profile_md,
            timezone="Asia/Bangkok",
            plan_slots=["lunch", "dinner"],
        )
        for tg_id in args.member_id:
            session.add(FamilyMember(family_id=family.id, telegram_user_id=tg_id))
        print(f"family_id={family.id} invite_code={family.invite_code}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: .env.example и деплой-заметка**

`.env.example`: заменить строку DB на:

```
# Local dev: sqlite. Production (Railway): создайте Postgres-сервис и возьмите URL,
# заменив схему postgres:// на postgresql+asyncpg://
DB_URL=sqlite+aiosqlite:///./data/chef.db
```

- [ ] **Step 6: Финальная прогонка этапа**

Run: `ruff check . && pytest -q`
Expected: PASS. Дополнительно вручную: `python -c "import bot.main"` — импорт без ошибок.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(infra): asyncpg + Postgres migrations smoke, own-family seed script"
```

---

## Self-Review Notes

- **Spec coverage (этап 1):** профиль-как-данные (T1, T4, T6–T8), онбординг (T6–T7), инвайты (T9), роли/права (T2, T9), снятие allowlist (T3), миграция 0005 (T1), Postgres (T10), миграция своей семьи (T10), llm_usage-фундамент для лимитов этапа 3 (T5, запись в T7). Уведомление админа о генерации/аппруве меню — этап 2 (там появляется сам флоу /plan). Per-family дайджест и лимиты — этап 3 (в Global Constraints).
- **Известные упрощения:** прерванный онбординг теряется при рестарте (MemoryStorage — так в спеке); дайджест до этапа 3 шлётся всем в 9:00 BKK.
- **Роутинг:** порядок роутеров критичен — family (deep-link) → start → profile → menu → shopping → load → freetext (HasFamily catch-all) → onboarding (FSM + fallback без семьи) последним.
