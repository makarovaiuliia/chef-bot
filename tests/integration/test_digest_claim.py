"""Заявка на рассылку: at-most-once на семью в сутки против реальной БД."""
from datetime import date

from core.repositories import claim_digest_slot, release_digest_slot
from core.services.family_service import create_family

TODAY = date(2026, 7, 21)


async def _family(db_session, tg_id=111):
    family, _member = await create_family(
        db_session,
        telegram_user_id=tg_id,
        display_name="Юля",
        profile_md="# Профиль",
        timezone="Asia/Bangkok",
        plan_slots=["dinner"],
    )
    await db_session.commit()
    return family


async def test_first_claim_granted(db_session):
    family = await _family(db_session)
    assert await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)


async def test_second_claim_same_day_denied(db_session):
    family = await _family(db_session)
    assert await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)
    assert not await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)


async def test_next_day_claim_granted(db_session):
    family = await _family(db_session)
    await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)
    assert await claim_digest_slot(
        db_session, family_id=family.id, local_date=date(2026, 7, 22)
    )


async def test_stale_claim_does_not_block_today(db_session):
    """Заявка вчерашним числом не должна мешать сегодняшней рассылке."""
    family = await _family(db_session)
    await claim_digest_slot(db_session, family_id=family.id, local_date=date(2026, 7, 20))
    assert await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)


async def test_release_allows_retry(db_session):
    family = await _family(db_session)
    await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)
    await release_digest_slot(db_session, family_id=family.id, previous=None)
    assert await claim_digest_slot(db_session, family_id=family.id, local_date=TODAY)


async def test_two_separate_sessions_only_one_wins(tmp_path):
    """Сценарий двух реплик: разные соединения, право получает ровно одно.

    Файловая БД, а не :memory:, — иначе каждое соединение получило бы свою
    отдельную базу. Заявки идут последовательно: одна AsyncSession не
    предназначена для параллельного использования, а в проде каждая заявка
    берет сессию из своего процесса.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.db import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/claim.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async with sm() as setup:
        family = await _family(setup)
        family_id = family.id

    results = []
    for _ in range(3):
        async with sm() as session:  # каждая «реплика» со своим соединением
            results.append(
                await claim_digest_slot(
                    session, family_id=family_id, local_date=TODAY
                )
            )
    await engine.dispose()

    assert results == [True, False, False]


async def test_claim_is_per_family(db_session):
    first = await _family(db_session, tg_id=111)
    second = await _family(db_session, tg_id=222)

    assert await claim_digest_slot(db_session, family_id=first.id, local_date=TODAY)
    assert await claim_digest_slot(db_session, family_id=second.id, local_date=TODAY)
