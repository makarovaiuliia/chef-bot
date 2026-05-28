"""Wipe ALL rows from the configured DB. Schema stays intact.

Usage (inside the deployed container, or locally with DB_URL set):

    python scripts/wipe_db.py --yes

After running on a fresh DB, send /start in Telegram to recreate the family.
"""
import argparse
import asyncio

from sqlalchemy import delete

from core.db import (
    ClaudeConversation,
    Family,
    FamilyMember,
    Meal,
    Menu,
    Recipe,
    ShoppingItem,
    ShoppingList,
    get_engine,
    get_sessionmaker,
)

# Children before parents — works even without PRAGMA foreign_keys=ON.
_TABLES_IN_ORDER = [
    Recipe,
    Meal,
    ShoppingItem,
    ShoppingList,
    Menu,
    ClaudeConversation,
    FamilyMember,
    Family,
]


async def main(confirm: bool) -> None:
    if not confirm:
        print("This will DELETE ALL ROWS from every table.")
        print("Re-run with --yes to proceed.")
        return

    sm = get_sessionmaker()
    async with sm() as session:
        for table in _TABLES_IN_ORDER:
            result = await session.execute(delete(table))
            print(f"  {table.__tablename__}: deleted {result.rowcount} rows")
        await session.commit()

    await get_engine().dispose()
    print("Done.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--yes", action="store_true", help="skip confirmation")
    args = p.parse_args()
    asyncio.run(main(args.yes))
