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
    """Run tool-use loop. Persist user + assistant + tool turns. Return final reply."""
    await repositories.append_conversation(
        session,
        family_id=family_id,
        telegram_user_id=telegram_user_id,
        role=MessageRole.user,
        content=text,
    )

    history_rows = await repositories.recent_conversation(
        session, family_id=family_id, limit=20
    )
    prior_messages: list[dict] = []
    for row in history_rows[:-1]:
        if row.role == MessageRole.user:
            prior_messages.append({"role": "user", "content": row.content})
        elif row.role == MessageRole.assistant:
            prior_messages.append({"role": "assistant", "content": row.content})

    today_str = date.today().isoformat()
    user_msg_with_context = f"[Сегодняшняя дата: {today_str}]\n\n{text}"
    messages: list[dict] = [
        *prior_messages,
        {"role": "user", "content": user_msg_with_context},
    ]

    llm = get_llm_client()
    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
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

        assistant_blocks: list[dict] = []
        if resp.text:
            assistant_blocks.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                }
            )
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
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result,
                }
            )
            await repositories.append_conversation(
                session,
                family_id=family_id,
                telegram_user_id=telegram_user_id,
                role=MessageRole.tool,
                content=f"[{tc['name']}({tc['input']})] -> {result}",
            )

        messages.append({"role": "user", "content": tool_result_blocks})
    else:
        final_text = (
            "Не получилось разобраться за разумное число шагов. Попробуй переформулировать."
        )

    await repositories.append_conversation(
        session,
        family_id=family_id,
        telegram_user_id=telegram_user_id,
        role=MessageRole.assistant,
        content=final_text,
    )
    return final_text
