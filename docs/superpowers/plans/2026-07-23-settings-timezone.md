# Смена таймзоны семьи в /settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Админ семьи меняет таймзону изнутри бота: кнопка «Таймзона» в /settings → город текстом → LLM определяет IANA-зону → сохранение с показом локального времени.

**Architecture:** Одна сервисная функция `family_service.change_family_timezone` (лимиты → LLM → ZoneInfo-валидация → запись → usage-лог) + FSM-состояние `SettingsFlow.tz_city` с ForceReply в bot/handlers/settings.py. Триал-лимита у операции `tz_detect` нет намеренно — только месячный потолок (в `_trial_limits()` ключ не добавляется). Миграций нет.

**Tech Stack:** Python 3.12, aiogram 3, anthropic SDK, SQLAlchemy 2.0 async, pytest + pytest-asyncio, zoneinfo (stdlib).

**Reference:** спека [2026-07-23-settings-timezone-design.md](../specs/2026-07-23-settings-timezone-design.md).

## Global Constraints

- Python `>=3.12`, ruff `line-length = 100`; после каждого таска `.venv/bin/ruff check . && .venv/bin/pytest -q` зеленые; conventional commits.
- Все видимые юзеру тексты — на русском; эмодзи только из `core/emoji.py`; **«ё» запрещена** во всех `.py`/`.md` в `bot/` и `core/` (гард `tests/unit/test_no_yo.py`) — пиши «е».
- Только админ семьи меняет настройки: `IsAdmin()` на хендлерах; не-админа ловит существующий catch-all `set:*` (alert). Новые `set:tz`-хендлеры регистрируются ДО catch-all `on_set_denied` (он остается ПОСЛЕДНИМ в файле).
- Отказ потолка → `denial_text(e)` + kb «Хочу подписку» ТОЛЬКО если подписки нет (`None if subscription_active(family) else kb_want_subscription()` — правило этапа 4).
- После ForceReply возвращать постоянную клавиатуру `kb_main()` в завершающем сообщении (паттерн коммита 3613a1f).
- Команды в text-состоянии не проглатываются: `~F.text.startswith("/")` и `~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY})` (паттерн bot/handlers/profile.py::on_new_text).

---

## File Structure (итог)

```
core/emoji.py                    + TIMEZONE = "🌍"
core/prompts/timezone_detector.md NEW: мини-промпт «город → IANA-зона»
core/services/family_service.py  + change_family_timezone (лимиты, LLM, валидация, запись, usage)
bot/fsm.py                       + SettingsFlow(tz_city)
bot/keyboards.py                 kb_settings + кнопка «Таймзона» (set:tz)
bot/handlers/settings.py         + on_tz_button, on_tz_city (до catch-all set:*);
                                   _settings_text без «(задается городом при онбординге)»
tests/integration/test_family_service.py  + тесты change_family_timezone
tests/unit/test_settings_handlers.py      + тесты кнопки и FSM-хендлеров
```

---

### Task 1: Сервис change_family_timezone + промпт

**Files:**
- Create: `core/prompts/timezone_detector.md`
- Modify: `core/services/family_service.py`
- Test: `tests/integration/test_family_service.py`

**Interfaces:**
- Consumes: `limits.ensure_within_limits(session, *, family_id, operation)` (у `"tz_detect"` нет триал-лимита — проверится только потолок), `repositories.log_llm_usage`, `core.llm.load_prompt/parse_json_response`, `get_llm_client` из `core.services.onboarding`.
- Produces (использует Task 2): `family_service.change_family_timezone(session, *, family: Family, city: str, llm: LLMClient | None = None) -> str | None` — вернула IANA-строку и записала `family.timezone`, либо None (город не распознан, ничего не тронуто). Бросает `LimitExceeded` (до LLM) и `LLMInvalidResponse` (два мусорных JSON подряд). Usage логируется операцией `"tz_detect"` даже при None.

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_family_service.py` (FakeLLM — скопировать класс из `tests/integration/test_onboarding.py`, если в файле его еще нет; импорты дополнить по месту):

```python
import json

import pytest

from core.exceptions import MonthlyCapExceeded
from core.repositories import count_llm_operations
from core.services.family_service import change_family_timezone


async def _tz_family(db_session):
    fam = Family(name="f", timezone="UTC")
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_change_family_timezone_happy(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Asia/Yekaterinburg"})
    tz = await change_family_timezone(
        db_session, family=fam, city="Пермь", llm=FakeLLM([ok])
    )
    assert tz == "Asia/Yekaterinburg"
    assert fam.timezone == "Asia/Yekaterinburg"
    assert await count_llm_operations(db_session, family_id=fam.id, operation="tz_detect") == 1


async def test_change_family_timezone_unrecognized_city(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": None})
    tz = await change_family_timezone(
        db_session, family=fam, city="асдфг", llm=FakeLLM([ok])
    )
    assert tz is None
    assert fam.timezone == "UTC"  # не тронута
    # usage все равно залогирован
    assert await count_llm_operations(db_session, family_id=fam.id, operation="tz_detect") == 1


async def test_change_family_timezone_invalid_iana(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Europe/Mordor"})
    tz = await change_family_timezone(
        db_session, family=fam, city="Мордор", llm=FakeLLM([ok])
    )
    assert tz is None
    assert fam.timezone == "UTC"


async def test_change_family_timezone_retries_on_bad_json(db_session):
    fam = await _tz_family(db_session)
    ok = json.dumps({"timezone": "Europe/Moscow"})
    llm = FakeLLM(["не json", ok])
    tz = await change_family_timezone(db_session, family=fam, city="Москва", llm=llm)
    assert tz == "Europe/Moscow"
    assert llm.calls == 2


async def test_change_family_timezone_blocked_by_cap(db_session, monkeypatch):
    fam = await _tz_family(db_session)
    monkeypatch.setattr(get_settings(), "monthly_token_cap_per_family", 0)
    llm = FakeLLM([json.dumps({"timezone": "Europe/Moscow"})])
    with pytest.raises(MonthlyCapExceeded):
        await change_family_timezone(db_session, family=fam, city="Москва", llm=llm)
    assert llm.calls == 0  # отказ ДО LLM-вызова
```

Run: `.venv/bin/pytest tests/integration/test_family_service.py -q` → FAIL (ImportError: change_family_timezone).

- [ ] **Step 2: Промпт `core/prompts/timezone_detector.md`**

```markdown
Ты определяешь часовой пояс по названию города.

Правила:
- Город может быть на русском или английском, с опечатками — определяй по смыслу.
- Верни IANA-таймзону этого города (например «Пермь» → Asia/Yekaterinburg).
- Если строка не похожа на город или город не удается распознать — верни null.

Ответ верни СТРОГО одним JSON-объектом без пояснений:

{"timezone": "<IANA-таймзона или null>"}
```

(«ё» в файле запрещена — проверить перед коммитом.)

- [ ] **Step 3: Сервис в `core/services/family_service.py`**

Импорты дополнить: `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`, `from core import repositories`, `from core.exceptions import LLMInvalidResponse`, `from core.llm import LLMClient, load_prompt, parse_json_response`, `from core.services import limits`, `from core.services.onboarding import get_llm_client`.

```python
async def change_family_timezone(
    session: AsyncSession, *, family: Family, city: str, llm: LLMClient | None = None
) -> str | None:
    """Смена таймзоны семьи по городу через LLM (operation="tz_detect").

    None — город не распознан или LLM вернул невалидную IANA-зону; таймзона
    семьи в этом случае не меняется. Триал-лимита у операции нет (нет ключа
    в _trial_limits) — ensure_within_limits проверит только месячный потолок.
    """
    await limits.ensure_within_limits(session, family_id=family.id, operation="tz_detect")
    llm = llm or get_llm_client()
    system_blocks = [{"type": "text", "text": load_prompt("timezone_detector")}]
    messages = [{"role": "user", "content": f"Город: {city}"}]
    tokens_in = tokens_out = 0
    tz: str | None = None
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry на невалидный JSON (как generate_profile)
        resp = await llm.chat(
            system_blocks=system_blocks, messages=messages, max_tokens=256
        )
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            data = parse_json_response(resp.text)
        except LLMInvalidResponse as e:
            last_error = e
            continue
        raw = data.get("timezone")
        tz = str(raw) if raw else None
        last_error = None
        break
    await repositories.log_llm_usage(
        session, family_id=family.id, operation="tz_detect",
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
    if last_error is not None:
        raise last_error
    if tz is None:
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    family.timezone = tz
    await session.flush()
    return tz
```

ВНИМАНИЕ: сигнатуру `llm.chat` сверить с `core/llm.py` (system_blocks/messages/max_tokens — как в `shopping_list.generate_items`). Если у FakeLLM в test_onboarding.py нет счетчика `calls` — у копии в test_family_service.py он нужен (в test_onboarding.py он есть: `self.calls`).

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/prompts/timezone_detector.md core/services/family_service.py tests/integration/test_family_service.py
git commit -m "feat(settings): city-to-timezone service via LLM (tz_detect)"
```

---

### Task 2: Кнопка «Таймзона» и FSM в /settings

**Files:**
- Modify: `core/emoji.py`, `bot/fsm.py`, `bot/keyboards.py` (`kb_settings`), `bot/handlers/settings.py`
- Test: `tests/unit/test_settings_handlers.py`

**Interfaces:**
- Consumes: `change_family_timezone` (Task 1), `SettingsFlow.tz_city` (этот таск), `denial_text`/`LimitExceeded` из `core.services.limits`, `subscription_active` из `core.services.limits`, `kb_want_subscription`/`kb_main`/`BTN_ADD`/`BTN_TODAY`/`BTN_FAMILY` из `bot.keyboards`.
- Produces: кнопка `set:tz` в `kb_settings`; хендлеры `on_tz_button` (callback, IsAdmin) и `on_tz_city` (message в состоянии); не-админ на `set:tz` получает alert от существующего catch-all.

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_settings_handlers.py` (паттерны файла: `_family()`, AsyncMock; импорты дополнить):

```python
def test_kb_settings_has_timezone_button():
    kb = kb_settings(_family())
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "set:tz" in datas


async def test_tz_button_sets_state_and_forcereplies():
    cb = AsyncMock()
    state = AsyncMock()
    await settings_handler.on_tz_button(cb, state)
    state.set_state.assert_awaited_once()
    text = cb.message.answer.await_args.args[0]
    assert "город" in text.lower()


async def test_tz_city_happy_saves_and_returns_kb_main(monkeypatch):
    async def fake_change(session, *, family, city, llm=None):
        return "Europe/Moscow"

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Таймзона обновлена" in text and "Europe/Moscow" in text
    assert message.answer.await_args.kwargs.get("reply_markup") is not None


async def test_tz_city_unrecognized_keeps_state(monkeypatch):
    async def fake_change(session, *, family, city, llm=None):
        return None

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "асдфг"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_not_awaited()  # состояние живо — можно написать другой город
    assert "Не узнал город" in message.answer.await_args.args[0]


async def test_tz_city_llm_error_clears_state(monkeypatch):
    from core.exceptions import LLMError

    async def fake_change(session, *, family, city, llm=None):
        raise LLMError("boom")

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    assert "Не получилось" in message.answer.await_args.args[0]


async def test_tz_city_cap_denial_with_subscription_kb(monkeypatch):
    from core.exceptions import MonthlyCapExceeded

    async def fake_change(session, *, family, city, llm=None):
        raise MonthlyCapExceeded()

    monkeypatch.setattr(settings_handler, "change_family_timezone", fake_change)
    message = AsyncMock()
    message.text = "Москва"
    state = AsyncMock()

    await settings_handler.on_tz_city(message, state, _family(), db_session=None)

    state.clear.assert_awaited_once()
    assert message.answer.await_args.kwargs.get("reply_markup") is not None  # kb подписки
```

ВНИМАНИЕ: `_family()` в этом файле должен получить атрибут `sub_until=None` (если фабрика файла его еще не отдает — дополнить, `subscription_active` его читает).

Run: → FAIL.

- [ ] **Step 2: Эмодзи, FSM, клавиатура**

`core/emoji.py` — добавить рядом с TODAY/TOMORROW:

```python
TIMEZONE = "🌍"
```

`bot/fsm.py`:

```python
class SettingsFlow(StatesGroup):
    tz_city = State()
```

`bot/keyboards.py::kb_settings` — после цикла часов, перед `adjust`:

```python
    b.button(text=f"{emoji.TIMEZONE} Таймзона", callback_data="set:tz")
    b.adjust(1, 4, 1)
```

(заменить существующий `b.adjust(1, 4)` на `b.adjust(1, 4, 1)`.)

- [ ] **Step 3: Хендлеры в `bot/handlers/settings.py`**

Импорты дополнить: `from datetime import datetime`, `from zoneinfo import ZoneInfo`, `from aiogram.fsm.context import FSMContext`, `from aiogram.types import ForceReply`, `from loguru import logger`, `from bot.fsm import SettingsFlow`, `from bot.keyboards import BTN_ADD, BTN_FAMILY, BTN_TODAY, kb_main, kb_want_subscription`, `from core.exceptions import LimitExceeded, LLMError`, `from core.services.family_service import change_family_timezone` (к существующим is_admin/update_digest_settings), `from core.services.limits import denial_text, subscription_active`.

В `_settings_text` убрать хвост про онбординг:

```python
        f"Часовой пояс: {family.timezone}"
```

Хендлеры — вставить ПОСЛЕ `on_set_hour`, ДО catch-all `on_set_denied`:

```python
@router.callback_query(F.data == "set:tz", IsAdmin())
async def on_tz_button(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.tz_city)
    await cb.message.answer(
        "Напишите ваш город (например: Москва, Дубай):", reply_markup=ForceReply()
    )
    await cb.answer()


@router.message(
    SettingsFlow.tz_city,
    F.text,
    ~F.text.in_({BTN_ADD, BTN_TODAY, BTN_FAMILY}),
    ~F.text.startswith("/"),
    IsAdmin(),
)
async def on_tz_city(
    message: Message, state: FSMContext, family: Family, db_session: AsyncSession
) -> None:
    try:
        tz = await change_family_timezone(db_session, family=family, city=message.text)
    except LimitExceeded as e:
        await state.clear()
        await message.answer(
            denial_text(e),
            reply_markup=None if subscription_active(family) else kb_want_subscription(),
        )
        return
    except LLMError:
        logger.exception("settings: tz detect failed family_id={}", family.id)
        await state.clear()
        await message.answer(
            "Не получилось определить таймзону. Попробуйте позже: /settings",
            reply_markup=kb_main(),
        )
        return
    if tz is None:
        await message.answer("Не узнал город, попробуйте иначе (например: Москва, Дубай).")
        return
    await state.clear()
    now_local = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
    # ForceReply вытеснил постоянную клавиатуру — возвращаем (паттерн 3613a1f)
    await message.answer(
        f"{emoji.DONE} Таймзона обновлена: {tz} (у вас сейчас {now_local})",
        reply_markup=kb_main(),
    )
```

Сразу ПОСЛЕ `on_tz_city` (и тоже до catch-all) — фолбэк на нетекстовый ввод в состоянии (стикер/фото; `~F.text` ловит только сообщения без текста — команды и кнопки НЕ съедаются, они падают в другие роутеры):

```python
@router.message(SettingsFlow.tz_city, ~F.text, IsAdmin())
async def on_tz_city_not_text(message: Message) -> None:
    await message.answer("Не узнал город, попробуйте текстом (например: Москва, Дубай).")
```

И тест к нему в `tests/unit/test_settings_handlers.py`:

```python
async def test_tz_city_non_text_prompts_again():
    message = AsyncMock()
    await settings_handler.on_tz_city_not_text(message)
    assert "текстом" in message.answer.await_args.args[0]
```

Существующий тест `_settings_text`/cmd_settings, если ассертил «задается городом», — обновить под новый текст.

- [ ] **Step 4: Прогон + Commit**

Run: `.venv/bin/ruff check . && .venv/bin/pytest -q` → PASS

```bash
git add core/emoji.py bot/ tests/unit/test_settings_handlers.py
git commit -m "feat(settings): change family timezone by city from /settings"
```

---

## Вне скоупа

- Смена таймзоны в онбординге (уже есть — по городу анкеты).
- Пресеты-кнопки, подтверждение, уведомление семье, обновление profile_md.
