# Reply Keyboard + ё→е Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Постоянная reply-клавиатура с тремя кнопками (`➕ Добавить`, `🍳 Сегодня`, `👨‍👩‍👧 Семья`) + замена «ё» на «е» во всех текстах `bot/` и `core/`.

**Architecture:** Тексты кнопок — константы в `bot/keyboards.py`, клавиатура `kb_main()`. Хэндлеры кнопок — вторые декораторы `@router.message(F.text == BTN_*)` на существующих командных хэндлерах (логика не дублируется). Клавиатура прикрепляется к ответам `/start`, `/help` и к финальному сообщению онбординга.

**Tech Stack:** Python 3.12, aiogram 3, pytest (через `uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-07-20-reply-keyboard-design.md`

## Global Constraints

- Буква «ё»/«Ё» ЗАПРЕЩЕНА в любых строках в `bot/` и `core/` (включая новый код этого плана): всегда «е»/«Е».
- Тексты бота — на русском, в стиле существующих.
- Порядок регистрации роутеров в `bot/main.py` НЕ менять.
- Тесты запускать: `uv run pytest tests/unit -q` (из корня репозитория).
- Каталоги `docs/` и `tests/` заменой «ё» не трогать (в тестах «ё» встречается в их собственных фикстурах — это нормально).
- Коммиты после каждой задачи; сообщение заканчивается строкой `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Замена «ё» → «е» в bot/ и core/ + guard-тест

**Files:**
- Modify: все `*.py` в `bot/` и `core/`, все `*.md` в `core/prompts/` (где есть «ё»/«Ё»)
- Test: `tests/unit/test_no_yo.py` (создать)

**Interfaces:**
- Produces: инвариант «нет ё в bot/ и core/», охраняемый тестом `test_no_yo_in_bot_and_core`. Последующие задачи обязаны писать тексты без «ё».

- [ ] **Step 1: Написать падающий guard-тест**

Создать `tests/unit/test_no_yo.py`:

```python
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
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/unit/test_no_yo.py -v`
Expected: FAIL, в списке offenders ~19 файлов (bot/keyboards.py, bot/main.py, bot/handlers/*, core/db.py, core/tools.py, core/services/*, core/prompts/*.md).

- [ ] **Step 3: Выполнить замену**

Из корня репозитория:

```bash
python3 - <<'EOF'
from pathlib import Path

for base in ("bot", "core"):
    for p in sorted(Path(base).rglob("*")):
        if p.suffix not in {".py", ".md"}:
            continue
        text = p.read_text(encoding="utf-8")
        new = text.replace("ё", "е").replace("Ё", "Е")
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(p)
EOF
```

- [ ] **Step 4: Прогнать guard-тест и весь юнит-набор**

Run: `uv run pytest tests/unit -q`
Expected: все PASS (тесты сравнивают ё-строки только со своими фикстурами, не с текстами бота). Если какой-то тест сравнивает строку из `bot/`/`core/` с «ё»-эталоном — поправить эталон теста на «е»-версию.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(copy): replace ё with е in all bot and core texts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Константы кнопок и kb_main() в keyboards.py

**Files:**
- Modify: `core/emoji.py`, `bot/keyboards.py`
- Test: `tests/unit/test_main_keyboard.py` (создать)

Конвенция кодовой базы: эмодзи-литералы живут ТОЛЬКО в `core/emoji.py` (single source of truth, это требование прошлого ревью). Поэтому глифы кнопок — через константы emoji.

**Interfaces:**
- Produces: `BTN_ADD = "➕ Добавить"`, `BTN_TODAY = "🍳 Сегодня"`, `BTN_FAMILY = "👨‍👩‍👧 Семья"` (str-константы) и `kb_main() -> ReplyKeyboardMarkup` в `bot/keyboards.py`. Задачи 3 и 4 импортируют их оттуда.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/unit/test_main_keyboard.py`:

```python
from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY, kb_main


def test_kb_main_is_persistent_single_row():
    kb = kb_main()
    assert kb.resize_keyboard is True
    assert kb.is_persistent is True
    assert len(kb.keyboard) == 1  # один ряд
    texts = [b.text for b in kb.keyboard[0]]
    assert texts == [BTN_ADD, BTN_TODAY, BTN_FAMILY]


def test_button_texts_are_not_commands():
    for text in (BTN_ADD, BTN_TODAY, BTN_FAMILY):
        assert not text.startswith("/")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/unit/test_main_keyboard.py -v`
Expected: FAIL с `ImportError: cannot import name 'BTN_ADD'`.

- [ ] **Step 3: Реализовать**

В `core/emoji.py`:

- добавить после `TOMORROW`:

```python
COOK = "🍳"  # кнопка «Сегодня» главной клавиатуры
```

- заменить значение `FAMILY = "👪"` на:

```python
FAMILY = "👨‍👩‍👧"
```

(глиф семьи унифицируется с кнопкой главной клавиатуры; используется также в /help и /start)

В `bot/keyboards.py` заменить первую строку импорта

```python
from aiogram.types import InlineKeyboardMarkup
```

на

```python
from aiogram.types import (
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
```

и добавить после импортов (перед `kb_confirm_overwrite`):

```python
# Постоянная reply-клавиатура с основными действиями.
# Тексты — контракт: на них матчатся message-хэндлеры (menu, shopping, family).
BTN_ADD = f"{emoji.ADD} Добавить"
BTN_TODAY = f"{emoji.COOK} Сегодня"
BTN_FAMILY = f"{emoji.FAMILY} Семья"


def kb_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BTN_ADD),
                KeyboardButton(text=BTN_TODAY),
                KeyboardButton(text=BTN_FAMILY),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
```

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/unit/test_main_keyboard.py tests/unit/test_no_yo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/emoji.py bot/keyboards.py tests/unit/test_main_keyboard.py
git commit -m "feat(bot): main reply keyboard constants and kb_main()

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Хэндлеры на тексты кнопок (today, add, family)

**Files:**
- Modify: `bot/handlers/menu.py` (хэндлер `cmd_today`, ~строка 49)
- Modify: `bot/handlers/shopping.py` (общий промпт + новый хэндлер)
- Modify: `bot/handlers/family.py` (хэндлеры `cmd_family` ~112 и `cmd_family_member_view` ~128)
- Test: `tests/unit/test_button_handlers.py` (создать)

**Interfaces:**
- Consumes: `BTN_ADD`, `BTN_TODAY`, `BTN_FAMILY` из `bot.keyboards` (Task 2).
- Produces: нажатия кнопок обрабатываются теми же функциями, что команды `/today`, `/family` и inline-кнопка `shop:add`. Новая функция `bot/handlers/shopping.py::btn_add(message: Message) -> None` и хелпер `_ask_what_to_add(message: Message) -> None`.

Механика: на существующий хэндлер навешивается второй декоратор — aiogram регистрирует функцию дважды с разными фильтрами. Роутеры menu/shopping/family подключены раньше freetext-роутера (`bot/main.py:49-56`), поэтому тексты кнопок не попадут в ИИ-чат. Порядок роутеров не менять.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/unit/test_button_handlers.py`:

```python
"""Кнопки reply-клавиатуры маппятся на те же хэндлеры, что и команды."""
from unittest.mock import AsyncMock

from aiogram import F
from aiogram.filters import Command

from bot.handlers import family, menu, shopping
from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY


def _registered_filters(router):
    """[(callback_name, [filter_reprs])] для всех message-хэндлеров роутера."""
    return [
        (h.callback.__name__, [repr(f.callback) for f in h.filters])
        for h in router.message.handlers
    ]


def _has_text_binding(router, func_name: str, btn_text: str) -> bool:
    magic = repr(F.text == btn_text)
    return any(
        name == func_name and any(magic in f for f in filters)
        for name, filters in _registered_filters(router)
    )


def test_btn_today_bound_to_cmd_today():
    assert _has_text_binding(menu.router, "cmd_today", BTN_TODAY)


def test_btn_family_bound_to_both_family_views():
    assert _has_text_binding(family.router, "cmd_family", BTN_FAMILY)
    assert _has_text_binding(family.router, "cmd_family_member_view", BTN_FAMILY)


def test_btn_add_bound():
    assert _has_text_binding(shopping.router, "btn_add", BTN_ADD)


async def test_btn_add_asks_what_to_add():
    message = AsyncMock()
    await shopping.btn_add(message)
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == shopping._ADD_PROMPT
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/unit/test_button_handlers.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'btn_add'` и assert False в тестах биндингов).

Примечание: если `_registered_filters` не находит фильтры из-за внутренностей aiogram (поле называется иначе), поправить хелпер под фактическую структуру `router.message.handlers` — но НЕ ослаблять сами проверки.

- [ ] **Step 3: Реализовать — menu.py**

В `bot/handlers/menu.py`:

Заменить

```python
from aiogram import Router
```

на

```python
from aiogram import F, Router
```

Добавить импорт после `from bot.filters import HasFamily`:

```python
from bot.keyboards import BTN_TODAY
```

Заменить

```python
@router.message(Command("today"))
async def cmd_today(
```

на

```python
@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(
```

- [ ] **Step 4: Реализовать — shopping.py**

В `bot/handlers/shopping.py`:

Заменить

```python
from bot.keyboards import kb_shopping_list
```

на

```python
from bot.keyboards import BTN_ADD, kb_shopping_list
```

Добавить после `_split_names` общий хелпер (промпт «что добавить?» используется в трех местах):

```python
async def _ask_what_to_add(message: Message) -> None:
    await message.answer(
        _ADD_PROMPT,
        reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
    )
```

В `cmd_add` заменить

```python
    if not text:
        await message.answer(
            _ADD_PROMPT,
            reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
        )
        return
```

на

```python
    if not text:
        await _ask_what_to_add(message)
        return
```

В `cb_add` заменить

```python
    await cb.message.answer(
        _ADD_PROMPT,
        reply_markup=ForceReply(input_field_placeholder="например, молоко 1 л"),
    )
    await cb.answer()
```

на

```python
    await _ask_what_to_add(cb.message)
    await cb.answer()
```

Добавить новый хэндлер сразу после `cb_add`:

```python
@router.message(F.text == BTN_ADD)
async def btn_add(message: Message) -> None:
    await _ask_what_to_add(message)
```

- [ ] **Step 5: Реализовать — family.py**

В `bot/handlers/family.py`:

Добавить импорт после `from bot.filters import HasFamily, IsAdmin`:

```python
from bot.keyboards import BTN_FAMILY
```

Заменить

```python
@router.message(Command("family"), HasFamily(), IsAdmin())
async def cmd_family(message: Message, db_session, family, family_member) -> None:
```

на

```python
@router.message(Command("family"), HasFamily(), IsAdmin())
@router.message(F.text == BTN_FAMILY, HasFamily(), IsAdmin())
async def cmd_family(message: Message, db_session, family, family_member) -> None:
```

Заменить

```python
@router.message(Command("family"), HasFamily())
async def cmd_family_member_view(message: Message, db_session, family) -> None:
```

на

```python
@router.message(Command("family"), HasFamily())
@router.message(F.text == BTN_FAMILY, HasFamily())
async def cmd_family_member_view(message: Message, db_session, family) -> None:
```

Важно: у family-роутера нет роутер-левел фильтра `HasFamily()` — фильтры указываются в каждом декораторе, как в существующем коде. Порядок пар декораторов сохранить как выше: админский вариант регистрируется раньше обычного.

- [ ] **Step 6: Прогнать тесты**

Run: `uv run pytest tests/unit -q`
Expected: все PASS.

- [ ] **Step 7: Commit**

```bash
git add bot/handlers/menu.py bot/handlers/shopping.py bot/handlers/family.py tests/unit/test_button_handlers.py
git commit -m "feat(bot): handle main keyboard button presses

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Выдача клавиатуры в /start, /help и в финале онбординга

**Files:**
- Modify: `bot/handlers/start.py`
- Modify: `bot/handlers/onboarding.py` (хэндлер `on_profile_ok`, ~строка 229)
- Test: `tests/unit/test_button_handlers.py` (дополнить), `tests/unit/test_onboarding_handlers.py` (дополнить)

**Interfaces:**
- Consumes: `kb_main()` из `bot.keyboards` (Task 2).
- Produces: пользователь с семьей получает reply-клавиатуру после `/start`, `/help` и после создания семьи в онбординге.

Нюанс: `ReplyKeyboardMarkup` нельзя прикрепить через `edit_text` (Telegram принимает там только inline-клавиатуры). Поэтому в `on_profile_ok` финальный текст отправляется новым сообщением с клавиатурой, а у сообщения с профилем убираются inline-кнопки через `edit_reply_markup(reply_markup=None)` — текст профиля остается в чате.

- [ ] **Step 1: Написать падающие тесты**

В `tests/unit/test_button_handlers.py` добавить в конец:

```python
async def test_cmd_help_attaches_main_keyboard():
    from bot.handlers import start
    from bot.keyboards import kb_main

    message = AsyncMock()
    await start.cmd_help(message)
    assert message.answer.await_args.kwargs["reply_markup"] == kb_main()


async def test_cmd_start_with_family_attaches_main_keyboard():
    from bot.handlers import start
    from bot.keyboards import kb_main

    message = AsyncMock()
    state = AsyncMock()
    await start.cmd_start(message, state, family=object())
    assert message.answer.await_args.kwargs["reply_markup"] == kb_main()
```

В `tests/unit/test_onboarding_handlers.py` добавить в конец:

```python
async def test_on_profile_ok_creates_family_and_attaches_keyboard(monkeypatch):
    """После создания семьи финальное сообщение идет новым message
    с постоянной reply-клавиатурой (edit_text не умеет reply-клавиатуры)."""
    from types import SimpleNamespace

    from bot.keyboards import kb_main

    async def fake_create_family(db, **kwargs):
        return SimpleNamespace(id=1), None

    async def fake_log_llm_usage(db, **kwargs):
        return None

    monkeypatch.setattr(onb, "create_family", fake_create_family)
    monkeypatch.setattr(onb, "log_llm_usage", fake_log_llm_usage)

    cb = AsyncMock()
    state = AsyncMock()
    state.get_data.return_value = {
        "profile_md": "профиль",
        "timezone": "Europe/Moscow",
        "slots": ["dinner"],
    }

    await onb.on_profile_ok(cb, state, db_session=None, family=None)

    state.clear.assert_awaited_once()
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    assert "Семья создана" in cb.message.answer.await_args.args[0]
    assert cb.message.answer.await_args.kwargs["reply_markup"] == kb_main()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `uv run pytest tests/unit/test_button_handlers.py tests/unit/test_onboarding_handlers.py -v`
Expected: три новых теста FAIL (нет `reply_markup` / нет `edit_reply_markup`), старые PASS.

- [ ] **Step 3: Реализовать — start.py**

В `bot/handlers/start.py`:

Добавить импорт после `from bot.handlers.onboarding import start_onboarding`:

```python
from bot.keyboards import kb_main
```

Заменить

```python
    if family is not None:
        await message.answer(_HELP_TEXT)
        return
```

на

```python
    if family is not None:
        await message.answer(_HELP_TEXT, reply_markup=kb_main())
        return
```

Заменить

```python
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)
```

на

```python
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT, reply_markup=kb_main())
```

- [ ] **Step 4: Реализовать — onboarding.py**

В `bot/handlers/onboarding.py`:

В импорте из `bot.keyboards` добавить `kb_main`:

```python
from bot.keyboards import (
    kb_cook_minutes,
    kb_household,
    kb_main,
    kb_multiselect,
    kb_profile_confirm,
    kb_skip,
)
```

В `on_profile_ok` заменить

```python
    await state.clear()
    await cb.message.edit_text(
        f"{emoji.DONE} Готово! Семья создана.\n\n"
        "Пригласить близких: /invite\n"
        "Профиль семьи: /profile\n"
        "Справка: /help"
    )
    await cb.answer()
```

на

```python
    await state.clear()
    # Reply-клавиатуру нельзя прикрепить к edit_text — отправляем новым сообщением,
    # а у сообщения с профилем убираем inline-кнопки (текст профиля остается в чате).
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        f"{emoji.DONE} Готово! Семья создана.\n\n"
        "Пригласить близких: /invite\n"
        "Профиль семьи: /profile\n"
        "Справка: /help",
        reply_markup=kb_main(),
    )
    await cb.answer()
```

Ветку `if family is not None:` в начале `on_profile_ok` не трогать.

- [ ] **Step 5: Прогнать весь набор**

Run: `uv run pytest tests/unit -q`
Expected: все PASS.

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/start.py bot/handlers/onboarding.py tests/unit/test_button_handlers.py tests/unit/test_onboarding_handlers.py
git commit -m "feat(bot): attach main reply keyboard on /start, /help and onboarding finish

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
