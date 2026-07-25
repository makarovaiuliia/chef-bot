import json
from dataclasses import dataclass, field
from functools import lru_cache
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
        settings = get_settings()
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._model = settings.claude_model

    async def chat(
        self,
        *,
        system_blocks: list[dict],
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
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
                tool_calls.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            raw_message=resp,
        )


@lru_cache
def get_llm_client() -> LLMClient:
    """Единственный клиент на процесс.

    Раньше фабрика дублировалась в каждом сервисе, и каждая держала свой
    httpx-пул: до семи пулов на процесс вместо одного, без переиспользования
    соединений между операциями. Сервисы по-прежнему импортируют имя к себе в
    модуль, чтобы его можно было подменять в тестах.
    """
    return LLMClient()


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


def parse_json_response(text: str) -> dict:
    """Extract a JSON object from Claude's text response, stripping fences."""
    text = text.strip()
    if text.startswith("```"):
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
