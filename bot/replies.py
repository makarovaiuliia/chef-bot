"""Отправка ответов, которые могут не влезть в лимит Telegram (4096 символов).

Переполнение реально в четырех местах: вывод рецепта (LLM отдает до 4096
токенов, это заметно больше 4096 символов русского текста), список покупок
текстом, длинное меню и список семей в /admin. Без разбиения Telegram
отвечает 400 и юзер не получает ничего.
"""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from loguru import logger

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


async def replace_placeholder(placeholder: Message, text: str, **kwargs) -> Message | None:
    """Заменить сообщение-ожидание результатом, удалив его и ответив заново.

    Плейсхолдер генерации несет постоянную reply-клавиатуру (kb_main), которую
    вытеснил ForceReply. Такое сообщение Telegram редактировать отказывается:
    editMessageText отдает 400 «message can't be edited». Ошибка попадала в
    benign-ветку глобального обработчика — ни юзеру, ни оператору, — и человек
    вечно смотрел на «Готовлю меню...», хотя меню было сгенерировано и оплачено.

    Удаление плейсхолдера не снимает reply-клавиатуру: она уровня чата, а не
    сообщения. Не удалилось (сообщение старше 48 часов) — не беда, результат
    все равно уходит новым сообщением: молчание здесь хуже лишней строки.
    """
    try:
        await placeholder.delete()
    except TelegramBadRequest as e:
        logger.info("replies: не удалось убрать плейсхолдер: {}", e)
    return await answer_long(placeholder, text, **kwargs)


async def edit_long(message: Message, text: str, **kwargs) -> None:
    """Заменить текст сообщения, дослав не влезший хвост отдельными ответами."""
    chunks = split_for_telegram(text)
    await message.edit_text(chunks[0], **(kwargs if len(chunks) == 1 else {}))
    for index, chunk in enumerate(chunks[1:], start=2):
        extra = kwargs if index == len(chunks) else {}
        await message.answer(chunk, **extra)
