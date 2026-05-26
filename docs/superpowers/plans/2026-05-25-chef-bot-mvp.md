# Chef-Bot MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal Telegram meal-planner bot for a family of 2 living on Phuket, generating menus / recipes / shopping lists via Claude API in Russian. MVP scope: phases 0–3 from the design spec.

**Architecture:** Two-layer architecture (`bot/` + `core/`). Bot layer is a thin aiogram-3 wrapper that parses Telegram updates and delegates to core services. Core layer owns business logic, LLM integration, and DB access. Hybrid pattern: slash commands and inline-button callbacks call core directly; free-text messages go through a tool-use agent (`core/services/conversation.py`) that calls the same core services as tools.

**Tech Stack:** Python 3.12+, aiogram 3, official `anthropic` SDK (Claude Sonnet 4.6), SQLAlchemy 2.0 async + Alembic, SQLite (aiosqlite driver), pydantic v2 + pydantic-settings, loguru for logging, ruff for lint/format, pytest + pytest-asyncio for tests. Deployment: Docker container on PaaS (Fly.io / Railway / Render) with persistent volume for SQLite file.

**Reference spec:** [docs/superpowers/specs/2026-05-25-chef-bot-design.md](../specs/2026-05-25-chef-bot-design.md)

---

## File Structure (target after all phases)

```
chef-bot/
├── pyproject.toml
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── README.md
├── config.py
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_init.py            -- families, family_members
│       ├── 0002_menus_meals.py     -- menus, meals, recipes
│       ├── 0003_shopping.py        -- shopping_lists, shopping_items
│       └── 0004_conversations.py   -- claude_conversations
├── bot/
│   ├── __init__.py
│   ├── main.py                     -- entrypoint, dispatcher, polling
│   ├── middlewares.py              -- AllowlistMiddleware, FamilyResolverMiddleware
│   ├── keyboards.py                -- inline keyboards
│   ├── fsm.py                      -- FSM states for /plan wizard
│   └── handlers/
│       ├── __init__.py
│       ├── start.py                -- /start, /help
│       ├── plan.py                 -- /plan wizard
│       ├── menu.py                 -- /menu, /today
│       ├── recipe.py               -- /recipe
│       ├── shopping.py             -- /list + mark_bought callback
│       └── freetext.py             -- free-text → conversation service
├── core/
│   ├── __init__.py
│   ├── db.py                       -- SQLAlchemy ORM models + session factory
│   ├── models.py                   -- Pydantic domain models
│   ├── repositories.py             -- DB access functions
│   ├── llm.py                      -- Anthropic client wrapper
│   ├── tools.py                    -- tool definitions for conversation agent
│   ├── exceptions.py
│   ├── prompts/
│   │   ├── base_context.md         -- shared user context (family, rules, products...)
│   │   ├── menu_planner.md
│   │   ├── recipe.md
│   │   ├── shopping_list.md
│   │   └── conversation.md
│   └── services/
│       ├── __init__.py
│       ├── family_service.py
│       ├── menu_planner.py
│       ├── recipe_service.py
│       ├── shopping_list.py
│       ├── dish_replacer.py
│       └── conversation.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── unit/
    │   ├── test_models.py
    │   ├── test_llm_parsing.py
    │   └── test_tools.py
    └── integration/
        ├── test_family_service.py
        ├── test_menu_planner.py
        ├── test_recipe_service.py
        ├── test_shopping_list.py
        └── test_conversation.py
```

---

# PHASE 0 — Project Skeleton

**Goal:** Bot answers `/start` to allowlisted users. SQLAlchemy is configured. CI-lint passes. Code is dockerizable.

---

### Task 0.1: Create `pyproject.toml` with dependencies

> **Status:** ✅ DONE (2026-05-25, commits fdc66d2 + b97cbeb). `[build-system]` section was added during code-quality review.

**Files:**
- Create: `pyproject.toml`

- [x] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "chef-bot"
version = "0.1.0"
description = "Personal Telegram meal-planner bot"
requires-python = ">=3.12"
dependencies = [
    "aiogram>=3.13,<4",
    "anthropic>=0.40,<1",
    "sqlalchemy[asyncio]>=2.0,<3",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "pydantic>=2.8,<3",
    "pydantic-settings>=2.5",
    "loguru>=0.7",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "ASYNC"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [x] **Step 2: Install dependencies**

Run: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: All deps install successfully.

- [x] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with project deps"
```

---

### Task 0.2: Create `.gitignore` and `.env.example`

> **Status:** ✅ DONE (2026-05-25). Pure paste task done inline (no subagent).

**Files:**
- Create: `.gitignore`
- Create: `.env.example`

- [x] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.venv/
venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Project
.env
data/
*.db
*.db-journal

# IDE
.vscode/
.idea/

# OS
.DS_Store
```

- [x] **Step 2: Write `.env.example`**

```bash
# Telegram Bot
BOT_TOKEN=

# Anthropic
ANTHROPIC_API_KEY=

# Allowlist (comma-separated telegram user IDs)
ALLOWLIST_TELEGRAM_IDS=123456789,987654321

# Database (default: local SQLite)
DB_URL=sqlite+aiosqlite:///./data/chef.db

# Misc
TIMEZONE=Asia/Bangkok
LOG_LEVEL=INFO
CLAUDE_MODEL=claude-sonnet-4-6
```

- [x] **Step 3: Commit**

```bash
git add .gitignore .env.example
git commit -m "chore: add .gitignore and .env.example"
```

---

### Task 0.3: Create `config.py` (pydantic-settings)

> **Status:** ✅ DONE (2026-05-26). Added `NoDecode` + `field_validator` for comma-separated `ALLOWLIST_TELEGRAM_IDS` (pydantic-settings 2.x JSON-decodes list fields by default).

**Files:**
- Create: `config.py`
- Test: `tests/unit/test_config.py`

- [x] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import os
import pytest
from config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ALLOWLIST_TELEGRAM_IDS", "111,222")

    s = Settings()
    assert s.bot_token.get_secret_value() == "abc"
    assert s.anthropic_api_key.get_secret_value() == "sk-test"
    assert s.allowlist_telegram_ids == [111, 222]
    assert s.timezone == "Asia/Bangkok"
    assert s.claude_model == "claude-sonnet-4-6"
```

- [x] **Step 2: Run test, verify it fails**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL (ImportError — config.Settings does not exist)

- [x] **Step 3: Implement `config.py`**

```python
# config.py
from functools import lru_cache
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    allowlist_telegram_ids: list[int] = Field(default_factory=list)
    db_url: str = "sqlite+aiosqlite:///./data/chef.db"
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"
    claude_model: str = "claude-sonnet-4-6"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [x] **Step 4: Run test, verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add config.py tests/unit/test_config.py tests/__init__.py tests/unit/__init__.py
git commit -m "feat(config): add pydantic-settings configuration"
```

(Create empty `tests/__init__.py` and `tests/unit/__init__.py` as needed.)

---

### Task 0.4: Create `core/db.py` — ORM base + session factory

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline. Imports verified via `python -c`.

**Files:**
- Create: `core/__init__.py` (empty)
- Create: `core/db.py`

- [x] **Step 1: Implement `core/db.py`**

```python
# core/db.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


# Reusable column type for created_at fields
CreatedAt = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().db_url, echo=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager that commits on success, rolls back on error."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [x] **Step 2: Commit**

```bash
git add core/__init__.py core/db.py
git commit -m "feat(db): add SQLAlchemy base and session factory"
```

---

### Task 0.5: Add `families` and `family_members` ORM models

> **Status:** ✅ DONE (2026-05-26). Imports consolidated at top of file (instead of literal append) to keep ruff `I` happy.

**Files:**
- Modify: `core/db.py` — append ORM models

- [x] **Step 1: Append ORM models to `core/db.py`**

Append at end of file:

```python
from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import relationship


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[CreatedAt]

    members: Mapped[list["FamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[CreatedAt]

    family: Mapped["Family"] = relationship(back_populates="members")
```

- [x] **Step 2: Commit**

```bash
git add core/db.py
git commit -m "feat(db): add families and family_members ORM models"
```

---

### Task 0.6: Initialize Alembic and create first migration

> **Status:** ✅ DONE (2026-05-26). Migration applied to `data/chef.db`; `.tables` shows `alembic_version`, `families`, `family_members`. Migration revision renamed to `0001_init` for readability.

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/` (directory)

- [x] **Step 1: Run alembic init**

Run: `alembic init -t async alembic`
Expected: Alembic creates `alembic/`, `alembic.ini`, etc.

- [x] **Step 2: Edit `alembic.ini` — set sqlalchemy.url**

In `alembic.ini`, replace the line `sqlalchemy.url = driver://user:pass@localhost/dbname` with:

```ini
sqlalchemy.url =
```

(Empty — we'll set it from env in `env.py`.)

- [x] **Step 3: Edit `alembic/env.py` — load metadata and url from project**

Replace the auto-generated `alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from config import get_settings
from core.db import Base
import core.db  # noqa: F401  -- ensure ORM models are imported

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [x] **Step 4: Generate first migration**

Run: `mkdir -p data && BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic revision --autogenerate -m "init: families and family_members"`
Expected: A file appears in `alembic/versions/` defining `families` and `family_members` tables.

Inspect the generated migration to confirm it has both tables. Rename the file to `0001_init.py` for readability.

- [x] **Step 5: Apply migration**

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic upgrade head`
Expected: Creates `data/chef.db` with both tables.

Verify: `sqlite3 data/chef.db ".tables"` should list `alembic_version`, `families`, `family_members`.

- [x] **Step 6: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat(db): init alembic and add first migration"
```

---

### Task 0.7: Add `core/exceptions.py`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline.

**Files:**
- Create: `core/exceptions.py`

- [x] **Step 1: Write `core/exceptions.py`**

```python
# core/exceptions.py
class ChefBotError(Exception):
    """Base exception."""


class NotAuthorized(ChefBotError):
    """Telegram user is not in allowlist."""


class FamilyNotFound(ChefBotError):
    pass


class MenuNotFound(ChefBotError):
    pass


class MealNotFound(ChefBotError):
    pass


class LLMError(ChefBotError):
    """Generic LLM failure (timeout, invalid JSON, etc)."""


class LLMInvalidResponse(LLMError):
    pass
```

- [x] **Step 2: Commit**

```bash
git add core/exceptions.py
git commit -m "feat(core): add custom exception types"
```

---

### Task 0.8: Add `core/services/family_service.py` (TDD)

> **Status:** ✅ DONE (2026-05-26). 4/4 tests pass. Dropped manual `event_loop` fixture (pytest-asyncio auto mode handles it); dropped `@pytest.mark.asyncio` decorators (redundant under auto mode).

**Files:**
- Create: `core/services/__init__.py` (empty)
- Create: `core/services/family_service.py`
- Test: `tests/integration/test_family_service.py`
- Modify: `tests/conftest.py` — add async DB fixture
- Create: `tests/integration/__init__.py` (empty)

- [x] **Step 1: Write `tests/conftest.py` with async DB fixtures**

```python
# tests/conftest.py
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWLIST_TELEGRAM_IDS", "111,222")
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"

from core.db import Base  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()
```

- [x] **Step 2: Write the failing test**

```python
# tests/integration/test_family_service.py
import pytest

from core.services.family_service import (
    get_or_create_family,
    is_authorized,
)


@pytest.mark.asyncio
async def test_unauthorized_telegram_id_returns_false(db_session, monkeypatch):
    monkeypatch.setenv("ALLOWLIST_TELEGRAM_IDS", "111,222")
    assert is_authorized(999) is False


@pytest.mark.asyncio
async def test_authorized_telegram_id_returns_true(monkeypatch):
    monkeypatch.setenv("ALLOWLIST_TELEGRAM_IDS", "111,222")
    # invalidate cached settings
    from config import get_settings
    get_settings.cache_clear()
    assert is_authorized(111) is True


@pytest.mark.asyncio
async def test_get_or_create_family_creates_new(db_session):
    family, member = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    assert family.id is not None
    assert member.telegram_user_id == 111
    assert member.display_name == "Юля"
    assert member.family_id == family.id


@pytest.mark.asyncio
async def test_get_or_create_family_returns_existing(db_session):
    f1, m1 = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    f2, m2 = await get_or_create_family(
        db_session, telegram_user_id=111, display_name="Юля"
    )
    assert f1.id == f2.id
    assert m1.id == m2.id
```

- [x] **Step 3: Run test, verify it fails**

Run: `pytest tests/integration/test_family_service.py -v`
Expected: FAIL (ImportError)

- [x] **Step 4: Implement `core/services/family_service.py`**

```python
# core/services/family_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.db import Family, FamilyMember


def is_authorized(telegram_user_id: int) -> bool:
    return telegram_user_id in get_settings().allowlist_telegram_ids


async def get_or_create_family(
    session: AsyncSession,
    telegram_user_id: int,
    display_name: str | None = None,
) -> tuple[Family, FamilyMember]:
    """
    For MVP shared-family mode: all allowlisted users share a single Family.
    If no Family exists yet, create one and attach the member.
    If member with this telegram_user_id exists, return their family.
    """
    member_stmt = select(FamilyMember).where(
        FamilyMember.telegram_user_id == telegram_user_id
    )
    member = (await session.execute(member_stmt)).scalar_one_or_none()
    if member is not None:
        family_stmt = select(Family).where(Family.id == member.family_id)
        family = (await session.execute(family_stmt)).scalar_one()
        return family, member

    family_stmt = select(Family).limit(1)
    family = (await session.execute(family_stmt)).scalar_one_or_none()
    if family is None:
        family = Family(name="Family")
        session.add(family)
        await session.flush()

    member = FamilyMember(
        family_id=family.id,
        telegram_user_id=telegram_user_id,
        display_name=display_name,
    )
    session.add(member)
    await session.flush()
    return family, member
```

- [x] **Step 5: Run test, verify it passes**

Run: `pytest tests/integration/test_family_service.py -v`
Expected: PASS (4/4)

- [x] **Step 6: Commit**

```bash
git add core/services/ tests/conftest.py tests/integration/
git commit -m "feat(family): add family_service with allowlist auth"
```

---

### Task 0.9: Create bot skeleton with `/start` and `/help`

> **Status:** ✅ DONE (2026-05-26). Imports verified via dry-run; ruff clean. Step 4 (manual Telegram smoke test) deferred — requires real BOT_TOKEN; will exercise after Task 0.10 once Docker image runs end-to-end.

**Files:**
- Create: `bot/__init__.py` (empty)
- Create: `bot/main.py`
- Create: `bot/middlewares.py`
- Create: `bot/handlers/__init__.py`
- Create: `bot/handlers/start.py`

- [x] **Step 1: Write `bot/middlewares.py`**

```python
# bot/middlewares.py
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from loguru import logger

from config import get_settings
from core.db import session_scope
from core.services.family_service import get_or_create_family, is_authorized


class AllowlistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or not is_authorized(user.id):
            logger.warning("rejected non-allowlisted user user_id={}",
                           user.id if user else "?")
            return None
        return await handler(event, data)


class FamilyResolverMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User = data["event_from_user"]
        async with session_scope() as session:
            family, member = await get_or_create_family(
                session,
                telegram_user_id=user.id,
                display_name=user.full_name,
            )
            data["family"] = family
            data["family_member"] = member
            data["db_session"] = session
            return await handler(event, data)
```

- [x] **Step 2: Write `bot/handlers/start.py`**

```python
# bot/handlers/start.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-помощник для планирования меню.\n\n"
        "Команды:\n"
        "/plan — спланировать меню\n"
        "/menu — показать текущее меню\n"
        "/today — что готовить сегодня\n"
        "/recipe — рецепт текущего приёма\n"
        "/list — список покупок\n"
        "/help — справка\n\n"
        "Также я понимаю свободный текст — просто напиши, что хочешь."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await cmd_start(message)
```

- [x] **Step 3: Write `bot/main.py`**

```python
# bot/main.py
import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from bot.handlers import start as start_handler
from bot.middlewares import AllowlistMiddleware, FamilyResolverMiddleware
from config import get_settings


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.middleware(AllowlistMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware())
    dp.message.middleware(FamilyResolverMiddleware())
    dp.callback_query.middleware(FamilyResolverMiddleware())

    dp.include_router(start_handler.router)

    logger.info("starting bot polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Manual smoke test** (deferred — needs real BOT_TOKEN)

With a valid `.env` file (real `BOT_TOKEN`, `ALLOWLIST_TELEGRAM_IDS=<your id>`):

Run: `python -m bot.main`
Expected: Logs "starting bot polling". From your Telegram, send `/start` to the bot — get the welcome reply.

Stop with Ctrl-C.

- [x] **Step 5: Commit**

```bash
git add bot/
git commit -m "feat(bot): add bot skeleton with /start and allowlist middleware"
```

---

### Task 0.10: Add Dockerfile and `.dockerignore`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline. Step 3 (`docker build`) deferred — verify before deploying to PaaS.

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [x] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . ./

RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]
```

- [x] **Step 2: Write `.dockerignore`**

```
.git
.gitignore
.venv
__pycache__
*.pyc
.pytest_cache
.ruff_cache
tests/
docs/
.env
data/
```

- [ ] **Step 3: Build and run locally to verify**

Run:
```bash
docker build -t chef-bot:dev .
docker run --rm -e BOT_TOKEN=$BOT_TOKEN \
                -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
                -e ALLOWLIST_TELEGRAM_IDS=$ALLOWLIST_TELEGRAM_IDS \
                -v $(pwd)/data:/app/data \
                chef-bot:dev
```
Expected: Container starts, alembic runs migration, bot starts polling. From Telegram `/start` works.

- [x] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "chore: add Dockerfile and .dockerignore"
```

---

### Phase 0 — Verification

- [ ] All tests pass: `pytest`
- [ ] Ruff is clean: `ruff check .`
- [ ] Bot responds to `/start` from allowlisted user
- [ ] Bot ignores non-allowlisted users
- [ ] DB file `data/chef.db` is created with `families` and `family_members`
- [ ] Docker build + run works locally

---

# PHASE 1 — Menu Planning + Recipes

**Goal:** User can run `/plan` wizard, generate a menu via Claude, approve it. `/menu`, `/today`, `/recipe` work.

---

### Task 1.1: Add menus, meals, recipes ORM models + migration

> **Status:** ✅ DONE (2026-05-26). Used `enum.StrEnum` (Python 3.11+) instead of `(str, enum.Enum)` per ruff UP042. Imports consolidated at top of file. Migration applied; all 6 tables present.

**Files:**
- Modify: `core/db.py` — add Menu, Meal, Recipe
- Create: `alembic/versions/0002_menus_meals.py` (via autogenerate)

- [x] **Step 1: Add models to `core/db.py`**

Append at end of file:

```python
import enum
from datetime import date as DateType

from sqlalchemy import Date, Enum, Integer, Text, UniqueConstraint
from sqlalchemy import JSON


class MenuStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class MealSlot(str, enum.Enum):
    lunch = "lunch"
    dinner = "dinner"


class ProteinKind(str, enum.Enum):
    chicken = "chicken"
    fish = "fish"
    seafood = "seafood"
    beef = "beef"
    pork = "pork"
    vegetarian = "vegetarian"
    mixed = "mixed"


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    start_date: Mapped[DateType] = mapped_column(Date, nullable=False)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[MenuStatus] = mapped_column(
        Enum(MenuStatus), default=MenuStatus.draft, nullable=False
    )
    created_at: Mapped[CreatedAt]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    meals: Mapped[list["Meal"]] = relationship(
        back_populates="menu", cascade="all, delete-orphan", order_by="Meal.date, Meal.slot"
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False)
    date: Mapped[DateType] = mapped_column(Date, nullable=False)
    slot: Mapped[MealSlot] = mapped_column(Enum(MealSlot), nullable=False)
    dish_name: Mapped[str] = mapped_column(Text, nullable=False)
    side_dishes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    protein_kind: Mapped[ProteinKind] = mapped_column(Enum(ProteinKind), nullable=False)

    menu: Mapped["Menu"] = relationship(back_populates="meals")
    recipe: Mapped["Recipe | None"] = relationship(
        back_populates="meal", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("menu_id", "date", "slot", name="uq_meal_slot"),)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(
        ForeignKey("meals.id"), unique=True, nullable=False
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    ingredients: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[CreatedAt]

    meal: Mapped["Meal"] = relationship(back_populates="recipe")
```

- [x] **Step 2: Generate and apply migration**

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic revision --autogenerate -m "add menus, meals, recipes"`
Inspect the file, rename to `0002_menus_meals.py`.

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic upgrade head`
Expected: Tables created. Verify with `sqlite3 data/chef.db ".tables"`.

- [x] **Step 3: Commit**

```bash
git add core/db.py alembic/versions/0002_menus_meals.py
git commit -m "feat(db): add menus, meals, recipes models and migration"
```

---

### Task 1.2: Add Pydantic domain models

> **Status:** ✅ DONE (2026-05-26). 2/2 tests pass.

**Files:**
- Create: `core/models.py`
- Test: `tests/unit/test_models.py`

- [x] **Step 1: Write `core/models.py`**

```python
# core/models.py
from datetime import date as DateType
from datetime import datetime

from pydantic import BaseModel, Field

from core.db import MealSlot, MenuStatus, ProteinKind


class MealDTO(BaseModel):
    """Pydantic representation of a meal in a menu."""
    date: DateType
    slot: MealSlot
    dish_name: str
    side_dishes: list[str] = Field(default_factory=list)
    protein_kind: ProteinKind


class MenuDTO(BaseModel):
    id: int | None = None
    family_id: int
    start_date: DateType
    days_count: int
    status: MenuStatus = MenuStatus.draft
    meals: list[MealDTO] = Field(default_factory=list)
    created_at: datetime | None = None
    approved_at: datetime | None = None


class IngredientDTO(BaseModel):
    name: str
    quantity: str
    unit: str | None = None
    store: str | None = None


class RecipeDTO(BaseModel):
    meal_id: int | None = None
    content_md: str
    ingredients: list[IngredientDTO] = Field(default_factory=list)
    prep_minutes: int


class LLMMenuResponse(BaseModel):
    """Schema we ask Claude to follow when generating a menu."""
    meals: list[MealDTO]


class LLMRecipeResponse(BaseModel):
    content_md: str
    ingredients: list[IngredientDTO]
    prep_minutes: int
```

- [x] **Step 2: Write tests**

```python
# tests/unit/test_models.py
from datetime import date

from core.db import MealSlot, ProteinKind
from core.models import LLMMenuResponse, MealDTO


def test_meal_dto_parsing():
    raw = {
        "date": "2026-05-26",
        "slot": "lunch",
        "dish_name": "Курица в airfryer с гречкой",
        "side_dishes": ["гречка", "брокколи"],
        "protein_kind": "chicken",
    }
    m = MealDTO.model_validate(raw)
    assert m.date == date(2026, 5, 26)
    assert m.slot == MealSlot.lunch
    assert m.protein_kind == ProteinKind.chicken


def test_llm_menu_response_parsing():
    raw = {
        "meals": [
            {"date": "2026-05-26", "slot": "lunch",
             "dish_name": "x", "side_dishes": [], "protein_kind": "fish"},
            {"date": "2026-05-26", "slot": "dinner",
             "dish_name": "y", "side_dishes": ["z"], "protein_kind": "beef"},
        ]
    }
    r = LLMMenuResponse.model_validate(raw)
    assert len(r.meals) == 2
```

- [x] **Step 3: Run tests, verify they pass**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS (2/2)

- [x] **Step 4: Commit**

```bash
git add core/models.py tests/unit/test_models.py
git commit -m "feat(models): add Pydantic domain DTOs"
```

---

### Task 1.3: Write `core/prompts/base_context.md`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline.

**Files:**
- Create: `core/prompts/base_context.md`

- [x] **Step 1: Write the base context**

This is the full user context that will be the first cached `system` block for every LLM call. Copy verbatim from the design spec / business requirements (section "Пользовательский контекст"):

```markdown
# Контекст семьи

Семья из 2 взрослых, живут на Пхукете, Таиланд. Оба занимаются фитнесом
(тренажёрный зал). Стиль питания: ЗОЖ / ПП, европейская домашняя кухня.
Без строгих диет, фокус на баланс КБЖУ.

## Ограничения по продуктам

- Непереносимость лука и чеснока (мягкий FODMAP — не строго, но придерживаться).
- Индейка (фарш и мясо) недоступна в Таиланде — НЕ включать в меню.
- Лук НЕ добавлять в салаты (в горячие блюда — можно).

## Правила планирования

- Планируем ТОЛЬКО обед и ужин. Завтраки одинаковые каждый день, перекусов нет.
- Овощной гарнир обязателен к каждому обеду и ужину.
- Готовка день-в-день, БЕЗ батч-преппинга — не предлагать готовить заранее.
- Не больше 40 минут активной готовки на основное блюдо.
- Не повторять одно и то же блюдо в рамках одной недели.
- Чередовать белки: курица, рыба/морепродукты, говядина, свинина.
- Яйца НЕ могут быть основным белком.
- Ориентир КБЖУ: ~400–600 ккал на приём, белок ~2г/кг/день.

## Доступные продукты и магазины

- На Пхукете легко доступны: морепродукты, курица, свинина, рис, тофу,
  тропические фрукты, кокосовое молоко.
- **Makro** — основной магазин: мясо (курица, свинина, говядина), рыба (лосось),
  морепродукты, овощи, фрукты, крупы, базовые продукты.
- **Villa Market** — спец. продукты: стейковые отруба, европейская молочка,
  импортные сыры, специальные ингредиенты.
- **Lotus's** — альтернатива Makro для части продуктов.
- **7-Eleven** — готовая кукуруза и мелочи.
- Рынка нет — НЕ включать в списки покупок.

## Кухонная техника

- Airfryer — основной для мяса и овощей.
- Instant Pot — тушение, бобовые, крупы.
- Духовка.
- Большая индукционная плита.
- Тостер, блендер.

## Базовая кладовка (ВСЕГДА есть дома, НЕ включать в списки покупок)

- Оливковое масло (Extra Virgin и обычное)
- Соль, перец чёрный молотый
- Чеснок (свежий или сушёный) — но НЕ использовать в блюдах
- Паприка, орегано / итальянские травы
- Соевый соус

## Избранные блюда (включать в меню и предлагать вариации)

- Курица в airfryer (бёдра/грудка), курица с гречкой + овощи
- Говядина в airfryer (стейки или нарезка)
- Жареный лосось, паста с лососем
- Креветки (жареные, в пасте, в боулах)
- Котлеты (куриные, рыбные), тефтели
- Гарниры: гречка, рис жасмин, паста, бобовые
- Овощи: греческий салат (БЕЗ ЛУКА!), цветная капуста, брокколи, кукуруза
- Сыры: фета, моцарелла, пармезан

## Стиль ответа

- Отвечай на русском языке.
- Будь конкретным и кратким, без воды.
- При генерации меню или рецепта используй заданный JSON-формат строго.
```

- [x] **Step 2: Commit**

```bash
git add core/prompts/base_context.md
git commit -m "feat(prompts): add base_context.md with user context"
```

---

### Task 1.4: Implement `core/llm.py` (Anthropic client wrapper)

> **Status:** ✅ DONE (2026-05-26). 4/4 parser tests pass. LLMClient.chat() not exercised against live API yet — will be covered by Task 1.7 integration test.

**Files:**
- Create: `core/llm.py`
- Test: `tests/unit/test_llm_parsing.py`

- [x] **Step 1: Write `core/llm.py`**

```python
# core/llm.py
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message as AnthropicMessage
from loguru import logger

from config import get_settings
from core.exceptions import LLMError, LLMInvalidResponse

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    raw_message: AnthropicMessage | None = None


class LLMClient:
    def __init__(self) -> None:
        self._client = AsyncAnthropic(
            api_key=get_settings().anthropic_api_key.get_secret_value()
        )
        self._model = get_settings().claude_model

    async def chat(
        self,
        *,
        system_blocks: list[dict],
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Single chat completion.

        system_blocks: list of {"type": "text", "text": ..., "cache_control": ...}
        messages: list of {"role": "user"|"assistant", "content": ...}
        tools: optional list of tool definitions
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "system": system_blocks,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            resp = await self._client.messages.create(**kwargs)
        except Exception as e:
            logger.exception("Anthropic API error")
            raise LLMError(str(e)) from e

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            raw_message=resp,
        )


def build_system_blocks(task_prompt_name: str) -> list[dict]:
    """
    Build system blocks: base_context (cached) + task-specific prompt (cached).
    """
    return [
        {
            "type": "text",
            "text": load_prompt("base_context"),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": load_prompt(task_prompt_name),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def parse_json_response(text: str) -> dict:
    """
    Claude often wraps JSON in ```json fences or extra prose.
    Extract the JSON object or raise LLMInvalidResponse.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json … ``` fences
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMInvalidResponse(f"Could not parse JSON: {e}\nText: {text[:500]}") from e
```

- [x] **Step 2: Write tests for the parser**

```python
# tests/unit/test_llm_parsing.py
import pytest

from core.exceptions import LLMInvalidResponse
from core.llm import parse_json_response


def test_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = '```json\n{"a": 1}\n```'
    assert parse_json_response(text) == {"a": 1}


def test_fenced_without_lang():
    text = "```\n{\"a\": 1}\n```"
    assert parse_json_response(text) == {"a": 1}


def test_invalid_json_raises():
    with pytest.raises(LLMInvalidResponse):
        parse_json_response("not json at all")
```

- [x] **Step 3: Run tests, verify they pass**

Run: `pytest tests/unit/test_llm_parsing.py -v`
Expected: PASS (4/4)

- [x] **Step 4: Commit**

```bash
git add core/llm.py tests/unit/test_llm_parsing.py
git commit -m "feat(llm): add Anthropic client wrapper with prompt loader"
```

---

### Task 1.5: Write `core/prompts/menu_planner.md`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline.

**Files:**
- Create: `core/prompts/menu_planner.md`

- [x] **Step 1: Write the menu-planner prompt**

```markdown
# Задача: генерация меню

Ты планируешь меню обедов и ужинов для семьи из 2 человек (см. контекст выше).

## Что от тебя нужно

Сгенерируй меню по заданному количеству дней. Каждый день — обед и ужин.
Соблюдай ВСЕ правила из контекста семьи (продукты, чередование белков,
непереносимости, кладовка).

Учти содержимое холодильника, которое тебе передадут — используй эти продукты
в меню (особенно в первые дни, чтобы не портились).

## Формат ответа

Верни СТРОГО валидный JSON по схеме ниже, БЕЗ markdown-фенсов, БЕЗ комментариев,
БЕЗ пояснений. Только JSON.

```
{
  "meals": [
    {
      "date": "YYYY-MM-DD",
      "slot": "lunch" | "dinner",
      "dish_name": "Название основного блюда",
      "side_dishes": ["гарнир 1", "гарнир 2"],
      "protein_kind": "chicken" | "fish" | "seafood" | "beef" | "pork" | "vegetarian" | "mixed"
    }
  ]
}
```

## Требования к меню

- Каждый день — ровно 2 элемента: один lunch, один dinner.
- side_dishes — массив из 1-2 строк (овощной гарнир ОБЯЗАТЕЛЕН + опционально крупа/паста).
- dish_name — на русском, конкретное и узнаваемое название.
- Чередуй белки между обедами и ужинами разных дней.
- Не повторяй dish_name в рамках одного меню.
- Никаких пояснений до или после JSON. Только JSON.
```

- [x] **Step 2: Commit**

```bash
git add core/prompts/menu_planner.md
git commit -m "feat(prompts): add menu_planner prompt"
```

---

### Task 1.6: Implement `core/repositories.py` — menu operations

> **Status:** ✅ DONE (2026-05-26). Used `datetime.now(UTC)` instead of deprecated `utcnow()`. Recipe deletion in `update_meal` uses a direct select (instead of relationship access) to avoid async lazy-load issues.

**Files:**
- Create: `core/repositories.py`

- [x] **Step 1: Write repository functions for menus**

```python
# core/repositories.py
from datetime import date as DateType, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db import Meal, MealSlot, Menu, MenuStatus, ProteinKind, Recipe


async def create_draft_menu(
    session: AsyncSession,
    *,
    family_id: int,
    start_date: DateType,
    days_count: int,
    meals: list[dict],
) -> Menu:
    """
    Create a menu in 'draft' status with all its meals.
    `meals` is a list of dicts matching MealDTO (date, slot, dish_name, side_dishes, protein_kind).
    """
    menu = Menu(
        family_id=family_id,
        start_date=start_date,
        days_count=days_count,
        status=MenuStatus.draft,
    )
    session.add(menu)
    await session.flush()

    for m in meals:
        meal = Meal(
            menu_id=menu.id,
            date=m["date"],
            slot=MealSlot(m["slot"]),
            dish_name=m["dish_name"],
            side_dishes=m.get("side_dishes", []),
            protein_kind=ProteinKind(m["protein_kind"]),
        )
        session.add(meal)
    await session.flush()
    return menu


async def approve_menu(session: AsyncSession, menu_id: int) -> None:
    """Mark menu as active. Archive any previously active menu in the same family."""
    menu = await session.get(Menu, menu_id)
    if menu is None:
        return
    await session.execute(
        update(Menu)
        .where(Menu.family_id == menu.family_id, Menu.status == MenuStatus.active)
        .values(status=MenuStatus.archived)
    )
    menu.status = MenuStatus.active
    menu.approved_at = datetime.utcnow()


async def get_active_menu(session: AsyncSession, family_id: int) -> Menu | None:
    stmt = (
        select(Menu)
        .where(Menu.family_id == family_id, Menu.status == MenuStatus.active)
        .options(selectinload(Menu.meals))
        .order_by(Menu.approved_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_menu_with_meals(session: AsyncSession, menu_id: int) -> Menu | None:
    stmt = (
        select(Menu)
        .where(Menu.id == menu_id)
        .options(selectinload(Menu.meals))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_meal(session: AsyncSession, meal_id: int) -> Meal | None:
    return await session.get(Meal, meal_id)


async def get_meals_for_date(
    session: AsyncSession, family_id: int, on_date: DateType
) -> list[Meal]:
    stmt = (
        select(Meal)
        .join(Menu)
        .where(
            Menu.family_id == family_id,
            Menu.status == MenuStatus.active,
            Meal.date == on_date,
        )
        .order_by(Meal.slot)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_meal(
    session: AsyncSession,
    meal_id: int,
    *,
    dish_name: str,
    side_dishes: list[str],
    protein_kind: ProteinKind,
) -> Meal:
    meal = await session.get(Meal, meal_id)
    if meal is None:
        raise ValueError(f"Meal {meal_id} not found")
    meal.dish_name = dish_name
    meal.side_dishes = side_dishes
    meal.protein_kind = protein_kind
    # Drop cached recipe (if any) since the meal changed
    if meal.recipe is not None:
        await session.delete(meal.recipe)
    await session.flush()
    return meal


async def save_recipe(
    session: AsyncSession,
    meal_id: int,
    *,
    content_md: str,
    ingredients: list[dict],
    prep_minutes: int,
) -> Recipe:
    recipe = Recipe(
        meal_id=meal_id,
        content_md=content_md,
        ingredients=ingredients,
        prep_minutes=prep_minutes,
    )
    session.add(recipe)
    await session.flush()
    return recipe


async def get_recipe(session: AsyncSession, meal_id: int) -> Recipe | None:
    stmt = select(Recipe).where(Recipe.meal_id == meal_id)
    return (await session.execute(stmt)).scalar_one_or_none()
```

- [x] **Step 2: Commit**

```bash
git add core/repositories.py
git commit -m "feat(repo): add menu/meal/recipe repository functions"
```

---

### Task 1.7: Implement `menu_planner.start_planning()` (TDD)

> **Status:** ✅ DONE (2026-05-26). Test passes. Two deviations from plan: (1) service validates `days_count >= 1` (not `in (7,14)`) — the 7/14 choice is enforced by the FSM wizard, so the service stays callable for tests/replacement flows; (2) `meals_payload` uses `model_dump(mode="python")` so `date` stays as `datetime.date` for SQLite Date columns instead of being serialized to ISO strings.

**Files:**
- Create: `core/services/menu_planner.py`
- Test: `tests/integration/test_menu_planner.py`

- [x] **Step 1: Write the failing test**

```python
# tests/integration/test_menu_planner.py
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core.db import MealSlot, ProteinKind
from core.llm import LLMResponse
from core.services import menu_planner
from core.services.family_service import get_or_create_family


@pytest.mark.asyncio
async def test_start_planning_creates_draft_menu(db_session, monkeypatch):
    """LLM is mocked; service should parse JSON and save a draft menu."""
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    mock_llm_response = LLMResponse(
        text='{"meals": ['
             '{"date": "2026-05-26", "slot": "lunch", "dish_name": "Курица",'
             ' "side_dishes": ["рис"], "protein_kind": "chicken"},'
             '{"date": "2026-05-26", "slot": "dinner", "dish_name": "Лосось",'
             ' "side_dishes": ["брокколи"], "protein_kind": "fish"}'
             ']}',
        stop_reason="end_turn",
    )

    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(return_value=mock_llm_response)
    monkeypatch.setattr(menu_planner, "get_llm_client", lambda: fake_client)

    menu = await menu_planner.start_planning(
        db_session,
        family_id=family.id,
        days_count=1,
        start_date=date(2026, 5, 26),
        fridge_text="курица, рис",
    )

    assert menu.id is not None
    assert menu.days_count == 1
    assert menu.status.value == "draft"
    assert len(menu.meals) == 2
    slots = {m.slot for m in menu.meals}
    assert slots == {MealSlot.lunch, MealSlot.dinner}
```

- [x] **Step 2: Run test, verify it fails**

Run: `pytest tests/integration/test_menu_planner.py -v`
Expected: FAIL (ImportError)

- [x] **Step 3: Implement `core/services/menu_planner.py`**

```python
# core/services/menu_planner.py
from datetime import date as DateType
from functools import lru_cache

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Menu
from core.exceptions import LLMInvalidResponse, MenuNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMMenuResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def start_planning(
    session: AsyncSession,
    *,
    family_id: int,
    days_count: int,
    start_date: DateType,
    fridge_text: str,
) -> Menu:
    """Generate a draft menu via Claude and persist it. Returns Menu (status=draft)."""
    if days_count not in (7, 14):
        raise ValueError("days_count must be 7 or 14")

    user_msg = (
        f"Дата начала: {start_date.isoformat()}. "
        f"Дней: {days_count}. "
        f"В холодильнике: {fridge_text or 'ничего особенного'}. "
        f"Сгенерируй меню."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("menu_planner"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4096,
    )
    logger.info("menu generation: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMMenuResponse.model_validate(data)
    except Exception as e:
        logger.warning("first parse failed, retrying with hint: {}", e)
        retry_msg = (
            user_msg
            + "\n\nПРЕДЫДУЩИЙ ОТВЕТ НЕВАЛИДЕН. Верни СТРОГО JSON без markdown."
        )
        resp = await llm.chat(
            system_blocks=build_system_blocks("menu_planner"),
            messages=[{"role": "user", "content": retry_msg}],
            max_tokens=4096,
        )
        try:
            data = parse_json_response(resp.text)
            validated = LLMMenuResponse.model_validate(data)
        except Exception as e2:
            raise LLMInvalidResponse(f"Failed to parse menu after retry: {e2}") from e2

    meals_payload = [m.model_dump(mode="json") for m in validated.meals]
    menu = await repositories.create_draft_menu(
        session,
        family_id=family_id,
        start_date=start_date,
        days_count=days_count,
        meals=meals_payload,
    )
    await session.refresh(menu, attribute_names=["meals"])
    return menu


async def approve(session: AsyncSession, menu_id: int) -> None:
    menu = await repositories.get_menu_with_meals(session, menu_id)
    if menu is None:
        raise MenuNotFound(f"Menu {menu_id} not found")
    await repositories.approve_menu(session, menu_id)


async def get_active(session: AsyncSession, family_id: int) -> Menu | None:
    return await repositories.get_active_menu(session, family_id)
```

- [x] **Step 4: Run test, verify it passes**

Run: `pytest tests/integration/test_menu_planner.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add core/services/menu_planner.py tests/integration/test_menu_planner.py
git commit -m "feat(menu): add menu_planner.start_planning with JSON retry"
```

---

### Task 1.8: Implement `dish_replacer.replace_meal()` (TDD)

> **Status:** ✅ DONE (2026-05-26). Test passes. While building this, hit async-lazy-load on `menu.meals` from `create_draft_menu`; folded the refresh into the repository function itself so all callers get the loaded relationship. Removed the now-redundant refresh from `menu_planner.start_planning`.

**Files:**
- Create: `core/services/dish_replacer.py`
- Test: `tests/integration/test_dish_replacer.py`

- [x] **Step 1: Write the failing test**

```python
# tests/integration/test_dish_replacer.py
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core import repositories
from core.db import MealSlot, ProteinKind
from core.llm import LLMResponse
from core.services import dish_replacer
from core.services.family_service import get_or_create_family


@pytest.mark.asyncio
async def test_replace_meal_swaps_dish(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {"date": date(2026, 5, 26), "slot": "lunch",
             "dish_name": "Курица", "side_dishes": ["рис"], "protein_kind": "chicken"},
        ],
    )
    meal_id = menu.meals[0].id

    new_dish_json = (
        '{"dish_name": "Жареный лосось", '
        '"side_dishes": ["брокколи на пару"], '
        '"protein_kind": "fish"}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=new_dish_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(dish_replacer, "get_llm_client", lambda: fake_client)

    meal = await dish_replacer.replace_meal(db_session, meal_id=meal_id, hint="с рыбой")
    assert meal.dish_name == "Жареный лосось"
    assert meal.protein_kind == ProteinKind.fish
```

- [x] **Step 2: Write the dish_replacer prompt**

Create `core/prompts/dish_replacer.md`:

```markdown
# Задача: замена блюда

Тебе передадут текущее блюдо в меню и пожелания пользователя по замене.
Предложи ОДНО новое блюдо, удовлетворяющее правилам из контекста семьи.

## Формат ответа

Верни СТРОГО валидный JSON, без markdown-фенсов, без пояснений:

```
{
  "dish_name": "Название",
  "side_dishes": ["гарнир1", "гарнир2"],
  "protein_kind": "chicken" | "fish" | "seafood" | "beef" | "pork" | "vegetarian" | "mixed"
}
```
```

- [x] **Step 3: Implement `core/services/dish_replacer.py`**

```python
# core/services/dish_replacer.py
from functools import lru_cache

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, ProteinKind
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _ReplacementSchema(BaseModel):
    dish_name: str
    side_dishes: list[str]
    protein_kind: ProteinKind


async def replace_meal(
    session: AsyncSession, *, meal_id: int, hint: str | None
) -> Meal:
    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Текущее блюдо: {meal.dish_name} (гарниры: {', '.join(meal.side_dishes or [])}, "
        f"белок: {meal.protein_kind.value}). "
        f"Дата: {meal.date.isoformat()}, приём: {meal.slot.value}. "
        f"Пожелание пользователя: {hint or 'просто другое блюдо'}. "
        f"Предложи замену."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("dish_replacer"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=512,
    )
    logger.info("dish replace: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        new = _ReplacementSchema.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse replacement: {e}") from e

    return await repositories.update_meal(
        session,
        meal_id=meal_id,
        dish_name=new.dish_name,
        side_dishes=new.side_dishes,
        protein_kind=new.protein_kind,
    )
```

- [x] **Step 4: Run test, verify it passes**

Run: `pytest tests/integration/test_dish_replacer.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add core/services/dish_replacer.py core/prompts/dish_replacer.md tests/integration/test_dish_replacer.py
git commit -m "feat(menu): add dish_replacer service"
```

---

### Task 1.9: Build `/plan` FSM wizard

> **Status:** ✅ DONE (2026-05-26). Imports verified; ruff clean. Step 5 (Telegram smoke test) deferred — requires real BOT_TOKEN.

**Files:**
- Create: `bot/fsm.py`
- Create: `bot/keyboards.py`
- Create: `bot/handlers/plan.py`
- Modify: `bot/main.py` — register plan router

- [x] **Step 1: Write FSM states (`bot/fsm.py`)**

```python
# bot/fsm.py
from aiogram.fsm.state import State, StatesGroup


class PlanWizard(StatesGroup):
    ask_days = State()
    ask_fridge = State()
    draft_review = State()
    ask_which_meal = State()
    ask_replace_hint = State()
```

- [x] **Step 2: Write keyboards (`bot/keyboards.py`)**

```python
# bot/keyboards.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def kb_days() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="7 дней", callback_data="plan:days:7")
    b.button(text="14 дней", callback_data="plan:days:14")
    return b.as_markup()


def kb_draft_review(menu_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Утвердить", callback_data=f"plan:approve:{menu_id}")
    b.button(text="🔁 Заменить блюдо", callback_data=f"plan:replace_pick:{menu_id}")
    b.button(text="❌ Отмена", callback_data=f"plan:cancel:{menu_id}")
    b.adjust(1)
    return b.as_markup()


def kb_meals_for_replace(meals) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in meals:
        label = f"{m.date.strftime('%a %d.%m')} {m.slot.value} — {m.dish_name[:25]}"
        b.button(text=label, callback_data=f"plan:replace_meal:{m.id}")
    b.adjust(1)
    return b.as_markup()
```

- [x] **Step 3: Write `bot/handlers/plan.py`**

```python
# bot/handlers/plan.py
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.fsm import PlanWizard
from bot.keyboards import kb_days, kb_draft_review, kb_meals_for_replace
from core import repositories
from core.db import Family
from core.exceptions import LLMError
from core.services import dish_replacer, menu_planner

router = Router()


def _format_menu(menu) -> str:
    """Render a Menu with meals into a readable Russian text block."""
    lines = [f"<b>Меню на {menu.days_count} дн. с {menu.start_date.strftime('%d.%m.%Y')}:</b>", ""]
    current_date = None
    for meal in menu.meals:
        if meal.date != current_date:
            lines.append(f"\n<b>{meal.date.strftime('%a %d.%m')}</b>")
            current_date = meal.date
        slot_ru = "Обед" if meal.slot.value == "lunch" else "Ужин"
        sides = ", ".join(meal.side_dishes) if meal.side_dishes else ""
        line = f"  • {slot_ru}: {meal.dish_name}"
        if sides:
            line += f" + {sides}"
        lines.append(line)
    return "\n".join(lines)


@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PlanWizard.ask_days)
    await message.answer("На сколько дней планируем?", reply_markup=kb_days())


@router.callback_query(PlanWizard.ask_days, F.data.startswith("plan:days:"))
async def cb_days(
    cb: CallbackQuery, state: FSMContext
) -> None:
    days = int(cb.data.split(":")[2])
    await state.update_data(days_count=days)
    await state.set_state(PlanWizard.ask_fridge)
    await cb.message.edit_text(
        f"{days} дней. Что уже есть в холодильнике? "
        "Перечисли через запятую (или напиши «ничего»)."
    )
    await cb.answer()


@router.message(PlanWizard.ask_fridge)
async def msg_fridge(
    message: Message,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    days = data["days_count"]
    fridge_text = message.text or ""
    await message.answer("Генерирую меню, это займёт ~20 секунд...")
    try:
        menu = await menu_planner.start_planning(
            db_session,
            family_id=family.id,
            days_count=days,
            start_date=date.today(),
            fridge_text=fridge_text,
        )
    except LLMError as e:
        logger.exception("LLM failed: {}", e)
        await message.answer(
            "Что-то пошло не так на стороне LLM. Попробуй /plan ещё раз."
        )
        await state.clear()
        return

    await state.update_data(menu_id=menu.id)
    await state.set_state(PlanWizard.draft_review)
    await message.answer(
        _format_menu(menu), reply_markup=kb_draft_review(menu.id)
    )


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:approve:"))
async def cb_approve(
    cb: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    menu_id = int(cb.data.split(":")[2])
    await menu_planner.approve(db_session, menu_id)
    await cb.message.edit_text(
        cb.message.html_text + "\n\n✅ Меню утверждено.",
    )
    await state.clear()
    await cb.answer("Утверждено")


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:cancel:"))
async def cb_cancel(
    cb: CallbackQuery, state: FSMContext
) -> None:
    await cb.message.edit_text("Отменено.")
    await state.clear()
    await cb.answer()


@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:replace_pick:"))
async def cb_replace_pick(
    cb: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    menu_id = int(cb.data.split(":")[2])
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    if menu is None:
        await cb.answer("Меню не найдено")
        return
    await state.set_state(PlanWizard.ask_which_meal)
    await cb.message.answer(
        "Какое блюдо заменить?", reply_markup=kb_meals_for_replace(menu.meals)
    )
    await cb.answer()


@router.callback_query(PlanWizard.ask_which_meal, F.data.startswith("plan:replace_meal:"))
async def cb_pick_meal(cb: CallbackQuery, state: FSMContext) -> None:
    meal_id = int(cb.data.split(":")[2])
    await state.update_data(meal_id_to_replace=meal_id)
    await state.set_state(PlanWizard.ask_replace_hint)
    await cb.message.answer(
        "Какое пожелание к новому блюду? (например, 'с рыбой', 'попроще', "
        "'без курицы'). Напиши свободным текстом или 'без пожеланий'."
    )
    await cb.answer()


@router.message(PlanWizard.ask_replace_hint)
async def msg_replace_hint(
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    meal_id = data["meal_id_to_replace"]
    menu_id = data["menu_id"]
    hint = message.text or "без пожеланий"
    await message.answer("Подбираю замену...")
    try:
        await dish_replacer.replace_meal(db_session, meal_id=meal_id, hint=hint)
    except LLMError as e:
        logger.exception("replace failed: {}", e)
        await message.answer("Не получилось. Попробуй ещё раз.")
        return

    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    await state.set_state(PlanWizard.draft_review)
    await message.answer(
        "Готово, обновил:\n\n" + _format_menu(menu),
        reply_markup=kb_draft_review(menu_id),
    )
```

- [x] **Step 4: Register plan router in `bot/main.py`**

Add to the `main()` function in `bot/main.py`, after `dp.include_router(start_handler.router)`:

```python
from bot.handlers import plan as plan_handler
dp.include_router(plan_handler.router)
```

- [ ] **Step 5: Manual smoke test** (deferred — needs real BOT_TOKEN)

Run: `python -m bot.main`. From Telegram run `/plan`, click "7 дней", type "курица, рис", wait, click "Утвердить".
Expected: Bot generates a menu, displays it formatted, "Утвердить" finalizes it. Check `data/chef.db`:

```bash
sqlite3 data/chef.db "SELECT id, days_count, status FROM menus;"
sqlite3 data/chef.db "SELECT date, slot, dish_name FROM meals ORDER BY date, slot;"
```

- [x] **Step 6: Commit**

```bash
git add bot/fsm.py bot/keyboards.py bot/handlers/plan.py bot/main.py
git commit -m "feat(bot): add /plan FSM wizard with approve and replace"
```

---

### Task 1.10: Implement `/menu` and `/today` handlers

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline; ruff clean. Step 3 (smoke test) deferred — needs real BOT_TOKEN.

**Files:**
- Create: `bot/handlers/menu.py`
- Modify: `bot/main.py` — register router

- [x] **Step 1: Write `bot/handlers/menu.py`**

```python
# bot/handlers/menu.py
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.plan import _format_menu
from core import repositories
from core.db import Family

router = Router()


@router.message(Command("menu"))
async def cmd_menu(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    menu = await repositories.get_active_menu(db_session, family.id)
    if menu is None:
        await message.answer(
            "Активного меню нет. Запусти /plan, чтобы создать."
        )
        return
    await message.answer(_format_menu(menu))


@router.message(Command("today"))
async def cmd_today(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    meals = await repositories.get_meals_for_date(
        db_session, family.id, date.today()
    )
    if not meals:
        await message.answer(
            "На сегодня в активном меню ничего не запланировано. "
            "Запусти /plan."
        )
        return
    lines = [f"<b>Сегодня ({date.today().strftime('%d.%m.%Y')}):</b>", ""]
    for m in meals:
        slot_ru = "Обед" if m.slot.value == "lunch" else "Ужин"
        sides = ", ".join(m.side_dishes) if m.side_dishes else ""
        line = f"<b>{slot_ru}:</b> {m.dish_name}"
        if sides:
            line += f" + {sides}"
        lines.append(line)
    await message.answer("\n".join(lines))
```

- [x] **Step 2: Register in `bot/main.py`**

Add after plan router registration:

```python
from bot.handlers import menu as menu_handler
dp.include_router(menu_handler.router)
```

- [ ] **Step 3: Manual smoke test** (deferred — needs real BOT_TOKEN)

Run bot, send `/menu` and `/today`. Expected: shows active menu / today's meals.

- [x] **Step 4: Commit**

```bash
git add bot/handlers/menu.py bot/main.py
git commit -m "feat(bot): add /menu and /today handlers"
```

---

### Task 1.11: Write `core/prompts/recipe.md`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline.

**Files:**
- Create: `core/prompts/recipe.md`

- [x] **Step 1: Write recipe prompt**

```markdown
# Задача: подробный рецепт

Тебе передадут блюдо из меню (название, гарниры). Напиши подробный пошаговый
рецепт на 2 порции, используя продукты и технику из контекста семьи.

## Формат ответа

Верни СТРОГО валидный JSON, БЕЗ markdown-фенсов, БЕЗ пояснений:

```
{
  "content_md": "Markdown-текст рецепта: ингредиенты списком + шаги нумерованным списком",
  "ingredients": [
    {"name": "Куриные бёдра", "quantity": "500", "unit": "г", "store": "Makro"}
  ],
  "prep_minutes": 30
}
```

## Требования

- content_md: полностью на русском, читабельный markdown.
- ingredients: каждый ингредиент с количеством на 2 порции. Поле "store" одно из:
  "Makro", "Villa Market", "Lotus's", "7-Eleven", "Кладовка" (последнее — для
  базовой кладовки, не нужно покупать).
- prep_minutes — реалистичная оценка АКТИВНОЙ готовки (не больше 40 для основного блюда).
- НЕ используй лук в салатах. НЕ используй индейку. НЕ используй чеснок в блюдах.
```

- [x] **Step 2: Commit**

```bash
git add core/prompts/recipe.md
git commit -m "feat(prompts): add recipe.md"
```

---

### Task 1.12: Implement `recipe_service.get_recipe()` (TDD)

> **Status:** ✅ DONE (2026-05-26). Test passes (including the cache-hit assertion on the second call).

**Files:**
- Create: `core/services/recipe_service.py`
- Test: `tests/integration/test_recipe_service.py`

- [x] **Step 1: Write the failing test**

```python
# tests/integration/test_recipe_service.py
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core import repositories
from core.llm import LLMResponse
from core.services import recipe_service
from core.services.family_service import get_or_create_family


@pytest.mark.asyncio
async def test_get_recipe_generates_and_caches(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {"date": date(2026, 5, 26), "slot": "lunch",
             "dish_name": "Курица в airfryer",
             "side_dishes": ["гречка"], "protein_kind": "chicken"},
        ],
    )
    meal_id = menu.meals[0].id

    recipe_json = (
        '{"content_md": "# Курица\\n\\n1. Замариновать\\n2. Жарить 25 минут",'
        ' "ingredients": [{"name": "куриные бёдра", "quantity": "500", "unit": "г",'
        ' "store": "Makro"}], "prep_minutes": 30}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=recipe_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(recipe_service, "get_llm_client", lambda: fake_client)

    recipe1 = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    assert "Курица" in recipe1.content_md
    assert recipe1.prep_minutes == 30

    # Second call should hit cache (no LLM call)
    fake_client.chat.reset_mock()
    recipe2 = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    assert recipe2.id == recipe1.id
    fake_client.chat.assert_not_called()
```

- [x] **Step 2: Implement `core/services/recipe_service.py`**

```python
# core/services/recipe_service.py
from datetime import date as DateType
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core import repositories
from core.db import MealSlot, Recipe
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMRecipeResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def get_recipe(session: AsyncSession, *, meal_id: int) -> Recipe:
    """Return cached recipe or generate via LLM."""
    cached = await repositories.get_recipe(session, meal_id)
    if cached is not None:
        return cached

    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Блюдо: {meal.dish_name}. "
        f"Гарниры: {', '.join(meal.side_dishes or [])}. "
        f"Дай мне подробный рецепт на 2 порции."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("recipe"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )
    logger.info("recipe gen: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMRecipeResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse recipe: {e}") from e

    return await repositories.save_recipe(
        session,
        meal_id=meal_id,
        content_md=validated.content_md,
        ingredients=[i.model_dump() for i in validated.ingredients],
        prep_minutes=validated.prep_minutes,
    )


async def get_current_meal(
    session: AsyncSession, *, family_id: int
) -> int | None:
    """Determine the current meal slot by Bangkok time and return its meal_id.

    Rule:
      • before 16:00 → today's lunch
      • after 16:00 → today's dinner
    """
    tz = ZoneInfo(get_settings().timezone)
    now = datetime.now(tz)
    today = now.date()
    target_slot = MealSlot.lunch if now.hour < 16 else MealSlot.dinner

    meals = await repositories.get_meals_for_date(session, family_id, today)
    for m in meals:
        if m.slot == target_slot:
            return m.id
    return None
```

- [x] **Step 3: Run test, verify it passes**

Run: `pytest tests/integration/test_recipe_service.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add core/services/recipe_service.py tests/integration/test_recipe_service.py
git commit -m "feat(recipe): add recipe_service with caching and current-meal logic"
```

---

### Task 1.13: Implement `/recipe` handler

> **Status:** ✅ DONE (2026-05-26). Imports verified; ruff clean. Step 3 (smoke test) deferred — needs real BOT_TOKEN. **Phase 1 complete: 14/14 tests passing.**

**Files:**
- Create: `bot/handlers/recipe.py`
- Modify: `bot/main.py`

- [x] **Step 1: Write `bot/handlers/recipe.py`**

```python
# bot/handlers/recipe.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family
from core.exceptions import LLMError
from core.services import recipe_service

router = Router()


@router.message(Command("recipe"))
async def cmd_recipe(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    meal_id = await recipe_service.get_current_meal(db_session, family_id=family.id)
    if meal_id is None:
        await message.answer(
            "На сегодня в активном меню нет блюда для текущего времени. "
            "Запусти /plan."
        )
        return
    await message.answer("Готовлю рецепт...")
    try:
        recipe = await recipe_service.get_recipe(db_session, meal_id=meal_id)
    except LLMError as e:
        logger.exception("recipe error: {}", e)
        await message.answer("Не удалось сгенерировать рецепт. Попробуй позже.")
        return
    await message.answer(
        f"{recipe.content_md}\n\n_Время активной готовки: ~{recipe.prep_minutes} мин_"
    )
```

- [x] **Step 2: Register in `bot/main.py`**

```python
from bot.handlers import recipe as recipe_handler
dp.include_router(recipe_handler.router)
```

- [ ] **Step 3: Manual smoke test** (deferred — needs real BOT_TOKEN)

Send `/recipe` to bot. Expected: ingredient list and steps for the meal closest to current time.

- [x] **Step 4: Commit**

```bash
git add bot/handlers/recipe.py bot/main.py
git commit -m "feat(bot): add /recipe handler"
```

---

### Phase 1 — Verification

- [ ] All integration tests pass: `pytest`
- [ ] `/plan` creates a real menu via Claude
- [ ] "Утвердить" finalizes menu (status=active in DB)
- [ ] "Заменить блюдо" → выбор → текст пожелания → меню обновляется
- [ ] `/menu` shows active menu
- [ ] `/today` shows today's meals
- [ ] `/recipe` generates and caches a recipe; second call doesn't re-call Claude

---

# PHASE 2 — Shopping List

**Goal:** After menu approval, bot builds a shopping list grouped by stores. `/list` shows interactive checkboxes; tapping toggles purchased status.

---

### Task 2.1: Add `shopping_lists` and `shopping_items` ORM models + migration

> **Status:** ✅ DONE (2026-05-26). Migration applied; 8 tables present. `Store` uses `enum.StrEnum` for consistency with the rest of the schema.

**Files:**
- Modify: `core/db.py`
- Create: `alembic/versions/0003_shopping.py` (via autogenerate)

- [x] **Step 1: Append to `core/db.py`**

```python
class Store(str, enum.Enum):
    makro = "makro"
    villa = "villa"
    lotus = "lotus"
    seven_eleven = "seven_eleven"
    other = "other"


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False)
    created_at: Mapped[CreatedAt]


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shopping_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("shopping_lists.id")
    )
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    store: Mapped[Store] = mapped_column(
        Enum(Store), default=Store.other, nullable=False
    )
    bought: Mapped[bool] = mapped_column(default=False, nullable=False)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[CreatedAt]
```

- [x] **Step 2: Generate and apply migration**

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic revision --autogenerate -m "add shopping tables"`
Rename to `0003_shopping.py`.

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic upgrade head`

- [x] **Step 3: Commit**

```bash
git add core/db.py alembic/versions/0003_shopping.py
git commit -m "feat(db): add shopping_lists and shopping_items"
```

---

### Task 2.2: Write `core/prompts/shopping_list.md`

> **Status:** ✅ DONE (2026-05-26). Pure paste task done inline.

**Files:**
- Create: `core/prompts/shopping_list.md`

- [x] **Step 1: Write prompt**

```markdown
# Задача: сборка списка покупок

Тебе передадут меню (список блюд) и список продуктов из базовой кладовки.
Собери единый список покупок на 2 порции каждого блюда, агрегируя одинаковые
ингредиенты (например, если курица фигурирует в 3 блюдах — суммируй).

## Правила

- ИСКЛЮЧИ продукты из базовой кладовки (они уже есть дома).
- Сгруппируй по магазинам: makro, villa, lotus, seven_eleven, other.
- Mясо/рыба/морепродукты/овощи/крупы → makro по умолчанию.
- Импортные сыры (фета, моцарелла, пармезан), европейская молочка, стейковые
  отруба → villa.
- Готовая кукуруза, мелочи → seven_eleven.
- Lotus's — альтернатива makro, используй если в makro нет.

## Формат ответа

Верни СТРОГО валидный JSON, без markdown-фенсов, без пояснений:

```
{
  "items": [
    {"name": "Куриные бёдра", "quantity": "1 кг", "store": "makro"},
    {"name": "Фета", "quantity": "200 г", "store": "villa"}
  ]
}
```

## Требования к именам

- Конкретные, на русском, в именительном падеже.
- В quantity — число + единица (г, кг, шт, мл, л, упаковка).
- Если ингредиент непонятен или его не нужно покупать (входит в кладовку) — пропусти.
```

- [x] **Step 2: Commit**

```bash
git add core/prompts/shopping_list.md
git commit -m "feat(prompts): add shopping_list.md"
```

---

### Task 2.3: Implement `shopping_list.build_from_menu()` (TDD)

**Files:**
- Create: `core/services/shopping_list.py`
- Modify: `core/repositories.py` — add shopping repo funcs
- Test: `tests/integration/test_shopping_list.py`
- Modify: `core/models.py` — add `LLMShoppingResponse`

- [ ] **Step 1: Append repo funcs to `core/repositories.py`**

```python
from core.db import ShoppingItem, ShoppingList, Store


async def create_shopping_list(
    session: AsyncSession,
    *,
    menu_id: int,
    family_id: int,
    items: list[dict],
) -> ShoppingList:
    sl = ShoppingList(menu_id=menu_id)
    session.add(sl)
    await session.flush()
    for item in items:
        si = ShoppingItem(
            shopping_list_id=sl.id,
            family_id=family_id,
            name=item["name"],
            quantity=item.get("quantity", ""),
            store=Store(item.get("store", "other")),
        )
        session.add(si)
    await session.flush()
    return sl


async def get_open_shopping_items(
    session: AsyncSession, *, family_id: int
) -> list[ShoppingItem]:
    """Return all unbought items for the family (menu-list items + standalone)."""
    stmt = (
        select(ShoppingItem)
        .where(ShoppingItem.family_id == family_id, ShoppingItem.bought.is_(False))
        .order_by(ShoppingItem.store, ShoppingItem.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_shopping_item(
    session: AsyncSession, item_id: int
) -> ShoppingItem | None:
    return await session.get(ShoppingItem, item_id)


async def mark_shopping_item_bought(
    session: AsyncSession, item_id: int, *, bought: bool = True
) -> ShoppingItem | None:
    item = await session.get(ShoppingItem, item_id)
    if item is None:
        return None
    item.bought = bought
    item.bought_at = datetime.utcnow() if bought else None
    return item
```

- [ ] **Step 2: Append to `core/models.py`**

```python
class ShoppingItemDTO(BaseModel):
    name: str
    quantity: str = ""
    store: str = "other"


class LLMShoppingResponse(BaseModel):
    items: list[ShoppingItemDTO]
```

- [ ] **Step 3: Write the failing test**

```python
# tests/integration/test_shopping_list.py
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core import repositories
from core.llm import LLMResponse
from core.services import shopping_list
from core.services.family_service import get_or_create_family


@pytest.mark.asyncio
async def test_build_from_menu_creates_grouped_items(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {"date": date(2026, 5, 26), "slot": "lunch",
             "dish_name": "Курица", "side_dishes": ["рис"], "protein_kind": "chicken"},
            {"date": date(2026, 5, 26), "slot": "dinner",
             "dish_name": "Лосось с фетой", "side_dishes": ["салат"], "protein_kind": "fish"},
        ],
    )

    llm_json = (
        '{"items": ['
        '{"name": "Куриные бёдра", "quantity": "500 г", "store": "makro"},'
        '{"name": "Лосось", "quantity": "300 г", "store": "makro"},'
        '{"name": "Фета", "quantity": "200 г", "store": "villa"}'
        ']}'
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(
        return_value=LLMResponse(text=llm_json, stop_reason="end_turn")
    )
    monkeypatch.setattr(shopping_list, "get_llm_client", lambda: fake_client)

    sl = await shopping_list.build_from_menu(db_session, menu_id=menu.id, family_id=family.id)
    items = await repositories.get_open_shopping_items(db_session, family_id=family.id)
    assert len(items) == 3
    assert any(i.name == "Фета" and i.store.value == "villa" for i in items)
```

- [ ] **Step 4: Implement `core/services/shopping_list.py`**

```python
# core/services/shopping_list.py
from functools import lru_cache

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import ShoppingList
from core.exceptions import LLMInvalidResponse, MenuNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.models import LLMShoppingResponse


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def build_from_menu(
    session: AsyncSession, *, menu_id: int, family_id: int
) -> ShoppingList:
    menu = await repositories.get_menu_with_meals(session, menu_id)
    if menu is None:
        raise MenuNotFound(f"Menu {menu_id} not found")

    meals_summary = "\n".join(
        f"- {m.date.isoformat()} {m.slot.value}: {m.dish_name} "
        f"(гарниры: {', '.join(m.side_dishes or [])})"
        for m in menu.meals
    )
    user_msg = (
        f"Меню на {menu.days_count} дней:\n{meals_summary}\n\n"
        f"Сгенерируй список покупок (на 2 порции каждого блюда). "
        f"Исключи продукты из кладовки."
    )

    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("shopping_list"),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )
    logger.info("shopping list: in={} out={}", resp.tokens_in, resp.tokens_out)

    try:
        data = parse_json_response(resp.text)
        validated = LLMShoppingResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse shopping list: {e}") from e

    items_payload = [i.model_dump() for i in validated.items]
    return await repositories.create_shopping_list(
        session, menu_id=menu_id, family_id=family_id, items=items_payload
    )


async def get_open_items(session: AsyncSession, *, family_id: int):
    return await repositories.get_open_shopping_items(session, family_id=family_id)


async def toggle_bought(
    session: AsyncSession, *, item_id: int
):
    item = await repositories.get_shopping_item(session, item_id)
    if item is None:
        return None
    return await repositories.mark_shopping_item_bought(
        session, item_id, bought=not item.bought
    )
```

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/integration/test_shopping_list.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/services/shopping_list.py core/repositories.py core/models.py tests/integration/test_shopping_list.py
git commit -m "feat(shopping): add shopping_list.build_from_menu"
```

---

### Task 2.4: Trigger shopping-list build after menu approval

**Files:**
- Modify: `bot/handlers/plan.py` — call `shopping_list.build_from_menu` in approve handler

- [ ] **Step 1: Update `cb_approve` in `bot/handlers/plan.py`**

Replace the existing `cb_approve` with:

```python
@router.callback_query(PlanWizard.draft_review, F.data.startswith("plan:approve:"))
async def cb_approve(
    cb: CallbackQuery,
    state: FSMContext,
    family: Family,
    db_session: AsyncSession,
) -> None:
    from core.services import shopping_list as shopping_service
    menu_id = int(cb.data.split(":")[2])
    await menu_planner.approve(db_session, menu_id)
    await cb.message.edit_text(
        cb.message.html_text + "\n\n✅ Меню утверждено. Собираю список покупок..."
    )
    try:
        await shopping_service.build_from_menu(
            db_session, menu_id=menu_id, family_id=family.id
        )
        await cb.message.answer(
            "📋 Список покупок готов. Открыть: /list"
        )
    except LLMError as e:
        logger.exception("shopping list build failed: {}", e)
        await cb.message.answer(
            "Меню утверждено, но список покупок не собрался. Попробуй позже."
        )
    await state.clear()
    await cb.answer("Утверждено")
```

- [ ] **Step 2: Manual smoke test**

Run `/plan` → 7 дней → "ничего" → утвердить. Bot should respond with "Список покупок готов".

- [ ] **Step 3: Commit**

```bash
git add bot/handlers/plan.py
git commit -m "feat(bot): trigger shopping-list build on menu approval"
```

---

### Task 2.5: Implement `/list` handler with inline checkboxes

**Files:**
- Create: `bot/handlers/shopping.py`
- Modify: `bot/keyboards.py` — add `kb_shopping_list`
- Modify: `bot/main.py` — register router

- [ ] **Step 1: Append to `bot/keyboards.py`**

```python
def kb_shopping_list(items) -> InlineKeyboardMarkup:
    """One button per item. Checkbox in label shows bought state."""
    b = InlineKeyboardBuilder()
    for item in items:
        mark = "✅" if item.bought else "☐"
        label = f"{mark} {item.name}"
        if item.quantity:
            label += f" — {item.quantity}"
        b.button(text=label, callback_data=f"shop:toggle:{item.id}")
    b.adjust(1)
    return b.as_markup()


STORE_LABELS = {
    "makro": "🟧 Makro",
    "villa": "🟦 Villa Market",
    "lotus": "🟩 Lotus's",
    "seven_eleven": "🟥 7-Eleven",
    "other": "⚪ Прочее",
}
```

- [ ] **Step 2: Write `bot/handlers/shopping.py`**

```python
# bot/handlers/shopping.py
from collections import defaultdict

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards import STORE_LABELS, kb_shopping_list
from core.db import Family
from core.services import shopping_list

router = Router()


def _group_by_store(items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.store.value].append(item)
    # Preserve a stable, sensible store order
    ordered_stores = ["makro", "villa", "lotus", "seven_eleven", "other"]
    return [(s, grouped[s]) for s in ordered_stores if grouped[s]]


@router.message(Command("list"))
async def cmd_list(
    message: Message, family: Family, db_session: AsyncSession
) -> None:
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    if not items:
        await message.answer(
            "Незакрытых пунктов нет. Запусти /plan, чтобы создать меню и список."
        )
        return

    grouped = _group_by_store(items)
    for store_key, store_items in grouped:
        await message.answer(
            f"<b>{STORE_LABELS.get(store_key, store_key)}</b>",
            reply_markup=kb_shopping_list(store_items),
        )


@router.callback_query(F.data.startswith("shop:toggle:"))
async def cb_toggle(
    cb: CallbackQuery, family: Family, db_session: AsyncSession
) -> None:
    item_id = int(cb.data.split(":")[2])
    await shopping_list.toggle_bought(db_session, item_id=item_id)
    # Rebuild the same store's keyboard
    items = await shopping_list.get_open_items(db_session, family_id=family.id)
    # Find which store this message originally showed:
    # easiest: rebuild a single keyboard for the *same* set still displayed.
    # We re-query and replace the keyboard with current open items in same store.
    target_item = await _find_item_anywhere(db_session, item_id)
    if target_item is None:
        await cb.answer()
        return
    same_store_items = [i for i in items if i.store == target_item.store]
    if not same_store_items:
        await cb.message.edit_text(
            f"<b>{STORE_LABELS.get(target_item.store.value)}</b>\n\n"
            "Все пункты закрыты ✅"
        )
    else:
        await cb.message.edit_reply_markup(
            reply_markup=kb_shopping_list(same_store_items)
        )
    await cb.answer("Готово")


async def _find_item_anywhere(db_session: AsyncSession, item_id: int):
    """Helper to locate an item by id regardless of bought state."""
    from core import repositories
    return await repositories.get_shopping_item(db_session, item_id)
```

- [ ] **Step 3: Register in `bot/main.py`**

```python
from bot.handlers import shopping as shopping_handler
dp.include_router(shopping_handler.router)
```

- [ ] **Step 4: Manual smoke test**

Run `/plan` → approve → `/list`. Expected: messages grouped by store, each item is a button. Tap an item — its label changes to "✅".

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/shopping.py bot/keyboards.py bot/main.py
git commit -m "feat(bot): add /list handler with interactive checkboxes"
```

---

### Phase 2 — Verification

- [ ] After `/plan` → утвердить, shopping_lists and shopping_items rows are created
- [ ] `/list` shows items grouped by store with checkboxes
- [ ] Tapping an item toggles bought state and updates the keyboard
- [ ] Integration test for `shopping_list.build_from_menu` passes

---

# PHASE 3 — Free Dialog (Tool-Use Agent)

**Goal:** User can write free-text Russian messages; bot uses Claude with a set of tools that wrap core services. The bot understands "что у нас сегодня на ужин?", "поменяй четверг на что-то с рыбой", "добавь молоко в список покупок".

---

### Task 3.1: Add `claude_conversations` table

**Files:**
- Modify: `core/db.py`
- Create: `alembic/versions/0004_conversations.py`

- [ ] **Step 1: Append to `core/db.py`**

```python
class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ClaudeConversation(Base):
    __tablename__ = "claude_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[CreatedAt]
```

- [ ] **Step 2: Generate + apply migration**

Run: `BOT_TOKEN=x ANTHROPIC_API_KEY=x alembic revision --autogenerate -m "add claude_conversations"`
Rename to `0004_conversations.py`. Run `alembic upgrade head`.

- [ ] **Step 3: Append repo funcs**

In `core/repositories.py`:

```python
from core.db import ClaudeConversation, MessageRole


async def append_conversation(
    session: AsyncSession,
    *,
    family_id: int,
    telegram_user_id: int,
    role: MessageRole,
    content: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    session.add(
        ClaudeConversation(
            family_id=family_id,
            telegram_user_id=telegram_user_id,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    await session.flush()


async def recent_conversation(
    session: AsyncSession, *, family_id: int, limit: int = 20
) -> list[ClaudeConversation]:
    stmt = (
        select(ClaudeConversation)
        .where(ClaudeConversation.family_id == family_id)
        .order_by(ClaudeConversation.created_at.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()  # oldest first
    return rows
```

- [ ] **Step 4: Commit**

```bash
git add core/db.py alembic/versions/0004_conversations.py core/repositories.py
git commit -m "feat(db): add claude_conversations table"
```

---

### Task 3.2: Define tools in `core/tools.py`

**Files:**
- Create: `core/tools.py`
- Test: `tests/unit/test_tools.py`

- [ ] **Step 1: Write `core/tools.py`**

```python
# core/tools.py
"""
Tool definitions for the conversation agent.

Each tool maps to a function in core services.
The TOOL_SCHEMAS list is sent to Claude; execute_tool() dispatches a tool call.
"""
from datetime import date as DateType
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.services import dish_replacer, recipe_service

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_active_menu",
        "description": (
            "Возвращает текущее активное меню семьи (список блюд с датами и приёмами). "
            "Используй когда пользователь спрашивает 'что у нас в меню', 'какое меню сейчас'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_meals_for_date",
        "description": (
            "Возвращает блюда на конкретную дату из активного меню. "
            "Используй когда пользователь спрашивает 'что сегодня', 'что на завтра', "
            "'что в четверг'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Дата в формате YYYY-MM-DD",
                }
            },
            "required": ["date"],
        },
    },
    {
        "name": "replace_meal",
        "description": (
            "Заменяет блюдо в активном меню. "
            "Используй когда пользователь просит 'поменяй четверг ужин', "
            "'замени курицу на рыбу' и т.п."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "slot": {"type": "string", "enum": ["lunch", "dinner"]},
                "hint": {
                    "type": "string",
                    "description": "Пожелание пользователя по новому блюду (например, 'с рыбой', 'попроще')",
                },
            },
            "required": ["date", "slot"],
        },
    },
    {
        "name": "get_recipe_for_meal",
        "description": (
            "Возвращает подробный рецепт блюда из активного меню. "
            "Используй когда пользователь просит рецепт конкретного приёма "
            "('дай рецепт сегодняшнего ужина', 'как готовить четверг обед')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "slot": {"type": "string", "enum": ["lunch", "dinner"]},
            },
            "required": ["date", "slot"],
        },
    },
    {
        "name": "add_shopping_item",
        "description": (
            "Добавляет пункт в текущий список покупок (или создаёт standalone-пункт). "
            "Используй когда пользователь говорит 'добавь молоко в список', 'надо купить X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "string", "description": "например '500 г', '1 шт'"},
                "store": {
                    "type": "string",
                    "enum": ["makro", "villa", "lotus", "seven_eleven", "other"],
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "mark_shopping_item_bought",
        "description": (
            "Отмечает пункт списка покупок купленным. "
            "Используй когда пользователь говорит 'я купила X', 'отметь молоко'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_substring": {
                    "type": "string",
                    "description": "Часть названия пункта (бот сам найдёт по подстроке)",
                }
            },
            "required": ["name_substring"],
        },
    },
]


async def execute_tool(
    session: AsyncSession, *, family_id: int, name: str, input: dict[str, Any]
) -> str:
    """Dispatch tool call. Returns string result for the LLM."""
    if name == "get_active_menu":
        return await _tool_get_active_menu(session, family_id)
    if name == "get_meals_for_date":
        return await _tool_get_meals_for_date(session, family_id, input["date"])
    if name == "replace_meal":
        return await _tool_replace_meal(session, family_id, input)
    if name == "get_recipe_for_meal":
        return await _tool_get_recipe_for_meal(session, family_id, input)
    if name == "add_shopping_item":
        return await _tool_add_shopping_item(session, family_id, input)
    if name == "mark_shopping_item_bought":
        return await _tool_mark_bought(session, family_id, input)
    return f"Неизвестный tool: {name}"


async def _tool_get_active_menu(session: AsyncSession, family_id: int) -> str:
    menu = await repositories.get_active_menu(session, family_id)
    if menu is None:
        return "Активного меню нет."
    lines = [f"Меню на {menu.days_count} дн. с {menu.start_date.isoformat()}:"]
    for m in menu.meals:
        sides = ", ".join(m.side_dishes or [])
        lines.append(
            f"  {m.date.isoformat()} {m.slot.value}: {m.dish_name}"
            + (f" (гарниры: {sides})" if sides else "")
        )
    return "\n".join(lines)


async def _tool_get_meals_for_date(
    session: AsyncSession, family_id: int, date_str: str
) -> str:
    try:
        d = DateType.fromisoformat(date_str)
    except ValueError:
        return f"Неверный формат даты: {date_str}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    if not meals:
        return f"На {d.isoformat()} в активном меню ничего."
    lines = [f"{d.isoformat()}:"]
    for m in meals:
        sides = ", ".join(m.side_dishes or [])
        lines.append(
            f"  {m.slot.value}: {m.dish_name}"
            + (f" (гарниры: {sides})" if sides else "")
        )
    return "\n".join(lines)


async def _tool_replace_meal(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    try:
        d = DateType.fromisoformat(input["date"])
    except ValueError:
        return f"Неверный формат даты: {input['date']}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    target = next((m for m in meals if m.slot.value == input["slot"]), None)
    if target is None:
        return f"Не нашёл {input['slot']} на {input['date']} в активном меню."
    new_meal = await dish_replacer.replace_meal(
        session, meal_id=target.id, hint=input.get("hint")
    )
    return (
        f"Заменил {input['slot']} {input['date']} на: {new_meal.dish_name}"
        + (f" (гарниры: {', '.join(new_meal.side_dishes)})" if new_meal.side_dishes else "")
    )


async def _tool_get_recipe_for_meal(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    try:
        d = DateType.fromisoformat(input["date"])
    except ValueError:
        return f"Неверный формат даты: {input['date']}"
    meals = await repositories.get_meals_for_date(session, family_id, d)
    target = next((m for m in meals if m.slot.value == input["slot"]), None)
    if target is None:
        return f"Не нашёл {input['slot']} на {input['date']} в активном меню."
    recipe = await recipe_service.get_recipe(session, meal_id=target.id)
    return f"Рецепт «{target.dish_name}» (~{recipe.prep_minutes} мин):\n\n{recipe.content_md}"


async def _tool_add_shopping_item(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    from core.db import ShoppingItem, Store
    store_value = input.get("store", "other")
    try:
        store = Store(store_value)
    except ValueError:
        store = Store.other
    item = ShoppingItem(
        shopping_list_id=None,  # standalone item
        family_id=family_id,
        name=input["name"],
        quantity=input.get("quantity", ""),
        store=store,
    )
    session.add(item)
    await session.flush()
    return f"Добавил в список: {input['name']}"


async def _tool_mark_bought(
    session: AsyncSession, family_id: int, input: dict
) -> str:
    from sqlalchemy import select
    from core.db import ShoppingItem

    substring = input["name_substring"].lower()
    stmt = select(ShoppingItem).where(
        ShoppingItem.family_id == family_id,
        ShoppingItem.bought.is_(False),
    )
    items = list((await session.execute(stmt)).scalars().all())
    target = next((i for i in items if substring in i.name.lower()), None)
    if target is None:
        return f"Не нашёл незакрытый пункт со словом '{substring}'."
    target.bought = True
    target.bought_at = datetime.utcnow()
    return f"Отметил купленным: {target.name}"
```

- [ ] **Step 2: Write tests**

```python
# tests/unit/test_tools.py
from core.tools import TOOL_SCHEMAS


def test_tool_schemas_have_required_fields():
    for tool in TOOL_SCHEMAS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_tool_names_are_unique():
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert len(names) == len(set(names))
```

- [ ] **Step 3: Run tests, verify they pass**

Run: `pytest tests/unit/test_tools.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/tools.py tests/unit/test_tools.py
git commit -m "feat(tools): add tool schemas and dispatcher for conversation agent"
```

---

### Task 3.3: Write `core/prompts/conversation.md`

**Files:**
- Create: `core/prompts/conversation.md`

- [ ] **Step 1: Write prompt**

```markdown
# Задача: ассистент в диалоге

Ты — помощник по планированию питания. Ты получаешь свободные сообщения от
пользователя на русском языке и можешь использовать tools для выполнения
действий (см. контекст семьи выше для общих правил).

## Поведение

- Отвечай на русском, кратко и по делу.
- Если нужно действие (заменить блюдо, добавить в список, посмотреть меню) —
  используй tools.
- Если можешь ответить без tools — отвечай напрямую.
- НЕ выдумывай, чего нет в меню или списке покупок — сначала проверь tools.
- Если пользователь говорит вещь относительно дат ("четверг", "завтра",
  "сегодня"), сам преобразуй в YYYY-MM-DD на основе текущей даты, которая
  тебе будет передана.

## Стиль

- Без преамбул "конечно!", "сейчас сделаю".
- Просто факт и/или результат действия.
- Если нет активного меню и пользователь спрашивает про блюда — предложи
  запустить /plan.
```

- [ ] **Step 2: Commit**

```bash
git add core/prompts/conversation.md
git commit -m "feat(prompts): add conversation.md"
```

---

### Task 3.4: Implement `conversation.handle_message()` with tool-use loop

**Files:**
- Create: `core/services/conversation.py`
- Test: `tests/integration/test_conversation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_conversation.py
from datetime import date
from unittest.mock import AsyncMock

import pytest

from core import repositories
from core.llm import LLMResponse
from core.services import conversation
from core.services.family_service import get_or_create_family


@pytest.mark.asyncio
async def test_handle_message_no_tool_call(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)

    fake_resp = LLMResponse(
        text="Привет! Чем помочь?",
        tool_calls=[],
        stop_reason="end_turn",
        tokens_in=100,
        tokens_out=10,
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(conversation, "get_llm_client", lambda: fake_client)

    reply = await conversation.handle_message(
        db_session,
        family_id=family.id,
        telegram_user_id=111,
        text="Привет",
    )
    assert reply == "Привет! Чем помочь?"


@pytest.mark.asyncio
async def test_handle_message_uses_tool(db_session, monkeypatch):
    family, _ = await get_or_create_family(db_session, telegram_user_id=111)
    # Set up an active menu
    menu = await repositories.create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=date(2026, 5, 26),
        days_count=1,
        meals=[
            {"date": date(2026, 5, 26), "slot": "lunch",
             "dish_name": "Курица", "side_dishes": ["рис"], "protein_kind": "chicken"},
        ],
    )
    await repositories.approve_menu(db_session, menu.id)

    # First LLM call: tool_use
    tool_call_resp = LLMResponse(
        text="",
        tool_calls=[{"id": "t1", "name": "get_active_menu", "input": {}}],
        stop_reason="tool_use",
    )
    # Second LLM call: end_turn with text
    final_resp = LLMResponse(
        text="В меню: курица.",
        tool_calls=[],
        stop_reason="end_turn",
    )
    fake_client = AsyncMock()
    fake_client.chat = AsyncMock(side_effect=[tool_call_resp, final_resp])
    monkeypatch.setattr(conversation, "get_llm_client", lambda: fake_client)

    reply = await conversation.handle_message(
        db_session,
        family_id=family.id,
        telegram_user_id=111,
        text="что в меню?",
    )
    assert "курица" in reply.lower()
    assert fake_client.chat.call_count == 2
```

- [ ] **Step 2: Implement `core/services/conversation.py`**

```python
# core/services/conversation.py
from datetime import date
from functools import lru_cache

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories, tools
from core.db import MessageRole
from core.exceptions import LLMError
from core.llm import LLMClient, build_system_blocks

MAX_TOOL_ITERATIONS = 5


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


async def handle_message(
    session: AsyncSession,
    *,
    family_id: int,
    telegram_user_id: int,
    text: str,
) -> str:
    """
    Run tool-use loop. Persist user message, assistant reply, and tool calls.
    Return the assistant's final text reply for delivery to Telegram.
    """
    # Persist user turn
    await repositories.append_conversation(
        session,
        family_id=family_id,
        telegram_user_id=telegram_user_id,
        role=MessageRole.user,
        content=text,
    )

    # Load recent history (last ~20 messages)
    history_rows = await repositories.recent_conversation(
        session, family_id=family_id, limit=20
    )
    # Build prior messages for LLM (skip the just-added user message — we add it explicitly)
    prior_messages: list[dict] = []
    for row in history_rows[:-1]:  # exclude current user message
        if row.role == MessageRole.user:
            prior_messages.append({"role": "user", "content": row.content})
        elif row.role == MessageRole.assistant:
            prior_messages.append({"role": "assistant", "content": row.content})
        # tool messages: omit from prior — they were intermediate

    today_str = date.today().isoformat()
    user_msg_with_context = (
        f"[Сегодняшняя дата: {today_str}]\n\n{text}"
    )
    messages: list[dict] = [
        *prior_messages,
        {"role": "user", "content": user_msg_with_context},
    ]

    llm = get_llm_client()
    final_text = ""
    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            resp = await llm.chat(
                system_blocks=build_system_blocks("conversation"),
                messages=messages,
                tools=tools.TOOL_SCHEMAS,
                max_tokens=2048,
            )
        except LLMError as e:
            logger.exception("LLM error in conversation: {}", e)
            return "Не получилось ответить. Попробуй ещё раз."

        if resp.stop_reason == "end_turn" or not resp.tool_calls:
            final_text = resp.text or "Готово."
            break

        # tool_use — execute tools, append both assistant message and tool_result
        assistant_blocks = []
        for tc in resp.tool_calls:
            assistant_blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            })
        if resp.text:
            assistant_blocks.insert(0, {"type": "text", "text": resp.text})

        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_result_blocks = []
        for tc in resp.tool_calls:
            try:
                result = await tools.execute_tool(
                    session, family_id=family_id, name=tc["name"], input=tc["input"]
                )
            except Exception as e:
                logger.exception("tool {} failed: {}", tc["name"], e)
                result = f"Ошибка при выполнении {tc['name']}: {e}"
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result,
            })
            # Persist intermediate tool call for audit
            await repositories.append_conversation(
                session,
                family_id=family_id,
                telegram_user_id=telegram_user_id,
                role=MessageRole.tool,
                content=f"[{tc['name']}({tc['input']})] -> {result}",
            )

        messages.append({"role": "user", "content": tool_result_blocks})
    else:
        # Loop exhausted
        final_text = "Не получилось разобраться за разумное число шагов. Попробуй переформулировать."

    # Persist assistant turn
    await repositories.append_conversation(
        session,
        family_id=family_id,
        telegram_user_id=telegram_user_id,
        role=MessageRole.assistant,
        content=final_text,
    )
    return final_text
```

- [ ] **Step 3: Run tests, verify they pass**

Run: `pytest tests/integration/test_conversation.py -v`
Expected: PASS (2/2)

- [ ] **Step 4: Commit**

```bash
git add core/services/conversation.py tests/integration/test_conversation.py
git commit -m "feat(conversation): add tool-use loop for free-text dialog"
```

---

### Task 3.5: Wire free-text handler in bot

**Files:**
- Create: `bot/handlers/freetext.py`
- Modify: `bot/main.py` — register LAST (so command handlers take precedence)

- [ ] **Step 1: Write `bot/handlers/freetext.py`**

```python
# bot/handlers/freetext.py
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import Family, FamilyMember
from core.services import conversation

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    # Don't run conversation agent if we're in the middle of an FSM dialog
    current = await state.get_state()
    if current is not None:
        return

    await message.chat.do("typing")
    try:
        reply = await conversation.handle_message(
            db_session,
            family_id=family.id,
            telegram_user_id=family_member.telegram_user_id,
            text=message.text,
        )
    except Exception as e:
        logger.exception("conversation failure: {}", e)
        await message.answer("Не получилось ответить. Попробуй ещё раз.")
        return
    await message.answer(reply)
```

- [ ] **Step 2: Register LAST in `bot/main.py`**

After all other routers:

```python
from bot.handlers import freetext as freetext_handler
dp.include_router(freetext_handler.router)
```

- [ ] **Step 3: Manual smoke test**

Run bot. Try:
- "что у нас в меню?" → bot replies with active menu (tool: get_active_menu)
- "что сегодня?" → today's meals (tool: get_meals_for_date)
- "поменяй четверг на что-то с рыбой" → menu updated (tool: replace_meal)
- "добавь молоко в список" → standalone shopping item appears in /list
- Make sure `/plan` wizard still works (FSM dialog takes precedence over free text)

- [ ] **Step 4: Commit**

```bash
git add bot/handlers/freetext.py bot/main.py
git commit -m "feat(bot): add free-text handler routing to conversation agent"
```

---

### Phase 3 — Verification

- [ ] All unit + integration tests pass: `pytest`
- [ ] Free text "что у нас в меню?" returns active menu
- [ ] Free text "поменяй четверг ужин на рыбу" actually updates the meal in DB
- [ ] Free text "добавь молоко в список" creates a `shopping_items` row visible in `/list`
- [ ] `/plan` wizard still works (free-text handler doesn't hijack FSM steps)
- [ ] `claude_conversations` table accumulates user/assistant/tool entries

---

# Final MVP Verification

After all phases:

- [ ] `pytest` — all green
- [ ] `ruff check .` — clean
- [ ] Docker image builds: `docker build -t chef-bot:mvp .`
- [ ] Deploy to chosen PaaS (Fly.io / Railway / Render) with `data/` volume + env vars
- [ ] End-to-end test as a real user from Telegram:
  1. `/start` — welcome
  2. `/plan` — generate 7-day menu, approve, get shopping list
  3. `/menu`, `/today` — see meals
  4. `/recipe` — get a recipe for current slot
  5. `/list` — tap items to mark bought
  6. Free text: "что в среду на ужин?", "замени пятницу ужин на креветки", "добавь сыр в список", "я купила молоко" — all should work
