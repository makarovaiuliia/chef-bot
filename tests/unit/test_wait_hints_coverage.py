"""Гард: каждый плейсхолдер ожидания LLM имеет оценку времени в LLM_WAIT_HINTS.

Ловит две ошибки: новый вызов wait_text с операцией, которой нет в словаре
(юзер увидит плейсхолдер без обещания), и LLM-вызов, к которому вообще забыли
приделать плейсхолдер (юзер сидит перед пустотой — так было со сменой таймзоны).
"""
import re
from pathlib import Path

from core.constants import LLM_WAIT_HINTS

HANDLERS_DIR = Path(__file__).resolve().parents[2] / "bot" / "handlers"

_WAIT_TEXT_CALL = re.compile(r'wait_text\(\s*[^,]+,\s*"[^"]+",\s*"([^"]+)"\s*\)')

# Операции, у которых есть LLM-вызов и обязан быть плейсхолдер с оценкой.
# tz_detect попал сюда после того, как обнаружилось, что смена таймзоны уходила
# в LLM вообще без плейсхолдера.
OPERATIONS_NEEDING_PLACEHOLDER = {
    "menu_gen",
    "replace",
    "recipe",
    "shopping",
    "profile",
    "tz_detect",
}


def _used_operations() -> set[str]:
    found: set[str] = set()
    for path in sorted(HANDLERS_DIR.glob("*.py")):
        found.update(_WAIT_TEXT_CALL.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_used_operation_has_a_hint():
    unknown = sorted(_used_operations() - set(LLM_WAIT_HINTS))
    assert unknown == [], (
        f"wait_text вызван с операцией без оценки в LLM_WAIT_HINTS: {unknown}"
    )


def test_every_llm_operation_has_a_placeholder():
    missing = sorted(OPERATIONS_NEEDING_PLACEHOLDER - _used_operations())
    assert missing == [], (
        f"LLM-вызов без плейсхолдера ожидания — юзер не поймет, что бот работает: {missing}"
    )


def test_hints_are_non_empty_strings():
    for operation, hint in LLM_WAIT_HINTS.items():
        assert isinstance(hint, str) and hint.strip(), operation


def test_no_stale_hints():
    """Словарь не должен обрастать операциями, которые нигде не используются."""
    used = _used_operations()
    # conversation живет за фича-флагом, но плейсхолдер у него есть.
    unused = sorted(set(LLM_WAIT_HINTS) - used)
    assert unused == [], f"оценки для неиспользуемых операций: {unused}"
