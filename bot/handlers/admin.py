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
