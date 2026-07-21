import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"

from core.db import Base  # noqa: E402


@pytest.fixture(scope="session")
def dispatcher():
    """Единый Dispatcher на весь прогон: aiogram-роутеры — модульные синглтоны,
    повторный create_dispatcher() падает (router already attached)."""
    from bot.main import create_dispatcher

    return create_dispatcher()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()
