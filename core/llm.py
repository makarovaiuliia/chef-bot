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


def build_system_blocks(task_prompt_name: str) -> list[dict]:
    """base_context (cached) + task-specific prompt (cached)."""
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
