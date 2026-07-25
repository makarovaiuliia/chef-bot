"""Суперадмин /admin: сводка и семьи. Отдельный слой доверия (config.superadmin_ids).

/grant и /revoke — скрытые команды ручной активации подписки после оплаты вне
бота; не добавляются в bot_commands/help (спека беты §5)."""
import html
from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import IsSuperadmin
from bot.replies import answer_long
from core import repositories
from core.constants import PRICE_USD_PER_MTOK_IN, PRICE_USD_PER_MTOK_OUT
from core.services.family_service import get_admins

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
    onboarding_today = await repositories.count_onboarding_attempts_today_all(
        db_session, now=now
    )

    ops_lines = [f"  {op}: {cnt}" for op, cnt in sorted(summary["ops"].items())]
    usd = _usd(summary["tokens_in"], summary["tokens_out"])
    lines = [
        f"<b>Сводка за месяц ({now.strftime('%m.%Y')})</b>",
        f"Семей: {summary['families']}",
        f"Заявок на подписку: {requests}",
        f"Онбординг сегодня: {onboarding_today} попыток",
        "Операции:",
        *(ops_lines or ["  нет"]),
        f"Токены: {summary['tokens_in']:,} in / {summary['tokens_out']:,} out",
        f"Оценка стоимости: ${usd:.2f} (ориентир Sonnet)",
        "",
        "<b>Семьи</b> (id · имя · участников · tz · токены/мес):",
    ]
    for f in overview:
        name = html.escape(f["name"]) if f["name"] else "—"
        line = (
            f"{f['id']} · {name} · {f['members']} · {f['timezone']} · "
            f"{f['tokens_month']:,}"
        )
        if f["sub_until"]:
            line += f" · подписка до {f['sub_until']:%d.%m.%Y}"
        lines.append(line)
    await answer_long(message, "\n".join(lines))


def _parse_grant_args(message: Message) -> tuple[int, int] | None:
    """(family_id, days) из «/grant <family_id> [дней]»; None — кривые аргументы."""
    parts = (message.text or "").split()
    if len(parts) not in (2, 3) or not parts[1].isdigit():
        return None
    if len(parts) == 3 and not parts[2].isdigit():
        return None
    return int(parts[1]), (int(parts[2]) if len(parts) == 3 else 30)


@router.message(Command("grant"))
async def cmd_grant(message: Message, db_session: AsyncSession) -> None:
    args = _parse_grant_args(message)
    if args is None:
        await message.answer("Использование: /grant <family_id> [дней=30]")
        return
    family_id, days = args
    sub_until = await repositories.extend_family_subscription(
        db_session, family_id=family_id, days=days, today=datetime.now(UTC).date()
    )
    if sub_until is None:
        await message.answer(f"Семья {family_id} не найдена")
        return
    until = sub_until.strftime("%d.%m.%Y")
    for admin in await get_admins(db_session, family_id=family_id):
        try:
            await message.bot.send_message(
                admin.telegram_user_id,
                f"Подписка активна до {until} — лимиты триала сняты. Спасибо!",
            )
        except Exception:
            logger.warning("admin: grant notify failed id={}", admin.telegram_user_id)
    await message.answer(f"Семья {family_id}: подписка до {until}")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, db_session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /revoke <family_id>")
        return
    family_id = int(parts[1])
    ok = await repositories.revoke_family_subscription(db_session, family_id=family_id)
    await message.answer(
        f"Семья {family_id}: подписка отключена" if ok
        else f"Семья {family_id} не найдена"
    )
