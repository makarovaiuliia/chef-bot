"""split_for_telegram и wait_text: лимит сообщения и оценки времени ожидания."""
import pytest

from bot.formatting import split_for_telegram, wait_text
from core.constants import LLM_WAIT_HINTS, TELEGRAM_MESSAGE_LIMIT


def test_short_text_stays_one_chunk():
    assert split_for_telegram("привет") == ["привет"]


def test_empty_text_gives_single_empty_chunk():
    # Вызывающий код всегда получает хотя бы один элемент, чтобы не проверять len.
    assert split_for_telegram("") == [""]


def test_long_text_split_respects_limit():
    text = "\n".join(f"строка номер {i}" for i in range(2000))
    chunks = split_for_telegram(text)
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_MESSAGE_LIMIT for c in chunks)


def test_split_preserves_content_and_line_boundaries():
    lines = [f"пункт {i}" for i in range(1000)]
    chunks = split_for_telegram("\n".join(lines))
    # Ни одна строка не разорвана: склейка кусков дает исходный набор строк.
    rejoined = "\n".join(chunks).split("\n")
    assert rejoined == lines


def test_prefers_blank_line_boundary():
    block = "x" * 2000
    chunks = split_for_telegram(f"{block}\n\n{block}\n\n{block}")
    assert len(chunks) == 2
    # Первый кусок закончился на границе абзаца, а не посреди блока.
    assert chunks[0] == f"{block}\n\n{block}"


def test_single_line_longer_than_limit_is_hard_split():
    text = "я" * (TELEGRAM_MESSAGE_LIMIT * 2 + 17)
    chunks = split_for_telegram(text)
    assert all(len(c) <= TELEGRAM_MESSAGE_LIMIT for c in chunks)
    assert "".join(chunks) == text  # ничего не потеряли и не зациклились


def test_custom_limit():
    chunks = split_for_telegram("аб\nвг\nде", limit=5)
    assert all(len(c) <= 5 for c in chunks)
    assert "\n".join(chunks).split("\n") == ["аб", "вг", "де"]


def test_wait_text_includes_hint():
    assert wait_text("X", "Готовлю меню", "menu_gen") == "X Готовлю меню... (до минуты)"


def test_wait_text_unknown_operation_omits_hint():
    # Неизвестная операция не должна ломать ответ юзеру — просто без оценки.
    assert wait_text("X", "Работаю", "нет_такой") == "X Работаю..."


@pytest.mark.parametrize("operation", sorted(LLM_WAIT_HINTS))
def test_every_hint_is_usable(operation):
    text = wait_text("X", "Проверка", operation)
    assert text.endswith(f"({LLM_WAIT_HINTS[operation]})")
