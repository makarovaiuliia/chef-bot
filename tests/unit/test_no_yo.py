"""Гард: в текстах бота (bot/, core/) не используется буква «ё» — всегда «е»."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_yo_in_bot_and_core():
    offenders = []
    for base in ("bot", "core"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.suffix not in {".py", ".md"}:
                continue
            text = path.read_text(encoding="utf-8")
            if "ё" in text or "Ё" in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Замените ё → е в: {offenders}"
