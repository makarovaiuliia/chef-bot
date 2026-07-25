"""Отправка ответов, которые могут не влезть в лимит Telegram (4096 символов).

Переполнение реально в четырех местах: вывод рецепта (LLM отдает до 4096
токенов, это заметно больше 4096 символов русского текста), список покупок
текстом, длинное меню и список семей в /admin. Без разбиения Telegram
отвечает 400 и юзер не получает ничего.
"""
from aiogram.types import Message

from bot.formatting import split_for_telegram


async def answer_long(message: Message, text: str, **kwargs) -> Message | None:
    """Ответить, разбив текст на несколько сообщений при переполнении.

    reply_markup и прочие kwargs вешаются на последний кусок — там, где юзер
    закончит читать.
    """
    sent = None
    chunks = split_for_telegram(text)
    for index, chunk in enumerate(chunks, start=1):
        extra = kwargs if index == len(chunks) else {}
        sent = await message.answer(chunk, **extra)
    return sent


async def edit_long(message: Message, text: str, **kwargs) -> None:
    """Заменить текст сообщения, дослав не влезший хвост отдельными ответами."""
    chunks = split_for_telegram(text)
    await message.edit_text(chunks[0], **(kwargs if len(chunks) == 1 else {}))
    for index, chunk in enumerate(chunks[1:], start=2):
        extra = kwargs if index == len(chunks) else {}
        await message.answer(chunk, **extra)
