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
