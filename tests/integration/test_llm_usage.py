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
