# Stage 2: Планирование меню в боте — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Семья планирует меню прямо в боте: `/plan` → дата + длительность → LLM-черновик → замены блюд кнопками → утверждение с автосборкой списка покупок; free-text агент выключен фича-флагом.

**Architecture:** Новый сервис `core/services/menu_planner.py` генерирует черновик меню (status=draft) по `profile_md` и `plan_slots` семьи; утверждение переиспользует конфликт-логику menu_loader (`find_conflicting_meal_dates` / `delete_future_meals_on_dates`). Замены — расширение `dish_replacer` до 2–3 альтернатив без немедленного применения. Список покупок собирается отдельной LLM-операцией при утверждении (решение пользователя от 2026-07-20; в спеке «существующие механизмы» — их не существует, сборки из меню никогда не было). Права: управление семьёй, инвайты и весь флоу планирования — только админам (`IsAdmin`); админов может быть несколько (`grant_admin` без потери прав у прежнего), `can_plan` выведен из употребления.

**Tech Stack:** Python 3.12, aiogram 3 (FSM MemoryStorage), anthropic SDK, SQLAlchemy 2.0 async, pytest + pytest-asyncio.

**Reference spec:** [2026-07-20-multi-family-product-design.md](../specs/2026-07-20-multi-family-product-design.md) (§3, §4-уведомления, §5 частично, §8, §10 этап 2)

## Global Constraints

- Python `>=3.12`, ruff `line-length = 100`, select `["E","F","I","W","UP","B","ASYNC"]`.
- Все видимые юзеру тексты — на русском; эмодзи только из `core/emoji.py`.
- **Буква «ё» не используется** ни в каких текстах и файлах `bot/` и `core/`, включая промпты `core/prompts/*.md` — всегда «е» (гард `tests/unit/test_no_yo.py`). Кодовые блоки этого плана написаны ДО правила: при переносе в код заменять ё→е во всех строках.
- В боте есть постоянная reply-клавиатура `kb_main()` (кнопки Добавить/Сегодня/Семья, прикрепляется в /start, /help, финале онбординга) — не трогать её и не терять `reply_markup=kb_main()` при правках start.py; кнопку для /plan НЕ добавлять (вне скоупа reply-kb спеки).
- pytest: `asyncio_mode = "auto"`; integration-тесты — фикстура `db_session` из `tests/conftest.py` (in-memory SQLite).
- После каждого таска: `ruff check . && pytest -q` — зелёные. Каждый таск = минимум один коммит (conventional commits).
- **Жёсткий потолок длительности меню — 14 дней** (`MENU_MAX_DAYS = 14`), валидируется и в menu_planner, и в /load.
- Операции в `llm_usage`: `menu_gen | replace | recipe | profile | shopping`. Логировать **только при успехе** (спека §8: «retry считается в лимитах только при успехе»). **Enforcement лимитов триала (4/15/15) и месячного токен-потолка — этап 3**, в этом этапе только логирование.
- «Перегенерировать всё» считается отдельной генерацией в лимитах (= отдельная запись `menu_gen`).
- Невалидный JSON от LLM при **генерации меню** → один автоматический retry, затем дружелюбная ошибка с кнопкой «Попробовать ещё раз» (§8). Для замен/рецептов/списка покупок авто-retry нет — только кнопка/повторное нажатие.
- Free-text агент (`core/services/conversation.py`) НЕ удаляется — выключается фича-флагом `conversation_enabled` (default False).
- **Флоу /plan — под фича-флагом `planning_enabled` (default False):** при выключенном /plan отвечает заглушкой «планирование скоро появится», команда не анонсируется в BOT_COMMANDS и /help; бот полноценно работает через /load — можно раздавать семьям до готовности планирования. Включение — env, без релиза.
- `/load` остаётся скрытой admin-командой (нет в BOT_COMMANDS и /help), гейтится `IsAdmin`.
- **Права (обновление спеки §4 от 2026-07-20):** управление семьёй (/family с кнопками), /invite и весь флоу планирования (/plan, замены, утверждение, /load) — только `role=admin`. Админов может быть несколько; «Сделать админом» добавляет права, прежний админ ничего не теряет. Флаг `can_plan` нигде не читается (колонка остаётся, чистка — этап 3).
- **Жизненный цикл меню (спека §7):** строки `menus` не удаляются никогда (исключение — черновики /plan через `delete_draft`); меню живёт минимум до конца своего срока. `meals` удаляются только при явно подтверждённой юзером перезаписи конфликтных дат.
- Каждый таск оставляет бота рабочим для текущей семьи.

---

## File Structure (итог этапа)

```
config.py                                + conversation_enabled=False, planning_enabled=False
core/constants.py                        NEW: MENU_MAX_DAYS = 14
core/exceptions.py                       + MenuTooLong
core/emoji.py                            + RECIPE, REPLACE, REGEN
core/repositories.py                     _SLOT_ORDER + breakfast; + get_meal_for_family
core/meal_format.py                      + breakfast (лейбл, порядок); slot_label() публичная
core/tools.py                            slot-enum'ы + "breakfast"; вызовы с family_id
core/services/family_service.py          + get_admins, grant_admin; минус transfer_admin,
                                         set_can_plan, has_plan_rights, get_admin
core/services/menu_planner.py            NEW: generate_menu, delete_draft, preview/commit_approve,
                                         family_today, next_monday, parse_start_date
core/services/dish_replacer.py           suggest_replacements (2–3) + apply_replacement + usage log
core/services/recipe_service.py          + family_id, usage log
core/services/shopping_list.py           + build_from_menu (LLM), close_stale_menu_items
core/services/menu_loader.py             + проверка горизонта 14 дней
core/prompts/menu_planner.md             NEW
core/prompts/shopping_list_builder.md    NEW
core/prompts/dish_replacer.md            → 2–3 альтернативы
core/prompts/recipe.md                   генерализован (без магазинов и семейных запретов)
bot/fsm.py                               + PlanFlow
bot/keyboards.py                         + клавиатуры /plan и рецептов
bot/handlers/plan.py                     NEW: весь флоу /plan (только IsAdmin)
bot/handlers/menu.py                     кнопки «Рецепт» в /today и /menu + callback
bot/handlers/load.py                     гейт IsAdmin
bot/handlers/family.py                   мульти-админ: без тоггла can_plan, «сделать админом»
                                         = грант, join-уведомления всем админам
bot/handlers/profile.py                  отказ с именами админов (get_admins)
bot/handlers/freetext.py                 фича-флаг → подсказка со списком команд
bot/handlers/start.py                    help_text() функцией; строка /plan — по флагу
bot/main.py                              + plan router, /plan в BOT_COMMANDS
tests/unit + tests/integration           на всё выше
```

---

### Task 1: Breakfast в сортировке и лейблах (перенос из ревью этапа 1)

**Files:**
- Modify: `core/repositories.py:24` (`_SLOT_ORDER`)
- Modify: `core/meal_format.py`
- Modify: `core/tools.py` (два slot-enum'а в TOOL_SCHEMAS)
- Test: `tests/unit/test_meal_format.py`, `tests/integration/test_slot_order.py` (новый)

**Interfaces:**
- Produces: `meal_format.slot_label(slot: MealSlot) -> str` (используется тасками 5, 9, 10); `format_meal_lines` выводит завтрак → обед → ужин; `_SLOT_ORDER` сортирует breakfast=0, lunch=1, dinner=2.

- [ ] **Step 1: Падающие тесты**

В `tests/unit/test_meal_format.py` добавить:

```python
from core.meal_format import format_meal_lines, slot_label


def test_slot_label_covers_all_slots():
    assert slot_label(MealSlot.breakfast) == "Завтрак"
    assert slot_label(MealSlot.lunch) == "Обед"
    assert slot_label(MealSlot.dinner) == "Ужин"


def test_meal_lines_breakfast_first():
    meals = [
        Meal(date=date(2026, 7, 21), slot=MealSlot.dinner, dish_name="Ужин-блюдо", side_dishes=[]),
        Meal(date=date(2026, 7, 21), slot=MealSlot.breakfast, dish_name="Каша", side_dishes=[]),
    ]
    lines = format_meal_lines(meals)
    assert lines[0] == "<b>Завтрак:</b> Каша"
    assert lines[1] == "<b>Ужин:</b> Ужин-блюдо"
```

(импорты `date`, `Meal`, `MealSlot` уже есть в файле — проверить.)

Создать `tests/integration/test_slot_order.py`:

```python
from datetime import date

from core.db import Family, MealSlot
from core.repositories import approve_menu, create_draft_menu, get_meals_for_date


async def test_meals_for_date_ordered_breakfast_lunch_dinner(db_session):
    family = Family(name="f")
    db_session.add(family)
    await db_session.flush()
    d = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session,
        family_id=family.id,
        start_date=d,
        days_count=1,
        meals=[
            {"date": d, "slot": "dinner", "dish_name": "У", "protein_kind": "beef"},
            {"date": d, "slot": "breakfast", "dish_name": "З", "protein_kind": "mixed"},
            {"date": d, "slot": "lunch", "dish_name": "О", "protein_kind": "chicken"},
        ],
    )
    await approve_menu(db_session, menu.id)
    meals = await get_meals_for_date(db_session, family.id, d)
    assert [m.slot for m in meals] == [MealSlot.breakfast, MealSlot.lunch, MealSlot.dinner]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/unit/test_meal_format.py tests/integration/test_slot_order.py -q`
Expected: FAIL — `ImportError: cannot import name 'slot_label'`; порядок слотов неверный.

- [ ] **Step 3: Реализация**

`core/repositories.py` — заменить `_SLOT_ORDER`:

```python
# завтрак → обед → ужин; строковый порядок enum'а ("breakfast" < "dinner" < "lunch") не годится
_SLOT_ORDER = case(
    (Meal.slot == MealSlot.breakfast, 0),
    (Meal.slot == MealSlot.lunch, 1),
    else_=2,
)
```

`core/meal_format.py` — заменить `_SLOT_LABEL` и цикл:

```python
_SLOT_LABEL = {
    MealSlot.breakfast: "Завтрак",
    MealSlot.lunch: "Обед",
    MealSlot.dinner: "Ужин",
}


def slot_label(slot: MealSlot) -> str:
    return _SLOT_LABEL[slot]
```

и в `format_meal_lines`: `for slot in (MealSlot.breakfast, MealSlot.lunch, MealSlot.dinner):`

`core/tools.py` — в схемах `replace_meal` и `get_recipe_for_meal` заменить `"enum": ["lunch", "dinner"]` на `"enum": ["breakfast", "lunch", "dinner"]` (оба места).

- [ ] **Step 4: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/repositories.py core/meal_format.py core/tools.py tests/
git commit -m "feat(meals): wire MealSlot.breakfast into ordering and labels"
```

---

### Task 2: Потолок 14 дней в /load + /load только админам

**Files:**
- Create: `core/constants.py`
- Modify: `core/services/menu_loader.py:47-50` (`_validate_range`)
- Modify: `bot/handlers/load.py`
- Test: `tests/integration/test_menu_loader.py`

**Interfaces:**
- Produces: `core.constants.MENU_MAX_DAYS = 14` (используется тасками 7, 9); `/load` (документ + callbacks) доступен только админу.
- Consumes: `bot.filters.IsAdmin` (этап 1).

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_menu_loader.py` добавить (образец существующих тестов файла — сверить фикстуры):

```python
import json
from datetime import date, timedelta

import pytest

from core.constants import MENU_MAX_DAYS
from core.services.menu_loader import MenuLoadError, parse_raw
from core.services import menu_loader


def _menu_json(start: date, days: int) -> bytes:
    meals = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "slot": "dinner",
            "dish_name": f"Блюдо {i}",
            "protein_kind": "chicken",
        }
        for i in range(days)
    ]
    return json.dumps({"start_date": start.isoformat(), "meals": meals}).encode()


async def test_load_rejects_horizon_over_14_days(db_session):
    start = date(2026, 8, 1)
    with pytest.raises(MenuLoadError, match="14"):
        await menu_loader.preview_load(
            db_session, family_id=1, raw=_menu_json(start, MENU_MAX_DAYS + 1), today=start
        )


async def test_load_accepts_exactly_14_days(db_session):
    start = date(2026, 8, 1)
    preview = await menu_loader.preview_load(
        db_session, family_id=1, raw=_menu_json(start, MENU_MAX_DAYS), today=start
    )
    assert len(preview.parsed.meals) == MENU_MAX_DAYS
```

Run: `pytest tests/integration/test_menu_loader.py -q` → FAIL (ImportError на `core.constants`).

- [ ] **Step 2: Реализация**

Создать `core/constants.py`:

```python
"""Продуктовые константы, разделяемые сервисами."""

# Жёсткий потолок длительности меню (спека §3): страхует кастомные пути —
# свой ввод даты, /load, будущие фичи. Кнопок длиннее недели в UI нет.
MENU_MAX_DAYS = 14
```

`core/services/menu_loader.py` — расширить `_validate_range`:

```python
from core.constants import MENU_MAX_DAYS


def _validate_range(parsed: MenuFile) -> None:
    last_date = max(m.date for m in parsed.meals)
    if last_date < parsed.start_date:
        raise MenuLoadError("start_date позже последней даты в meals")
    horizon = (last_date - parsed.start_date).days + 1
    if horizon > MENU_MAX_DAYS:
        raise MenuLoadError(
            f"горизонт меню {horizon} дн. — максимум {MENU_MAX_DAYS} дн. от start_date"
        )
```

`bot/handlers/load.py` — /load только админу (скрытая команда, отказ не показываем):

```python
from bot.filters import HasFamily, IsAdmin

router.message.filter(HasFamily(), IsAdmin())
router.callback_query.filter(HasFamily(), IsAdmin())
```

- [ ] **Step 3: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/constants.py core/services/menu_loader.py bot/handlers/load.py tests/
git commit -m "feat(plan): 14-day menu horizon cap in /load, admin-gate /load"
```

---

### Task 2b: Мульти-админ — назначение без потери прав, can_plan выведен из употребления

**Files:**
- Modify: `core/services/family_service.py`, `bot/handlers/family.py`, `bot/handlers/profile.py`
- Test: `tests/integration/test_family_service.py`, `tests/integration/test_family_flow.py`

**Interfaces:**
- Produces (используется тасками 9, 11):
  - `get_admins(session, *, family_id: int) -> list[FamilyMember]` — все админы семьи по возрастанию id.
  - `grant_admin(session, *, family_id: int, member_id: int) -> FamilyMember` — назначает участника админом; прежние админы права НЕ теряют; raises `MemberNotInFamily`.
- Удаляются: `transfer_admin`, `set_can_plan`, `has_plan_rights`, `get_admin` — все вызовы чинятся в этом же таске. `can_plan` больше нигде не читается и не пишется (колонка остаётся в БД, удаление — этап 3).
- Consumes: `MemberRole`, `is_admin` (этап 1).

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_family_service.py`: заменить импорты (`get_admin`, `has_plan_rights`, `set_can_plan`, `transfer_admin` → `get_admins`, `grant_admin`), убрать ассерты `has_plan_rights` из существующих тестов, а `test_set_can_plan_and_transfer_admin` и `test_transfer_admin_rejects_member_from_other_family` заменить на:

```python
async def test_grant_admin_keeps_old_admin_rights(db_session):
    family, admin = await _make_family(db_session)
    _, joined = await join_by_invite(
        db_session, invite_code=family.invite_code, telegram_user_id=222, display_name="Вова"
    )
    await grant_admin(db_session, family_id=family.id, member_id=joined.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert {a.telegram_user_id for a in admins} == {111, 222}
    assert is_admin(admin) and is_admin(joined)  # прежний админ ничего не потерял


async def test_grant_admin_rejects_member_from_other_family(db_session):
    family, _ = await _make_family(db_session, tg_id=111)
    other_family, other_member = await _make_family(db_session, tg_id=333)
    with pytest.raises(MemberNotInFamily):
        await grant_admin(db_session, family_id=family.id, member_id=other_member.id)
    admins = await get_admins(db_session, family_id=family.id)
    assert len(admins) == 1
```

В `tests/integration/test_family_flow.py`: `get_admin` → `get_admins` (проверять `admins[0]` / состав списка).

Run: `pytest tests/integration/test_family_service.py -q` → FAIL (ImportError).

- [ ] **Step 2: `core/services/family_service.py`**

Удалить `has_plan_rights`, `set_can_plan`, `get_admin`, `transfer_admin`; из `create_family` убрать `can_plan=True`. Добавить:

```python
async def get_admins(session: AsyncSession, *, family_id: int) -> list[FamilyMember]:
    stmt = (
        select(FamilyMember)
        .where(
            FamilyMember.family_id == family_id,
            FamilyMember.role == MemberRole.admin,
        )
        .order_by(FamilyMember.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def grant_admin(
    session: AsyncSession, *, family_id: int, member_id: int
) -> FamilyMember:
    """Назначить участника администратором. Прежние админы права не теряют."""
    member = (
        await session.execute(
            select(FamilyMember).where(
                FamilyMember.id == member_id, FamilyMember.family_id == family_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise MemberNotInFamily
    member.role = MemberRole.admin
    await session.flush()
    return member
```

- [ ] **Step 3: `bot/handlers/family.py`**

- Импорты: `set_can_plan`, `transfer_admin`, `get_admin` → `get_admins`, `grant_admin`.
- Добавить хелпер имён админов (используется и в отказах):

```python
def _admin_names(admins) -> str:
    return ", ".join(_name(a.display_name, a.telegram_user_id) for a in admins) or "администратор"
```

- `start_with_invite`: блок уведомления админа заменить на цикл по всем админам:

```python
    admins = await get_admins(db_session, family_id=joined_family.id)
    member_name = _name(member.display_name, member.telegram_user_id)
    for admin in admins:
        if admin.telegram_user_id == member.telegram_user_id:
            continue
        try:
            await message.bot.send_message(
                admin.telegram_user_id,
                f"{emoji.FAMILY} {member_name} присоединился к семье",
            )
        except Exception:
            logger.warning(
                "family: join notification failed admin_id={}", admin.telegram_user_id
            )
```

- `cmd_invite_denied`: `admin = await get_admin(...)` → `name = _admin_names(await get_admins(db_session, family_id=family.id))`; текст «Приглашать может только администратор ({name}).»
- `_kb_family`: убрать кнопку `fam:plan:` (тоггл can_plan) целиком; для каждого участника-НЕ-админа оставить только кнопку `fam:admin:` с текстом f"{emoji.CROWN} сделать админом: ..."; пропуск по `is_admin(m)`, а не по `m.id == admin_id` (аргумент `admin_id` больше не нужен — убрать из сигнатуры и вызова).
- `cmd_family`: убрать суффикс «— может планировать» из строк списка.
- Хендлер `on_toggle_plan` удалить целиком.
- `on_transfer_admin` → `on_grant_admin`:

```python
@router.callback_query(F.data.startswith("fam:admin:"), IsAdmin())
async def on_grant_admin(cb: CallbackQuery, db_session, family) -> None:
    member_id = int(cb.data.split(":")[-1])
    try:
        member = await grant_admin(db_session, family_id=family.id, member_id=member_id)
    except MemberNotInFamily:
        await cb.answer("Участник не найден", show_alert=True)
        return
    name = _name(member.display_name, member.telegram_user_id)
    await cb.message.edit_text(
        f"{emoji.CROWN} {name} теперь администратор. /family — актуальный состав."
    )
    await cb.answer()
```

- [ ] **Step 4: `bot/handlers/profile.py`**

`on_edit_denied`: `get_admin` → `get_admins`, имя → перечисление имён (по образцу `_admin_names`; в profile.py достаточно инлайна с `html.escape`). Импорт поправить.

- [ ] **Step 5: Полный прогон + Commit**

Run: `ruff check . && pytest -q` → PASS (упавшие тесты family_flow/profile — починить импорты по Step 1).

```bash
git add core/services/family_service.py bot/handlers/family.py bot/handlers/profile.py tests/
git commit -m "feat(family): multiple admins — grant_admin keeps old admin, drop can_plan usage"
```

---

### Task 3: Фича-флаги — free-text агент и планирование

**Files:**
- Modify: `config.py`, `bot/handlers/start.py`, `bot/handlers/freetext.py`, `.env.example`
- Test: `tests/unit/test_freetext_flag.py` (новый)

**Interfaces:**
- Produces: `Settings.conversation_enabled: bool = False` (env `CONVERSATION_ENABLED`) и `Settings.planning_enabled: bool = False` (env `PLANNING_ENABLED`; используется Task 9 — заглушка /plan, условный анонс команды); `bot.handlers.start.help_text() -> str` (функция вместо константы, используется тасками 9). При выключенном `conversation_enabled` free-text отвечает подсказкой со списком команд, LLM не вызывается.

- [ ] **Step 1: Падающий тест**

Создать `tests/unit/test_freetext_flag.py`:

```python
"""Free-text агент выключен фича-флагом: вместо LLM — подсказка с командами."""
from unittest.mock import AsyncMock

from bot.handlers import freetext


async def test_freetext_disabled_replies_command_hint(monkeypatch):
    monkeypatch.setattr(freetext, "_conversation_enabled", lambda: False)
    called = False

    async def fake_handle(*a, **kw):
        nonlocal called
        called = True

    monkeypatch.setattr(freetext.conversation, "handle_message", fake_handle)

    message = AsyncMock()
    state = AsyncMock()
    state.get_state.return_value = None

    await freetext.handle_free_text(
        message, state, family=object(), family_member=object(), db_session=None
    )

    assert called is False
    reply = message.answer.await_args.args[0]
    # ответ — подсказка со списком команд
    assert "/menu" in reply and "/help" in reply
```

Run: `pytest tests/unit/test_freetext_flag.py -q` → FAIL.

- [ ] **Step 2: Реализация**

`config.py` — в `Settings` добавить:

```python
    conversation_enabled: bool = False
    planning_enabled: bool = False
```

`.env.example` — добавить строки `CONVERSATION_ENABLED=false` и `PLANNING_ENABLED=false`.

`bot/handlers/start.py` — заменить константу `_HELP_TEXT` функцией (условная строка /plan добавится в Task 9); оба хендлера файла вызывают `help_text()`:

```python
def help_text() -> str:
    lines = [
        "Я — семейный помощник для меню и покупок.",
        "",
        "Команды:",
        f"{emoji.MENU} /menu — текущее меню",
        f"{emoji.TODAY} /today — что готовить сегодня",
        f"{emoji.SHOPPING} /list — список покупок",
        f"{emoji.ADD} /add — добавить пункт в список",
        f"{emoji.PROFILE} /profile — профиль семьи",
        f"{emoji.FAMILY} /family — управление семьей",
        f"{emoji.INVITE} /invite — пригласить в семью",
        f"{emoji.HELP} /help — справка",
    ]
    return "\n".join(lines)
```

`bot/handlers/freetext.py` — в начало хендлера:

```python
from bot.handlers.start import help_text
from config import get_settings


def _conversation_enabled() -> bool:
    return get_settings().conversation_enabled


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(...) -> None:
    if await state.get_state() is not None:
        return
    if not _conversation_enabled():
        await message.answer(
            "Я понимаю команды, а не свободный текст. Вот что я умею:\n\n" + help_text()
        )
        return
    ...  # существующий код с conversation.handle_message без изменений
```

(обёртка `_conversation_enabled` — точка для monkeypatch в тестах, т.к. `get_settings` закэширован `lru_cache`.)

- [ ] **Step 3: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add config.py .env.example bot/handlers/start.py bot/handlers/freetext.py tests/unit/test_freetext_flag.py
git commit -m "feat(bot): conversation_enabled and planning_enabled feature flags"
```

---

### Task 4: recipe_service — usage-лог, family_id, генерализация промпта

**Files:**
- Modify: `core/services/recipe_service.py`, `core/prompts/recipe.md`, `core/tools.py:202-214`
- Test: `tests/integration/test_recipe_service.py`

**Interfaces:**
- Produces: `recipe_service.get_recipe(session, *, meal_id: int, profile_md: str, family_id: int) -> Recipe` — новый обязательный kwarg `family_id`; при генерации (не из кэша) пишет `llm_usage(operation="recipe")`. Промпт `recipe.md` без магазинов и семейных запретов (это теперь в profile_md).

- [ ] **Step 1: Падающий тест**

В `tests/integration/test_recipe_service.py` добавить `family_id=...` во все вызовы `get_recipe` (взять family_id из фикстур файла) и новый тест:

```python
from core.repositories import count_llm_operations


async def test_recipe_generation_logs_usage(db_session, ...):  # фикстуры как в соседних тестах
    # первый вызов — генерация
    await recipe_service.get_recipe(
        db_session, meal_id=meal.id, profile_md="п", family_id=family.id
    )
    assert await count_llm_operations(db_session, family_id=family.id, operation="recipe") == 1
    # второй — из кэша, счётчик не растёт
    await recipe_service.get_recipe(
        db_session, meal_id=meal.id, profile_md="п", family_id=family.id
    )
    assert await count_llm_operations(db_session, family_id=family.id, operation="recipe") == 1
```

(в файле уже есть мок LLM — переиспользовать его паттерн; сверить имена фикстур по месту.)

Run: `pytest tests/integration/test_recipe_service.py -q` → FAIL (TypeError: unexpected keyword).

- [ ] **Step 2: Реализация сервиса**

`core/services/recipe_service.py`:

```python
async def get_recipe(
    session: AsyncSession, *, meal_id: int, profile_md: str, family_id: int
) -> Recipe:
    """Return cached recipe or generate via LLM (logs llm_usage on generation)."""
    cached = await repositories.get_recipe(session, meal_id)
    if cached is not None:
        return cached

    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Блюдо: {meal.dish_name}. "
        f"Гарниры: {', '.join(meal.side_dishes or [])}. "
        f"Дай подробный рецепт; число порций — по составу семьи из контекста."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("recipe", profile_md=profile_md),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )

    try:
        data = parse_json_response(resp.text)
        validated = LLMRecipeResponse.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Could not parse recipe: {e}") from e

    recipe = await repositories.save_recipe(
        session,
        meal_id=meal_id,
        content_md=validated.content_md,
        ingredients=[i.model_dump() for i in validated.ingredients],
        prep_minutes=validated.prep_minutes,
    )
    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="recipe",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return recipe
```

(строку `logger.info("recipe gen: ...")` можно удалить — учёт теперь в БД; импорт `log_llm_usage` через `repositories`.)

`core/tools.py` `_tool_get_recipe_for_meal` — добавить `family_id=family_id` в вызов `recipe_service.get_recipe`.

- [ ] **Step 3: Генерализовать `core/prompts/recipe.md`**

Убрать из промпта всё пер-семейное (теперь это в profile_md):
- строку про 2 порции заменить на: «Число порций — по составу семьи из контекста; если состав не указан — 2 порции.»
- удалить список магазинов; поле `"store"` убрать из примера JSON и из требований (в примере ингредиента оставить `{"name": "Куриные бёдра", "quantity": "500", "unit": "г"}`);
- удалить последнюю строку «НЕ используй лук… индейку… чеснок» (семейные запреты приходят из контекста семьи);
- в требованиях добавить: «Строго соблюдай ограничения из контекста семьи.»

Остальное (формат Telegram HTML, структура, длина) — без изменений.

- [ ] **Step 4: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/services/recipe_service.py core/prompts/recipe.md core/tools.py tests/
git commit -m "feat(recipe): log llm_usage, family-agnostic prompt, family_id kwarg"
```

---

### Task 5: Кнопка «Рецепт» в /today и /menu

**Files:**
- Modify: `core/emoji.py`, `core/repositories.py`, `bot/keyboards.py`, `bot/handlers/menu.py`
- Test: `tests/unit/test_menu_keyboards.py` (новый), `tests/integration/test_repositories_meal_for_family.py` (новый)

**Interfaces:**
- Consumes: `recipe_service.get_recipe(..., family_id=...)` (Task 4), `meal_format.slot_label` (Task 1).
- Produces: `emoji.RECIPE = "📖"`; `repositories.get_meal_for_family(session, meal_id: int, *, family_id: int) -> Meal | None` (защита от чужого meal_id, используется тасками 10); `keyboards.kb_meal_recipes(meals) -> InlineKeyboardMarkup` (callback `meal:recipe:<meal_id>`); callback-хендлер показа рецепта в `bot/handlers/menu.py`.

- [ ] **Step 1: Падающие тесты**

Создать `tests/unit/test_menu_keyboards.py`:

```python
from datetime import date

from bot.keyboards import kb_meal_recipes
from core.db import Meal, MealSlot


def _meal(meal_id: int, slot: MealSlot, dish: str) -> Meal:
    m = Meal(date=date(2026, 7, 21), slot=slot, dish_name=dish, side_dishes=[])
    m.id = meal_id
    return m


def test_recipe_buttons_one_per_meal():
    kb = kb_meal_recipes([_meal(1, MealSlot.lunch, "Тефтели"), _meal(2, MealSlot.dinner, "Лосось")])
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert datas == ["meal:recipe:1", "meal:recipe:2"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert "Тефтели" in texts[0] and "Обед" in texts[0]
```

Создать `tests/integration/test_repositories_meal_for_family.py`:

```python
from datetime import date

from core.db import Family
from core.repositories import approve_menu, create_draft_menu, get_meal_for_family


async def test_get_meal_for_family_scopes_by_family(db_session):
    fam1, fam2 = Family(name="a"), Family(name="b")
    db_session.add_all([fam1, fam2])
    await db_session.flush()
    d = date(2026, 7, 21)
    menu = await create_draft_menu(
        db_session, family_id=fam1.id, start_date=d, days_count=1,
        meals=[{"date": d, "slot": "lunch", "dish_name": "О", "protein_kind": "chicken"}],
    )
    await approve_menu(db_session, menu.id)
    meal_id = menu.meals[0].id
    assert (await get_meal_for_family(db_session, meal_id, family_id=fam1.id)) is not None
    assert (await get_meal_for_family(db_session, meal_id, family_id=fam2.id)) is None
```

Run: оба файла → FAIL (ImportError).

- [ ] **Step 2: Реализация**

`core/emoji.py` — добавить:

```python
RECIPE = "📖"
REPLACE = "🔄"
REGEN = "♻️"
```

`core/repositories.py` — добавить:

```python
async def get_meal_for_family(
    session: AsyncSession, meal_id: int, *, family_id: int
) -> Meal | None:
    """Meal по id, только если он принадлежит меню этой семьи (защита callback-данных)."""
    stmt = (
        select(Meal)
        .join(Menu)
        .where(Meal.id == meal_id, Menu.family_id == family_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

`bot/keyboards.py` — добавить:

```python
from core.meal_format import slot_label


def kb_meal_recipes(meals) -> InlineKeyboardMarkup:
    """Кнопка «Рецепт» на каждое блюдо (/today, /menu)."""
    b = InlineKeyboardBuilder()
    for m in meals:
        b.button(
            text=f"{emoji.RECIPE} {slot_label(m.slot)} {m.date.strftime('%d.%m')}: {m.dish_name}",
            callback_data=f"meal:recipe:{m.id}",
        )
    b.adjust(1)
    return b.as_markup()
```

`bot/handlers/menu.py` — в `cmd_menu` и `cmd_today` добавить `reply_markup=kb_meal_recipes(meals)` к существующим `message.answer(...)` с меню; добавить callback:

```python
from aiogram import F
from aiogram.types import CallbackQuery
from loguru import logger

from bot.keyboards import kb_meal_recipes
from core.exceptions import LLMError
from core.services import recipe_service


@router.callback_query(F.data.startswith("meal:recipe:"))
async def cb_recipe(cb: CallbackQuery, family: Family, db_session: AsyncSession) -> None:
    meal_id = int(cb.data.split(":")[-1])
    meal = await repositories.get_meal_for_family(db_session, meal_id, family_id=family.id)
    if meal is None:
        await cb.answer("Блюдо не найдено (меню обновилось?)", show_alert=True)
        return
    await cb.answer()
    placeholder = await cb.message.answer(f"{emoji.WAIT} Готовлю рецепт...")
    try:
        recipe = await recipe_service.get_recipe(
            db_session, meal_id=meal.id, profile_md=family.profile_md or "", family_id=family.id
        )
    except LLMError:
        logger.exception("recipe generation failed meal_id={}", meal_id)
        await placeholder.edit_text("Не получилось приготовить рецепт. Нажмите кнопку ещё раз.")
        return
    await placeholder.edit_text(recipe.content_md)  # content_md уже в Telegram HTML
```

- [ ] **Step 3: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/emoji.py core/repositories.py bot/keyboards.py bot/handlers/menu.py tests/
git commit -m "feat(recipes): recipe button per dish in /today and /menu"
```

---

### Task 6: dish_replacer — 2–3 альтернативы + usage-лог

**Files:**
- Modify: `core/services/dish_replacer.py`, `core/prompts/dish_replacer.md`, `core/tools.py:182-199`
- Test: `tests/integration/test_dish_replacer.py`

**Interfaces:**
- Consumes: `log_llm_usage` (этап 1).
- Produces (используется Task 10 и tools.py):
  - `ReplacementOption(BaseModel)`: `dish_name: str`, `side_dishes: list[str] = []`, `protein_kind: ProteinKind` — сериализуется в FSM через `.model_dump(mode="json")` / `ReplacementOption.model_validate`.
  - `suggest_replacements(session, *, meal_id: int, hint: str | None, profile_md: str, family_id: int) -> list[ReplacementOption]` — 2–3 варианта, ничего не меняет в БД, при успехе пишет `llm_usage(operation="replace")`; raises `MealNotFound`, `LLMInvalidResponse`.
  - `apply_replacement(session, *, meal_id: int, option: ReplacementOption) -> Meal`.
  - `replace_meal(session, *, meal_id, hint, profile_md, family_id) -> Meal` — сохраняется для tools.py: suggest + apply первого варианта.

- [ ] **Step 1: Падающие тесты**

Переписать/дополнить `tests/integration/test_dish_replacer.py` (мок LLM — по образцу существующего в файле):

```python
import json

from core.repositories import count_llm_operations
from core.services.dish_replacer import (
    ReplacementOption,
    apply_replacement,
    suggest_replacements,
)

_ALTERNATIVES = json.dumps({
    "alternatives": [
        {"dish_name": "Лосось на пару", "side_dishes": ["рис"], "protein_kind": "fish"},
        {"dish_name": "Креветки вок", "side_dishes": ["лапша"], "protein_kind": "seafood"},
    ]
})


async def test_suggest_returns_options_and_logs_usage(db_session, ...):
    # мок LLM возвращает _ALTERNATIVES
    options = await suggest_replacements(
        db_session, meal_id=meal.id, hint="с рыбой", profile_md="п", family_id=family.id
    )
    assert [o.dish_name for o in options] == ["Лосось на пару", "Креветки вок"]
    # блюдо НЕ изменилось
    fresh = await repositories.get_meal(db_session, meal.id)
    assert fresh.dish_name != "Лосось на пару"
    assert await count_llm_operations(db_session, family_id=family.id, operation="replace") == 1


async def test_apply_replacement_updates_meal_and_drops_recipe(db_session, ...):
    option = ReplacementOption(dish_name="Лосось", side_dishes=["рис"], protein_kind="fish")
    meal2 = await apply_replacement(db_session, meal_id=meal.id, option=option)
    assert meal2.dish_name == "Лосось"


async def test_suggest_invalid_json_raises_and_logs_nothing(db_session, ...):
    # мок LLM возвращает "мусор"
    with pytest.raises(LLMInvalidResponse):
        await suggest_replacements(
            db_session, meal_id=meal.id, hint=None, profile_md="п", family_id=family.id
        )
    assert await count_llm_operations(db_session, family_id=family.id, operation="replace") == 0
```

(фикстуры meal/family и механизм мока — сверить по текущему содержимому файла; существующие тесты `replace_meal` обновить под новый kwarg `family_id` и ответ-«alternatives».)

Run: `pytest tests/integration/test_dish_replacer.py -q` → FAIL.

- [ ] **Step 2: Переписать `core/prompts/dish_replacer.md`**

```markdown
# Задача: варианты замены блюда

Тебе передадут текущее блюдо из меню и пожелание пользователя по замене.
Предложи 2–3 РАЗНЫХ варианта нового блюда, каждый — с гарнирами. Соблюдай
правила и ограничения из контекста семьи. Варианты должны заметно отличаться
друг от друга (разные белки или техники приготовления), если пожелание
пользователя не требует иного.

## Формат ответа

Верни СТРОГО валидный JSON, без markdown-фенсов, без пояснений:

```
{
  "alternatives": [
    {
      "dish_name": "Название",
      "side_dishes": ["гарнир1", "гарнир2"],
      "protein_kind": "chicken" | "fish" | "seafood" | "beef" | "pork" | "vegetarian" | "mixed"
    }
  ]
}
```
```

- [ ] **Step 3: Переписать `core/services/dish_replacer.py`**

```python
from functools import lru_cache

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.db import Meal, ProteinKind
from core.exceptions import LLMInvalidResponse, MealNotFound
from core.llm import LLMClient, build_system_blocks, parse_json_response


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class ReplacementOption(BaseModel):
    dish_name: str
    side_dishes: list[str] = Field(default_factory=list)
    protein_kind: ProteinKind


class _AlternativesSchema(BaseModel):
    alternatives: list[ReplacementOption] = Field(min_length=1, max_length=3)


async def suggest_replacements(
    session: AsyncSession,
    *,
    meal_id: int,
    hint: str | None,
    profile_md: str,
    family_id: int,
) -> list[ReplacementOption]:
    """2–3 варианта замены. Ничего не применяет; логирует usage при успехе."""
    meal = await repositories.get_meal(session, meal_id)
    if meal is None:
        raise MealNotFound(f"Meal {meal_id} not found")

    user_msg = (
        f"Текущее блюдо: {meal.dish_name} "
        f"(гарниры: {', '.join(meal.side_dishes or [])}, белок: {meal.protein_kind.value}). "
        f"Дата: {meal.date.isoformat()}, приём: {meal.slot.value}. "
        f"Пожелание пользователя: {hint or 'просто другое блюдо'}. "
        f"Предложи 2–3 варианта замены."
    )
    llm = get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("dish_replacer", profile_md=profile_md),
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    )
    try:
        data = parse_json_response(resp.text)
        parsed = _AlternativesSchema.model_validate(data)
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse replacement options: {e}") from e

    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="replace",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return parsed.alternatives


async def apply_replacement(
    session: AsyncSession, *, meal_id: int, option: ReplacementOption
) -> Meal:
    return await repositories.update_meal(
        session,
        meal_id=meal_id,
        dish_name=option.dish_name,
        side_dishes=option.side_dishes,
        protein_kind=option.protein_kind,
    )


async def replace_meal(
    session: AsyncSession, *, meal_id: int, hint: str | None, profile_md: str, family_id: int
) -> Meal:
    """Однократная замена (для tool-use агента): первый предложенный вариант."""
    options = await suggest_replacements(
        session, meal_id=meal_id, hint=hint, profile_md=profile_md, family_id=family_id
    )
    return await apply_replacement(session, meal_id=meal_id, option=options[0])
```

`core/tools.py` `_tool_replace_meal` — добавить `family_id=family_id` в вызов `dish_replacer.replace_meal`.

- [ ] **Step 4: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS (обновить упавшие тесты conversation/tools, если мокают старый ответ dish_replacer).

```bash
git add core/services/dish_replacer.py core/prompts/dish_replacer.md core/tools.py tests/
git commit -m "feat(replace): 2-3 alternatives from dish_replacer + usage logging"
```

---

### Task 7: Сервис menu_planner + промпт

**Files:**
- Create: `core/services/menu_planner.py`, `core/prompts/menu_planner.md`
- Modify: `core/exceptions.py`
- Test: `tests/integration/test_menu_planner.py` (новый), `tests/unit/test_plan_dates.py` (новый)

**Interfaces:**
- Consumes: `create_draft_menu`, `find_conflicting_meal_dates`, `delete_future_meals_on_dates`, `approve_menu`, `log_llm_usage` (repositories); `MealDTO`; `MENU_MAX_DAYS` (Task 2).
- Produces (используется тасками 9–11):
  - `MenuTooLong(ChefBotError)` в `core/exceptions.py`.
  - `generate_menu(session, *, family: Family, start_date: date, days_count: int, llm: LLMClient | None = None) -> Menu` — черновик (status=draft) с meals; 1 авто-retry на невалидный JSON; `llm_usage(operation="menu_gen")` при успехе; raises `MenuTooLong`, `LLMInvalidResponse`, `LLMError`.
  - `delete_draft(session, *, menu_id: int) -> None` — удаляет меню только если оно draft.
  - `preview_approve(session, *, menu: Menu, today: date) -> set[date]` — конфликтные даты.
  - `commit_approve(session, *, menu: Menu, today: date) -> None` — удаляет чужие активные meals на датах меню и активирует.
  - `family_today(family: Family) -> date` — сегодня в таймзоне семьи (fallback UTC).
  - `next_monday(today: date) -> date` — сегодня, если понедельник, иначе ближайший будущий.
  - `parse_start_date(text: str, today: date) -> date | None` — `ДД.ММ`, `ДД.ММ.ГГГГ`, `ГГГГ-ММ-ДД`; прошлое → None.

- [ ] **Step 1: Падающие unit-тесты дат**

Создать `tests/unit/test_plan_dates.py`:

```python
from datetime import date

from core.services.menu_planner import next_monday, parse_start_date

TODAY = date(2026, 7, 22)  # среда


def test_next_monday_from_wednesday():
    assert next_monday(TODAY) == date(2026, 7, 27)


def test_next_monday_on_monday_is_today():
    assert next_monday(date(2026, 7, 27)) == date(2026, 7, 27)


def test_parse_start_date_formats():
    assert parse_start_date("25.07.2026", TODAY) == date(2026, 7, 25)
    assert parse_start_date("2026-07-25", TODAY) == date(2026, 7, 25)
    assert parse_start_date("25.07", TODAY) == date(2026, 7, 25)


def test_parse_start_date_short_form_rolls_to_next_year():
    assert parse_start_date("05.01", TODAY) == date(2027, 1, 5)


def test_parse_start_date_rejects_past_and_garbage():
    assert parse_start_date("01.07.2026", TODAY) is None
    assert parse_start_date("послезавтра", TODAY) is None
```

- [ ] **Step 2: Падающие integration-тесты генерации**

Создать `tests/integration/test_menu_planner.py`:

```python
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from core.constants import MENU_MAX_DAYS
from core.db import Family, Menu, MenuStatus
from core.exceptions import LLMInvalidResponse, MenuTooLong
from core.llm import LLMResponse
from core.repositories import count_llm_operations, get_future_meals
from core.services import menu_planner

START = date(2026, 7, 27)


class FakeLLM:
    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(text=self._texts.pop(0), tokens_in=100, tokens_out=200)


def _ok_menu(days: int = 3, start: date = START) -> str:
    meals = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        meals.append({"date": d, "slot": "lunch", "dish_name": f"Обед {i}",
                      "side_dishes": ["рис"], "protein_kind": "chicken"})
        meals.append({"date": d, "slot": "dinner", "dish_name": f"Ужин {i}",
                      "side_dishes": [], "protein_kind": "fish"})
    return json.dumps({"meals": meals})


async def _family(db_session) -> Family:
    fam = Family(name="f", profile_md="# Профиль", plan_slots=["lunch", "dinner"])
    db_session.add(fam)
    await db_session.flush()
    return fam


async def test_generate_menu_creates_draft(db_session):
    fam = await _family(db_session)
    menu = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    assert menu.status == MenuStatus.draft
    assert len(menu.meals) == 6
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 1
    # черновик не виден в активном календаре
    assert await get_future_meals(db_session, fam.id, START) == []


async def test_generate_menu_retries_once_then_fails(db_session):
    fam = await _family(db_session)
    llm = FakeLLM(["мусор", _ok_menu(3)])
    menu = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=llm
    )
    assert llm.calls == 2 and len(menu.meals) == 6

    llm2 = FakeLLM(["мусор", "мусор"])
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3, llm=llm2
        )
    # неуспех не логируется: только одна запись от первой генерации
    assert await count_llm_operations(db_session, family_id=fam.id, operation="menu_gen") == 1


async def test_generate_menu_rejects_over_cap(db_session):
    fam = await _family(db_session)
    with pytest.raises(MenuTooLong):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START,
            days_count=MENU_MAX_DAYS + 1, llm=FakeLLM([]),
        )


async def test_generate_menu_rejects_meals_outside_range(db_session):
    fam = await _family(db_session)
    bad = json.dumps({"meals": [{
        "date": "2026-09-01", "slot": "lunch", "dish_name": "Чужая дата",
        "side_dishes": [], "protein_kind": "chicken",
    }]})
    with pytest.raises(LLMInvalidResponse):
        await menu_planner.generate_menu(
            db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([bad, bad])
        )


async def test_approve_flow_with_conflicts(db_session):
    fam = await _family(db_session)
    first = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    assert await menu_planner.preview_approve(db_session, menu=first, today=START) == set()
    await menu_planner.commit_approve(db_session, menu=first, today=START)
    assert len(await get_future_meals(db_session, fam.id, START)) == 6

    second = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    conflicts = await menu_planner.preview_approve(db_session, menu=second, today=START)
    assert len(conflicts) == 3
    await menu_planner.commit_approve(db_session, menu=second, today=START)
    # старые meals на конфликтных датах удалены, осталось 6 новых
    assert len(await get_future_meals(db_session, fam.id, START)) == 6


async def test_menu_lives_until_its_end_menus_never_deleted(db_session):
    """Спека §7 (жизненный цикл): строки menus не удаляются никогда; при
    перезаписи страдают только meals на конфликтных датах — неперекрытые дни
    старого меню доживают до своего конца."""
    fam = await _family(db_session)
    first = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    await menu_planner.commit_approve(db_session, menu=first, today=START)

    # второе меню перекрывает только последний день первого (START+2)
    overlap_start = START + timedelta(days=2)
    second = await menu_planner.generate_menu(
        db_session, family=fam, start_date=overlap_start, days_count=3,
        llm=FakeLLM([_ok_menu(3, start=overlap_start)]),
    )
    await menu_planner.commit_approve(db_session, menu=second, today=START)

    meals = await get_future_meals(db_session, fam.id, START)
    # дни 0–1 первого меню (4 блюда) + 3 дня второго (6 блюд)
    assert len(meals) == 10
    menus = list(
        (await db_session.execute(select(Menu).where(Menu.family_id == fam.id)))
        .scalars()
        .all()
    )
    assert len(menus) == 2  # оба меню живы, ни одна строка menus не удалена


async def test_delete_draft_only_deletes_draft(db_session):
    fam = await _family(db_session)
    menu = await menu_planner.generate_menu(
        db_session, family=fam, start_date=START, days_count=3, llm=FakeLLM([_ok_menu(3)])
    )
    await menu_planner.delete_draft(db_session, menu_id=menu.id)
    await menu_planner.delete_draft(db_session, menu_id=999)  # no-op, не падает
```

Run: оба файла → FAIL (нет модуля).

- [ ] **Step 3: Написать `core/prompts/menu_planner.md`**

```markdown
# Задача: генерация меню

Ты — планировщик семейного меню. Тебе передадут список дат и приёмов пищи.
Составь меню, строго соблюдая правила и ограничения из контекста семьи.

## Правила

- Планируй ТОЛЬКО указанные даты и ТОЛЬКО указанные приёмы пищи — ни больше,
  ни меньше: на каждую дату — каждый из указанных приёмов ровно один раз.
- Чередуй белки между днями и приёмами (не два одинаковых белка подряд),
  если ограничения семьи не требуют иного.
- Не повторяй одно и то же блюдо в рамках этого меню.
- К каждому обеду и ужину — гарнир(ы) в side_dishes; блюдо и гарниры — раздельно.
- Названия блюд — по-русски, коротко и конкретно («Куриные бёдра в духовке»,
  не «Вкусная курочка»).
- Учитывай лимит времени готовки и предпочтения из контекста семьи.

## Формат ответа

Верни СТРОГО один JSON-объект, без markdown-фенсов, без пояснений:

```
{
  "meals": [
    {
      "date": "YYYY-MM-DD",
      "slot": "breakfast" | "lunch" | "dinner",
      "dish_name": "Название блюда",
      "side_dishes": ["гарнир1", "гарнир2"],
      "protein_kind": "chicken" | "fish" | "seafood" | "beef" | "pork" | "vegetarian" | "mixed"
    }
  ]
}
```
```

- [ ] **Step 4: Реализовать `core/services/menu_planner.py`**

```python
"""Генерация меню в боте: черновик по профилю семьи → правки → утверждение."""
from datetime import date as DateType
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core import repositories
from core.constants import MENU_MAX_DAYS
from core.db import Family, Menu, MenuStatus
from core.exceptions import LLMInvalidResponse, MenuTooLong
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.meal_format import slot_label
from core.models import MealDTO


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _MenuSchema(BaseModel):
    meals: list[MealDTO] = Field(min_length=1)


def family_today(family: Family) -> DateType:
    try:
        tz = ZoneInfo(family.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def next_monday(today: DateType) -> DateType:
    return today if today.weekday() == 0 else today + timedelta(days=7 - today.weekday())


def parse_start_date(text: str, today: DateType) -> DateType | None:
    text = text.strip()
    parsed: DateType | None = None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.strptime(text, "%d.%m").date().replace(year=today.year)
            if parsed < today:
                parsed = parsed.replace(year=today.year + 1)
        except ValueError:
            return None
    return parsed if parsed >= today else None


def _user_message(family: Family, dates: list[DateType]) -> str:
    slots = family.plan_slots or ["lunch", "dinner"]
    slot_names = ", ".join(slot_label(MealSlot(s)) for s in slots)
    date_lines = "\n".join(f"- {d.isoformat()} ({d.strftime('%a')})" for d in dates)
    return (
        f"Составь меню на {len(dates)} дн.\n"
        f"Приёмы пищи: {slot_names} (slot-значения: {', '.join(slots)}).\n"
        f"Даты:\n{date_lines}"
    )


def _validate_generated(parsed: _MenuSchema, dates: list[DateType], slots: list[str]) -> None:
    allowed_dates = set(dates)
    for m in parsed.meals:
        if m.date not in allowed_dates:
            raise LLMInvalidResponse(f"meal date {m.date} вне запрошенного диапазона")
        if m.slot.value not in slots:
            raise LLMInvalidResponse(f"slot {m.slot.value} не входит в plan_slots семьи")


async def generate_menu(
    session: AsyncSession,
    *,
    family: Family,
    start_date: DateType,
    days_count: int,
    llm: LLMClient | None = None,
) -> Menu:
    """Черновик меню от LLM. 1 авто-retry на невалидный JSON; usage — при успехе."""
    if not 1 <= days_count <= MENU_MAX_DAYS:
        raise MenuTooLong(f"меню не длиннее {MENU_MAX_DAYS} дней")
    slots = family.plan_slots or ["lunch", "dinner"]
    dates = [start_date + timedelta(days=i) for i in range(days_count)]
    llm = llm or get_llm_client()

    messages = [{"role": "user", "content": _user_message(family, dates)}]
    system_blocks = build_system_blocks("menu_planner", profile_md=family.profile_md or "")
    tokens_in = tokens_out = 0
    last_error: LLMInvalidResponse | None = None
    for _ in range(2):  # 1 попытка + 1 retry (спека §8)
        resp = await llm.chat(system_blocks=system_blocks, messages=messages, max_tokens=4096)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out
        try:
            parsed = _MenuSchema.model_validate(parse_json_response(resp.text))
            _validate_generated(parsed, dates, slots)
        except (LLMInvalidResponse, ValueError) as e:
            last_error = e if isinstance(e, LLMInvalidResponse) else LLMInvalidResponse(str(e))
            continue
        menu = await repositories.create_draft_menu(
            session,
            family_id=family.id,
            start_date=start_date,
            days_count=days_count,
            meals=[m.model_dump(mode="python") for m in parsed.meals],
        )
        await repositories.log_llm_usage(
            session,
            family_id=family.id,
            operation="menu_gen",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return menu
    raise last_error


async def delete_draft(session: AsyncSession, *, menu_id: int) -> None:
    menu = await session.get(Menu, menu_id)
    if menu is not None and menu.status == MenuStatus.draft:
        await session.delete(menu)
        await session.flush()


async def preview_approve(
    session: AsyncSession, *, menu: Menu, today: DateType
) -> set[DateType]:
    """Даты, на которых у семьи уже есть активные meals (конфликт при утверждении)."""
    return await repositories.find_conflicting_meal_dates(
        session,
        family_id=menu.family_id,
        dates={m.date for m in menu.meals},
        from_date=today,
    )


async def commit_approve(session: AsyncSession, *, menu: Menu, today: DateType) -> None:
    """Активирует черновик, перезаписывая чужие активные meals на его датах."""
    await repositories.delete_future_meals_on_dates(
        session,
        family_id=menu.family_id,
        dates=[m.date for m in menu.meals],
        from_date=today,
    )
    await repositories.approve_menu(session, menu.id)
```

(в импорты добавить `from core.db import MealSlot` для `_user_message`.)

`core/exceptions.py` — добавить:

```python
class MenuTooLong(ChefBotError):
    """Запрошенная длительность меню превышает MENU_MAX_DAYS."""
```

- [ ] **Step 5: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/services/menu_planner.py core/prompts/menu_planner.md core/exceptions.py tests/
git commit -m "feat(plan): menu_planner service — LLM draft, approve with conflict overwrite"
```

---

### Task 8: Список покупок из меню (отдельная LLM-операция)

**Files:**
- Modify: `core/services/shopping_list.py`, `core/db.py:209` (комментарий operation)
- Create: `core/prompts/shopping_list_builder.md`
- Test: `tests/integration/test_shopping_list.py`

**Interfaces:**
- Consumes: `ShoppingList`, `ShoppingItem`, `log_llm_usage`.
- Produces (используется Task 11):
  - `close_stale_menu_items(session, *, family_id: int) -> int` — закрывает (bought=True) открытые пункты, привязанные к спискам прошлых меню (`shopping_list_id IS NOT NULL`); ручные пункты (/add, `shopping_list_id IS NULL`) не трогает. Возвращает число закрытых.
  - `build_from_menu(session, *, family_id: int, menu: Menu, profile_md: str, llm: LLMClient | None = None) -> list[ShoppingItem]` — LLM-сборка списка по блюдам меню; закрывает устаревшие пункты, создаёт `ShoppingList(menu_id=...)` + items; `llm_usage(operation="shopping")` при успехе; raises `LLMInvalidResponse`, `LLMError`. Авто-retry НЕТ (в хендлере — кнопка «Попробовать ещё раз»).

- [ ] **Step 1: Падающие тесты**

В `tests/integration/test_shopping_list.py` добавить:

```python
import json
from datetime import date

from core.db import Family
from core.llm import LLMResponse
from core.repositories import count_llm_operations, create_draft_menu, get_open_shopping_items
from core.services import shopping_list

_ITEMS = json.dumps({"items": [
    {"name": "Куриные бёдра", "quantity": "1 кг"},
    {"name": "Рис", "quantity": "500 г"},
]})


class FakeLLM:
    def __init__(self, texts):
        self._texts = list(texts)

    async def chat(self, **kwargs):
        return LLMResponse(text=self._texts.pop(0), tokens_in=50, tokens_out=60)


async def _family_with_menu(db_session):
    fam = Family(name="f")
    db_session.add(fam)
    await db_session.flush()
    d = date(2026, 7, 27)
    menu = await create_draft_menu(
        db_session, family_id=fam.id, start_date=d, days_count=1,
        meals=[{"date": d, "slot": "dinner", "dish_name": "Курица с рисом",
                "side_dishes": ["салат"], "protein_kind": "chicken"}],
    )
    return fam, menu


async def test_build_from_menu_creates_items_and_logs(db_session):
    fam, menu = await _family_with_menu(db_session)
    items = await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    assert [i.name for i in items] == ["Куриные бёдра", "Рис"]
    assert all(i.shopping_list_id is not None for i in items)
    assert await count_llm_operations(db_session, family_id=fam.id, operation="shopping") == 1


async def test_build_from_menu_closes_stale_keeps_manual(db_session):
    fam, menu = await _family_with_menu(db_session)
    manual = await shopping_list.add_manual_item(db_session, family_id=fam.id, name="Молоко")
    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    # второе меню: пункты первого закрываются, ручной остаётся
    _, menu2 = await _family_with_menu(db_session)
    await shopping_list.build_from_menu(
        db_session, family_id=fam.id, menu=menu2, profile_md="п", llm=FakeLLM([_ITEMS])
    )
    open_names = {i.name for i in await get_open_shopping_items(db_session, family_id=fam.id)}
    assert "Молоко" in open_names
    assert len(open_names) == 3  # молоко + 2 новых
```

Run: `pytest tests/integration/test_shopping_list.py -q` → FAIL.

- [ ] **Step 2: Промпт `core/prompts/shopping_list_builder.md`**

```markdown
# Задача: список покупок по меню

Тебе передадут блюда меню (с гарнирами) по дням. Составь единый список покупок
на все эти блюда с учётом состава семьи из контекста (количества — на всех).

## Правила

- Агрегируй одинаковые ингредиенты из разных блюд в один пункт (суммируй количество).
- НЕ включай базовые продукты, которые обычно всегда есть дома: соль, перец,
  растительное/оливковое масло, специи, сахар. Если в контексте семьи описана
  своя «базовая кладовка» — не включай и её.
- Количества — практичные для покупки («1 кг», «2 шт», «500 г»), по-русски.
- Порядок: сначала мясо/рыба, затем овощи и фрукты, крупы и гарниры, остальное.

## Формат ответа

Верни СТРОГО один JSON-объект, без markdown-фенсов, без пояснений:

```
{"items": [{"name": "Куриные бёдра", "quantity": "1 кг"}]}
```
```

- [ ] **Step 3: Реализация в `core/services/shopping_list.py`**

Добавить:

```python
from functools import lru_cache

from pydantic import BaseModel, Field
from sqlalchemy import select

from core import repositories
from core.db import Menu, ShoppingList
from core.exceptions import LLMInvalidResponse
from core.llm import LLMClient, build_system_blocks, parse_json_response
from core.meal_format import format_dish_with_sides, slot_label


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()


class _ItemSchema(BaseModel):
    name: str
    quantity: str = ""


class _ShoppingSchema(BaseModel):
    items: list[_ItemSchema] = Field(min_length=1)


async def close_stale_menu_items(session: AsyncSession, *, family_id: int) -> int:
    """Закрыть открытые пункты прошлых меню. Ручные пункты (/add) не трогаем."""
    stmt = select(ShoppingItem).where(
        ShoppingItem.family_id == family_id,
        ShoppingItem.bought.is_(False),
        ShoppingItem.shopping_list_id.is_not(None),
    )
    items = list((await session.execute(stmt)).scalars().all())
    for item in items:
        await repositories.mark_shopping_item_bought(session, item.id, bought=True)
    return len(items)


def _menu_as_text(menu: Menu) -> str:
    lines = []
    for m in sorted(menu.meals, key=lambda m: (m.date, m.slot.value)):
        lines.append(
            f"{m.date.isoformat()} · {slot_label(m.slot)}: "
            f"{format_dish_with_sides(m.dish_name, m.side_dishes)}"
        )
    return "\n".join(lines)


async def build_from_menu(
    session: AsyncSession,
    *,
    family_id: int,
    menu: Menu,
    profile_md: str,
    llm: LLMClient | None = None,
) -> list[ShoppingItem]:
    """LLM-сборка списка покупок по блюдам меню (operation="shopping")."""
    llm = llm or get_llm_client()
    resp = await llm.chat(
        system_blocks=build_system_blocks("shopping_list_builder", profile_md=profile_md),
        messages=[{"role": "user", "content": f"Меню:\n{_menu_as_text(menu)}"}],
        max_tokens=2048,
    )
    try:
        parsed = _ShoppingSchema.model_validate(parse_json_response(resp.text))
    except Exception as e:
        raise LLMInvalidResponse(f"Failed to parse shopping list: {e}") from e

    await close_stale_menu_items(session, family_id=family_id)
    sl = ShoppingList(menu_id=menu.id)
    session.add(sl)
    await session.flush()
    items = [
        ShoppingItem(
            shopping_list_id=sl.id, family_id=family_id, name=i.name, quantity=i.quantity
        )
        for i in parsed.items
    ]
    session.add_all(items)
    await session.flush()
    await repositories.log_llm_usage(
        session,
        family_id=family_id,
        operation="shopping",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
    )
    return items
```

В `core/db.py:209` обновить комментарий: `# menu_gen|replace|recipe|profile|shopping`.

- [ ] **Step 4: Прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add core/services/shopping_list.py core/prompts/shopping_list_builder.md core/db.py tests/
git commit -m "feat(shopping): build shopping list from approved menu via LLM"
```

---

### Task 9: /plan — выбор даты, длительности, генерация черновика

**Files:**
- Modify: `bot/fsm.py`, `bot/keyboards.py`, `bot/main.py`, `bot/handlers/start.py`
- Create: `bot/handlers/plan.py`
- Test: `tests/unit/test_plan_keyboards.py` (новый), `tests/unit/test_plan_handlers.py` (новый)

**Interfaces:**
- Consumes: `menu_planner.generate_menu/family_today/next_monday/parse_start_date` (Task 7), `IsAdmin` (этап 1), `get_admins` (Task 2b), `slot_label`/`format_meal_lines` (Task 1).
- Produces: роутер `bot.handlers.plan.router` (регистрируется в main после profile, до menu; **весь флоу — только админам**); FSM `PlanFlow`; клавиатуры `kb_plan_start`, `kb_plan_duration`, `kb_plan_draft`, `kb_retry`; функции `_show_draft`, `_generate_and_show`, `_notify_admins` (используются тасками 10–11); формат черновика `_format_draft(menu)`. Callback-префикс `plan:`. При выключенном `planning_enabled` (Task 3) /plan отвечает заглушкой «скоро», команда не попадает в BOT_COMMANDS и /help.
- Хранение в FSM data: `{"menu_id": int, "start_date": "<iso>", "days": int}`.

- [ ] **Step 1: Падающие тесты клавиатур**

Создать `tests/unit/test_plan_keyboards.py`:

```python
from bot.keyboards import kb_plan_draft, kb_plan_duration, kb_plan_start, kb_retry


def _datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_plan_start_buttons():
    datas = _datas(kb_plan_start())
    assert datas == ["plan:date:today", "plan:date:tomorrow", "plan:date:monday", "plan:date:custom"]


def test_plan_duration_buttons():
    assert _datas(kb_plan_duration()) == ["plan:days:3", "plan:days:5", "plan:days:7"]


def test_plan_draft_actions():
    datas = _datas(kb_plan_draft())
    assert datas == ["plan:replace", "plan:regen", "plan:approve"]


def test_retry_keyboard():
    assert _datas(kb_retry("plan:regen")) == ["plan:regen"]
```

Run → FAIL.

- [ ] **Step 2: Клавиатуры и FSM**

`bot/keyboards.py` — добавить:

```python
def kb_plan_start() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Сегодня", callback_data="plan:date:today")
    b.button(text="Завтра", callback_data="plan:date:tomorrow")
    b.button(text="Понедельник", callback_data="plan:date:monday")
    b.button(text=f"{emoji.EDIT} Своя дата", callback_data="plan:date:custom")
    b.adjust(3, 1)
    return b.as_markup()


def kb_plan_duration() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in (3, 5, 7):
        b.button(text=f"{n} дн.", callback_data=f"plan:days:{n}")
    b.adjust(3)
    return b.as_markup()


def kb_plan_draft() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.REPLACE} Заменить блюдо", callback_data="plan:replace")
    b.button(text=f"{emoji.REGEN} Перегенерировать всё", callback_data="plan:regen")
    b.button(text=f"{emoji.DONE} Утвердить", callback_data="plan:approve")
    b.adjust(1)
    return b.as_markup()


def kb_retry(callback: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.REFRESH} Попробовать ещё раз", callback_data=callback)
    return b.as_markup()
```

`bot/fsm.py` — добавить:

```python
class PlanFlow(StatesGroup):
    start_date = State()
    custom_date = State()
    duration = State()
    draft = State()
    replace_pick = State()
    replace_alts = State()
    replace_hint = State()
    approve_confirm = State()
```

- [ ] **Step 3: Хендлеры `bot/handlers/plan.py` (часть 1)**

```python
"""Флоу /plan: дата → длительность → LLM-черновик → правки → утверждение."""
import html
from datetime import date as DateType
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters import HasFamily, IsAdmin
from bot.keyboards import (
    kb_plan_draft,
    kb_plan_duration,
    kb_plan_start,
    kb_retry,
)
from config import get_settings
from core import emoji, repositories
from core.db import Family, FamilyMember, Menu
from core.exceptions import LLMError
from core.meal_format import format_meal_lines
from core.ru_format import format_date_short
from core.services import menu_planner
from core.services.family_service import get_admins

router = Router()
router.message.filter(HasFamily())
router.callback_query.filter(HasFamily(), IsAdmin())


def _planning_enabled() -> bool:
    return get_settings().planning_enabled


async def _planning_disabled_filter(message: Message) -> bool:
    return not _planning_enabled()


@router.message(Command("plan"), _planning_disabled_filter)
async def cmd_plan_disabled(message: Message) -> None:
    """Фича-флаг выключен: бот раздаётся до готовности планирования (спека §3)."""
    await message.answer(
        f"{emoji.MENU} Планирование меню в боте скоро появится. "
        "Пока меню загружает администратор семьи."
    )


@router.message(Command("plan"), IsAdmin())
async def cmd_plan(message: Message, state: FSMContext, family: Family) -> None:
    await state.clear()
    await state.set_state(PlanFlow.start_date)
    await message.answer("С какого дня планируем меню?", reply_markup=kb_plan_start())


@router.message(Command("plan"))
async def cmd_plan_denied(message: Message, db_session: AsyncSession, family: Family) -> None:
    admins = await get_admins(db_session, family_id=family.id)
    names = ", ".join(_actor_name(a) for a in admins) or "администратор"
    await message.answer(
        f"Планировать меню могут только администраторы ({names}). "
        "Попросите назначить вас администратором в /family."
    )


@router.callback_query(PlanFlow.start_date, F.data.startswith("plan:date:"))
async def on_start_date(cb: CallbackQuery, state: FSMContext, family: Family) -> None:
    choice = cb.data.split(":")[-1]
    today = menu_planner.family_today(family)
    if choice == "custom":
        await state.set_state(PlanFlow.custom_date)
        await cb.message.answer(
            "Напишите дату старта (например, 28.07):",
            reply_markup=ForceReply(input_field_placeholder="ДД.ММ или ДД.ММ.ГГГГ"),
        )
        await cb.answer()
        return
    start = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "monday": menu_planner.next_monday(today),
    }[choice]
    await _ask_duration(cb.message, state, start)
    await cb.answer()


@router.message(PlanFlow.custom_date, F.text)
async def on_custom_date(message: Message, state: FSMContext, family: Family) -> None:
    today = menu_planner.family_today(family)
    start = menu_planner.parse_start_date(message.text or "", today)
    if start is None:
        await message.answer(
            "Не понял дату. Формат: ДД.ММ или ДД.ММ.ГГГГ, не в прошлом. Попробуйте ещё раз.",
            reply_markup=ForceReply(input_field_placeholder="например, 28.07"),
        )
        return
    await _ask_duration(message, state, start)


async def _ask_duration(message: Message, state: FSMContext, start: DateType) -> None:
    await state.update_data(start_date=start.isoformat())
    await state.set_state(PlanFlow.duration)
    await message.answer(
        f"Старт: {format_date_short(start)}. На сколько дней?",
        reply_markup=kb_plan_duration(),
    )


@router.callback_query(PlanFlow.duration, F.data.startswith("plan:days:"))
async def on_duration(
    cb: CallbackQuery,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    await state.update_data(days=int(cb.data.split(":")[-1]))
    await cb.answer()
    await _generate_and_show(cb.message, state, family, family_member, db_session)


def _format_draft(menu: Menu) -> str:
    sections = [
        f"<b>{emoji.MENU} Черновик меню · {menu.days_count} дн. с "
        f"{menu.start_date.strftime('%d.%m.%Y')}</b>"
    ]
    for day in sorted({m.date for m in menu.meals}):
        day_meals = [m for m in menu.meals if m.date == day]
        sections.append(
            "\n".join([f"{emoji.TOMORROW} {format_date_short(day)}", *format_meal_lines(day_meals)])
        )
    return "\n\n".join(sections)


async def _generate_and_show(
    message: Message,
    state: FSMContext,
    family: Family,
    family_member: FamilyMember,
    db_session: AsyncSession,
) -> None:
    data = await state.get_data()
    start = DateType.fromisoformat(data["start_date"])
    days = data["days"]
    placeholder = await message.answer(f"{emoji.WAIT} Готовлю меню...")
    try:
        menu = await menu_planner.generate_menu(
            db_session, family=family, start_date=start, days_count=days
        )
    except LLMError:  # LLMInvalidResponse — подкласс; авто-retry уже был внутри
        logger.exception("plan: menu generation failed family_id={}", family.id)
        await state.set_state(PlanFlow.duration)
        await placeholder.edit_text(
            "Не получилось сгенерировать меню.",
            reply_markup=kb_retry(f"plan:days:{days}"),
        )
        return
    await state.update_data(menu_id=menu.id)
    await state.set_state(PlanFlow.draft)
    await placeholder.edit_text(_format_draft(menu), reply_markup=kb_plan_draft())
    await _notify_admins(
        message, db_session, family, family_member,
        f"{emoji.MENU} {_actor_name(family_member)} сгенерировал(а) черновик меню "
        f"на {days} дн. с {start.strftime('%d.%m.%Y')}",
    )


def _actor_name(member: FamilyMember) -> str:
    return html.escape(member.display_name) if member.display_name else str(member.telegram_user_id)


async def _notify_admins(
    message: Message,
    db_session: AsyncSession,
    family: Family,
    actor: FamilyMember,
    text: str,
) -> None:
    """Спека §4: о генерации/утверждении меню уведомляются остальные админы."""
    for admin in await get_admins(db_session, family_id=family.id):
        if admin.telegram_user_id == actor.telegram_user_id:
            continue
        try:
            await message.bot.send_message(admin.telegram_user_id, text)
        except Exception:
            logger.warning(
                "plan: admin notification failed admin_id={}", admin.telegram_user_id
            )
```

(импорт `PlanFlow` из `bot.fsm` добавить в начало.)

- [ ] **Step 4: Регистрация в main + /help**

`bot/main.py`:
- `from bot.handlers import plan as plan_handler`
- `dp.include_router(plan_handler.router)` — после `profile_handler`, до `menu_handler`;
- константу `BOT_COMMANDS` заменить функцией (команда /plan анонсируется только при включённом флаге):

```python
def bot_commands(*, planning_enabled: bool) -> list[BotCommand]:
    commands = [
        BotCommand(command="menu", description="Текущее меню"),
        BotCommand(command="today", description="Что готовить сегодня"),
        BotCommand(command="list", description="Список покупок"),
        BotCommand(command="add", description="Добавить пункт в список"),
        BotCommand(command="profile", description="Профиль семьи"),
        BotCommand(command="family", description="Управление семьёй"),
        BotCommand(command="invite", description="Пригласить в семью"),
        BotCommand(command="help", description="Справка"),
    ]
    if planning_enabled:
        commands.insert(2, BotCommand(command="plan", description="Спланировать меню"))
    return commands
```

и в `main()`: `await bot.set_my_commands(bot_commands(planning_enabled=settings.planning_enabled))`.

`bot/handlers/start.py` — в `help_text()` строка /plan появляется только при включённом флаге; заменить фрагмент списка:

```python
        f"{emoji.TODAY} /today — что готовить сегодня",
        *(
            [f"{emoji.MENU} /plan — спланировать меню"]
            if get_settings().planning_enabled
            else []
        ),
        f"{emoji.SHOPPING} /list — список покупок",
```

(добавить `from config import get_settings` в импорты start.py.)

- [ ] **Step 5: Хендлер-тесты**

Создать `tests/unit/test_plan_handlers.py` (паттерн `tests/unit/test_onboarding_handlers.py`):

```python
"""Хендлер-тесты /plan на AsyncMock (без aiogram-харнесса)."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers import plan as plan_handler
from core.exceptions import LLMInvalidResponse


def _family(**kw):
    return SimpleNamespace(
        id=1, timezone="UTC", plan_slots=["lunch", "dinner"], profile_md="п", **kw
    )


async def test_generation_failure_shows_retry(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad json twice")

    monkeypatch.setattr(plan_handler.menu_planner, "generate_menu", boom)
    message, state = AsyncMock(), AsyncMock()
    state.get_data.return_value = {"start_date": "2026-07-27", "days": 5}
    member = SimpleNamespace(display_name="Юля", telegram_user_id=1, role="admin")

    await plan_handler._generate_and_show(message, state, _family(), member, db_session=None)

    placeholder = message.answer.return_value
    placeholder.edit_text.assert_awaited_once()
    assert "Не получилось" in placeholder.edit_text.await_args.args[0]


async def test_custom_date_rejects_garbage():
    message, state = AsyncMock(), AsyncMock()
    message.text = "вчера"
    await plan_handler.on_custom_date(message, state, _family())
    assert "Не понял дату" in message.answer.await_args.args[0]
    state.update_data.assert_not_awaited()


async def test_planning_disabled_filter_reads_flag(monkeypatch):
    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: False)
    assert await plan_handler._planning_disabled_filter(AsyncMock()) is True
    monkeypatch.setattr(plan_handler, "_planning_enabled", lambda: True)
    assert await plan_handler._planning_disabled_filter(AsyncMock()) is False


async def test_plan_stub_when_flag_off():
    message = AsyncMock()
    await plan_handler.cmd_plan_disabled(message)
    assert "скоро" in message.answer.await_args.args[0]
```

Run: `pytest tests/unit/test_plan_keyboards.py tests/unit/test_plan_handlers.py -q` → PASS

- [ ] **Step 6: Полный прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add bot/ tests/
git commit -m "feat(plan): /plan flow — start date, duration, LLM draft with actions"
```

---

### Task 10: /plan — замена блюда и перегенерация

**Files:**
- Modify: `bot/handlers/plan.py`, `bot/keyboards.py`
- Test: `tests/unit/test_plan_keyboards.py`, `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Consumes: `suggest_replacements`, `apply_replacement`, `ReplacementOption` (Task 6); `get_meal_for_family` (Task 5); `delete_draft`, `generate_menu` (Task 7); `_generate_and_show`, `_format_draft` (Task 9).
- Produces: клавиатуры `kb_plan_meals(meals)` (`plan:rm:<meal_id>` + `plan:back`), `kb_plan_alternatives(n)` (`plan:alt:<i>`, `plan:althint`, `plan:back`). FSM data при замене: `replace_meal_id: int`, `alternatives: list[dict]` (`model_dump(mode="json")`).

- [ ] **Step 1: Падающие тесты клавиатур**

В `tests/unit/test_plan_keyboards.py` добавить:

```python
from datetime import date

from bot.keyboards import kb_plan_alternatives, kb_plan_meals
from core.db import Meal, MealSlot


def test_plan_meals_button_per_meal_plus_back():
    m = Meal(date=date(2026, 7, 27), slot=MealSlot.lunch, dish_name="Тефтели", side_dishes=[])
    m.id = 42
    datas = _datas(kb_plan_meals([m]))
    assert datas == ["plan:rm:42", "plan:back"]


def test_plan_alternatives_numbered_plus_hint_and_back():
    datas = _datas(kb_plan_alternatives(3))
    assert datas == ["plan:alt:0", "plan:alt:1", "plan:alt:2", "plan:althint", "plan:back"]
```

Run → FAIL.

- [ ] **Step 2: Клавиатуры**

`bot/keyboards.py`:

```python
def kb_plan_meals(meals) -> InlineKeyboardMarkup:
    """Выбор блюда для замены в черновике."""
    b = InlineKeyboardBuilder()
    for m in meals:
        b.button(
            text=f"{m.date.strftime('%d.%m')} · {slot_label(m.slot)}: {m.dish_name}",
            callback_data=f"plan:rm:{m.id}",
        )
    b.button(text=f"{emoji.ARROW} Назад к черновику", callback_data="plan:back")
    b.adjust(1)
    return b.as_markup()


def kb_plan_alternatives(count: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(count):
        b.button(text=f"Вариант {i + 1}", callback_data=f"plan:alt:{i}")
    b.button(text=f"{emoji.EDIT} Своё пожелание", callback_data="plan:althint")
    b.button(text=f"{emoji.ARROW} Назад к черновику", callback_data="plan:back")
    b.adjust(count, 1, 1)
    return b.as_markup()
```

- [ ] **Step 3: Хендлеры замен в `bot/handlers/plan.py`**

```python
from bot.keyboards import kb_plan_alternatives, kb_plan_meals
from core.meal_format import format_dish_with_sides, slot_label
from core.services.dish_replacer import (
    ReplacementOption,
    apply_replacement,
    suggest_replacements,
)


async def _draft_menu(state: FSMContext, db_session: AsyncSession, family: Family) -> Menu | None:
    data = await state.get_data()
    menu_id = data.get("menu_id")
    if menu_id is None:
        return None
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    return menu if menu is not None and menu.family_id == family.id else None


async def _show_draft(message: Message, state: FSMContext, menu: Menu) -> None:
    await state.set_state(PlanFlow.draft)
    await message.edit_text(_format_draft(menu), reply_markup=kb_plan_draft())


@router.callback_query(PlanFlow.draft, F.data == "plan:replace")
async def on_replace(cb: CallbackQuery, state: FSMContext, family: Family,
                     db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await state.set_state(PlanFlow.replace_pick)
    await cb.message.edit_text("Какое блюдо заменить?", reply_markup=kb_plan_meals(menu.meals))
    await cb.answer()


@router.callback_query(PlanFlow.replace_pick, F.data.startswith("plan:rm:"))
async def on_pick_meal(cb: CallbackQuery, state: FSMContext, family: Family,
                       db_session: AsyncSession) -> None:
    meal_id = int(cb.data.split(":")[-1])
    await state.update_data(replace_meal_id=meal_id)
    await cb.answer()
    await _suggest_and_show(cb.message, state, family, db_session, hint=None)


@router.message(PlanFlow.replace_hint, F.text)
async def on_replace_hint(message: Message, state: FSMContext, family: Family,
                          db_session: AsyncSession) -> None:
    # скоуп-ограниченный ввод: одна строка пожелания, не свободный чат (спека §3)
    await _suggest_and_show(message, state, family, db_session, hint=message.text.strip())


async def _suggest_and_show(message: Message, state: FSMContext, family: Family,
                            db_session: AsyncSession, *, hint: str | None) -> None:
    data = await state.get_data()
    meal_id = data["replace_meal_id"]
    meal = await repositories.get_meal_for_family(db_session, meal_id, family_id=family.id)
    if meal is None:
        await message.answer("Блюдо не найдено — начните заново: /plan")
        return
    placeholder = await message.answer(f"{emoji.WAIT} Подбираю варианты...")
    try:
        options = await suggest_replacements(
            db_session, meal_id=meal_id, hint=hint,
            profile_md=family.profile_md or "", family_id=family.id,
        )
    except LLMError:
        logger.exception("plan: suggest replacements failed meal_id={}", meal_id)
        await placeholder.edit_text("Не получилось подобрать замену. Выберите блюдо ещё раз.")
        await state.set_state(PlanFlow.replace_pick)
        return
    await state.update_data(alternatives=[o.model_dump(mode="json") for o in options])
    await state.set_state(PlanFlow.replace_alts)
    lines = [f"Замена для «{meal.dish_name}» ({slot_label(meal.slot)}):", ""]
    for i, o in enumerate(options, 1):
        lines.append(f"<b>{i}.</b> {format_dish_with_sides(o.dish_name, o.side_dishes)}")
    await placeholder.edit_text("\n".join(lines), reply_markup=kb_plan_alternatives(len(options)))


@router.callback_query(PlanFlow.replace_alts, F.data.startswith("plan:alt:"))
async def on_pick_alternative(cb: CallbackQuery, state: FSMContext, family: Family,
                              db_session: AsyncSession) -> None:
    idx = int(cb.data.split(":")[-1])
    data = await state.get_data()
    raw = data.get("alternatives", [])
    if idx >= len(raw):
        await cb.answer("Вариант не найден", show_alert=True)
        return
    option = ReplacementOption.model_validate(raw[idx])
    await apply_replacement(db_session, meal_id=data["replace_meal_id"], option=option)
    menu = await _draft_menu(state, db_session, family)
    await cb.answer(f"Заменил на: {option.dish_name}")
    await _show_draft(cb.message, state, menu)


@router.callback_query(PlanFlow.replace_alts, F.data == "plan:althint")
async def on_ask_hint(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PlanFlow.replace_hint)
    await cb.message.answer(
        "Опишите пожелание одной строкой (например, «что-то с рыбой, побыстрее»):",
        reply_markup=ForceReply(input_field_placeholder="ваше пожелание"),
    )
    await cb.answer()


@router.callback_query(PlanFlow.replace_pick, F.data == "plan:back")
@router.callback_query(PlanFlow.replace_alts, F.data == "plan:back")
async def on_back_to_draft(cb: CallbackQuery, state: FSMContext, family: Family,
                           db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await cb.answer()
    await _show_draft(cb.message, state, menu)


@router.callback_query(PlanFlow.draft, F.data == "plan:regen")
async def on_regenerate(cb: CallbackQuery, state: FSMContext, family: Family,
                        family_member: FamilyMember, db_session: AsyncSession) -> None:
    # отдельная генерация в лимитах (спека §3); старый черновик удаляем
    data = await state.get_data()
    if data.get("menu_id"):
        await menu_planner.delete_draft(db_session, menu_id=data["menu_id"])
    await cb.answer()
    await _generate_and_show(cb.message, state, family, family_member, db_session)
```

- [ ] **Step 4: Хендлер-тест замены**

В `tests/unit/test_plan_handlers.py` добавить:

```python
async def test_pick_alternative_out_of_range_alerts():
    cb, state = AsyncMock(), AsyncMock()
    cb.data = "plan:alt:5"
    state.get_data.return_value = {"alternatives": [], "replace_meal_id": 1}
    await plan_handler.on_pick_alternative(cb, state, _family(), db_session=None)
    cb.answer.assert_awaited_once()
    assert cb.answer.await_args.kwargs.get("show_alert") is True
```

Run: `pytest tests/unit/test_plan_handlers.py tests/unit/test_plan_keyboards.py -q` → PASS

- [ ] **Step 5: Полный прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add bot/handlers/plan.py bot/keyboards.py tests/
git commit -m "feat(plan): dish replacement with alternatives and full regeneration"
```

---

### Task 11: /plan — утверждение: конфликты, список покупок, уведомление админа

**Files:**
- Modify: `bot/handlers/plan.py`, `bot/keyboards.py`
- Test: `tests/unit/test_plan_handlers.py`

**Interfaces:**
- Consumes: `preview_approve`, `commit_approve`, `family_today` (Task 7); `build_from_menu` (Task 8); `kb_confirm_overwrite`-паттерн; `_notify_admins` (Task 9).
- Produces: callback'и `plan:approve`, `plan:approveyes`, `plan:approveno`, `plan:shoplist:<menu_id>` (ретрай сборки списка вне FSM — состояние к этому моменту очищено).

- [ ] **Step 1: Клавиатура подтверждения**

`bot/keyboards.py`:

```python
def kb_plan_approve_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{emoji.DONE} Да, перезаписать", callback_data="plan:approveyes")
    b.button(text=f"{emoji.CANCEL} Нет", callback_data="plan:approveno")
    b.adjust(2)
    return b.as_markup()
```

(тест в `tests/unit/test_plan_keyboards.py` по образцу соседних: datas == `["plan:approveyes", "plan:approveno"]`.)

- [ ] **Step 2: Хендлеры утверждения**

`bot/handlers/plan.py`:

```python
from bot.keyboards import kb_plan_approve_confirm
from core.services import shopping_list


@router.callback_query(PlanFlow.draft, F.data == "plan:approve")
async def on_approve(cb: CallbackQuery, state: FSMContext, family: Family,
                     family_member: FamilyMember, db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    today = menu_planner.family_today(family)
    conflicts = await menu_planner.preview_approve(db_session, menu=menu, today=today)
    if conflicts:
        dates_str = ", ".join(d.strftime("%d.%m.%Y") for d in sorted(conflicts))
        await state.set_state(PlanFlow.approve_confirm)
        await cb.message.edit_text(
            f"На даты {dates_str} уже есть меню. Перезаписать?",
            reply_markup=kb_plan_approve_confirm(),
        )
        await cb.answer()
        return
    await cb.answer()
    await _do_approve(cb.message, state, family, family_member, db_session, menu, today)


@router.callback_query(PlanFlow.approve_confirm, F.data == "plan:approveyes")
async def on_approve_yes(cb: CallbackQuery, state: FSMContext, family: Family,
                         family_member: FamilyMember, db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    if menu is None:
        await cb.answer("Черновик не найден — начните заново: /plan", show_alert=True)
        return
    await cb.answer()
    await _do_approve(
        cb.message, state, family, family_member, db_session,
        menu, menu_planner.family_today(family),
    )


@router.callback_query(PlanFlow.approve_confirm, F.data == "plan:approveno")
async def on_approve_no(cb: CallbackQuery, state: FSMContext, family: Family,
                        db_session: AsyncSession) -> None:
    menu = await _draft_menu(state, db_session, family)
    await cb.answer()
    if menu is not None:
        await _show_draft(cb.message, state, menu)


async def _do_approve(message: Message, state: FSMContext, family: Family,
                      family_member: FamilyMember, db_session: AsyncSession,
                      menu: Menu, today) -> None:
    await menu_planner.commit_approve(db_session, menu=menu, today=today)
    await state.clear()
    await message.edit_text(
        f"{emoji.DONE} Меню утверждено: {menu.days_count} дн. с "
        f"{menu.start_date.strftime('%d.%m.%Y')}. Смотреть: /menu"
    )
    await _notify_admins(
        message, db_session, family, family_member,
        f"{emoji.DONE} {_actor_name(family_member)} утвердил(а) меню на "
        f"{menu.days_count} дн. с {menu.start_date.strftime('%d.%m.%Y')}",
    )
    await _build_shopping(message, family, db_session, menu)


async def _build_shopping(message: Message, family: Family,
                          db_session: AsyncSession, menu: Menu) -> None:
    placeholder = await message.answer(f"{emoji.SHOPPING} Собираю список покупок...")
    try:
        items = await shopping_list.build_from_menu(
            db_session, family_id=family.id, menu=menu, profile_md=family.profile_md or ""
        )
    except LLMError:
        logger.exception("plan: shopping list build failed menu_id={}", menu.id)
        await placeholder.edit_text(
            "Меню утверждено, но список покупок собрать не получилось.",
            reply_markup=kb_retry(f"plan:shoplist:{menu.id}"),
        )
        return
    await placeholder.edit_text(
        f"{emoji.SHOPPING} Список покупок готов: {len(items)} пунктов. Смотреть: /list"
    )


@router.callback_query(F.data.startswith("plan:shoplist:"))
async def on_shoplist_retry(cb: CallbackQuery, family: Family,
                            db_session: AsyncSession) -> None:
    """Ретрай сборки списка после утверждения (вне FSM — state уже очищен)."""
    menu_id = int(cb.data.split(":")[-1])
    menu = await repositories.get_menu_with_meals(db_session, menu_id)
    if menu is None or menu.family_id != family.id:
        await cb.answer("Меню не найдено", show_alert=True)
        return
    await cb.answer()
    await _build_shopping(cb.message, family, db_session, menu)
```

- [ ] **Step 3: Хендлер-тест**

В `tests/unit/test_plan_handlers.py` добавить:

```python
async def test_shopping_failure_keeps_menu_approved_and_offers_retry(monkeypatch):
    async def boom(*a, **kw):
        raise LLMInvalidResponse("bad")

    monkeypatch.setattr(plan_handler.shopping_list, "build_from_menu", boom)
    message = AsyncMock()
    menu = SimpleNamespace(id=7, days_count=5, start_date=date(2026, 7, 27), meals=[])

    await plan_handler._build_shopping(message, _family(), db_session=None, menu=menu)

    placeholder = message.answer.return_value
    text = placeholder.edit_text.await_args.args[0]
    assert "утверждено" in text and "список покупок" in text
    assert placeholder.edit_text.await_args.kwargs["reply_markup"] is not None
```

Run: `pytest tests/unit/test_plan_handlers.py -q` → PASS

- [ ] **Step 4: Полный прогон + Commit**

Run: `ruff check . && pytest -q` → PASS

```bash
git add bot/handlers/plan.py bot/keyboards.py tests/
git commit -m "feat(plan): approve flow — conflict overwrite, shopping list build, admin notify"
```

---

### Task 12: Финализация — роадмап, полный прогон, smoke

**Files:**
- Modify: `docs/superpowers/ROADMAP.md` (секция «В работе»: ссылка на план этапа 2)
- Test: полный прогон + ручной smoke-чеклист

- [ ] **Step 1: ROADMAP**

В секцию «В работе» после ссылки на план этапа 1 добавить:

```markdown
План этапа 2:
[2026-07-20-stage2-planning.md](plans/2026-07-20-stage2-planning.md).
```

- [ ] **Step 2: Полный прогон**

Run: `ruff check . && pytest -q`
Expected: PASS, 0 ошибок ruff.

- [ ] **Step 3: Ручной smoke (локально, реальный бот + свой Telegram)**

Чеклист (не автоматизируется):
1. `/plan` → «Сегодня» → 5 дн. → черновик приходит, «Готовлю меню…» редактируется.
2. «Заменить блюдо» → выбрать → 2–3 варианта → «Своё пожелание» → вариант применяется, черновик обновлён.
3. «Утвердить» → меню в `/menu`, список в `/list`, старые menu-пункты закрыты, ручные целы.
4. Повторный `/plan` на те же даты → предупреждение о перезаписи.
5. `/today` → кнопка «Рецепт» → рецепт приходит; повторное нажатие — мгновенно (кэш).
6. Свободный текст → подсказка со списком команд (агент выключен).
7. Обычный участник: `/plan` → «Планировать меню могут только администраторы…»; в `/family` «сделать админом» → его `/plan` работает, прежний админ права сохранил (в `/family` две короны) и получает уведомления о генерации и утверждении вторым админом.
8. `/family` у обычного участника — список без кнопок; кнопки «план:» нет ни у кого.
9. `/load` от не-админа игнорируется; JSON длиннее 14 дней — отказ с пояснением.
10. После перезаписи части дат новым меню: неперекрытые дни старого меню на месте (`/menu`), старое меню дожило до своего конца.
11. `PLANNING_ENABLED=false` (default): `/plan` → заглушка «скоро появится», в меню команд и `/help` строки /plan нет; `PLANNING_ENABLED=true` → пункты 1–4 и 7 работают, /plan анонсирован.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/ROADMAP.md
git commit -m "docs(roadmap): link stage 2 plan"
```

---

## Что осознанно НЕ входит в этап 2 (этап 3 по спеке §10)

- Enforcement лимитов триала (4 меню / 15 замен / 15 рецептов, по `count_llm_operations`) и месячного токен-потолка (`MONTHLY_TOKEN_CAP_PER_FAMILY = 500_000`) — здесь только логирование операций, включая новую `shopping`. **В этап 3: решить, входит ли `shopping` в лимиты триала** (решение о самой операции принято 2026-07-20).
- Per-family таймзона/час дайджеста, `/settings`, напоминание «меню заканчивается» за 2 дня.
- Удаление колонки `family_members.can_plan` (deprecated с 2026-07-20, нигде не читается) — отдельной миграцией при следующей чистке схемы.

## Отложено финальным ревью этапа 2 (2026-07-21) — включить в план этапа 3

- Тестовый долг: конфликт-ветка `on_approve`, успешный путь `_build_shopping`, чужой `menu_id` в `plan:shoplist`, ValueError-ветка `on_pick_alternative`, флаг-условные `bot_commands()`/`help_text()`, enabled-путь `handle_free_text`, суммирование токенов retry по значению, join-уведомления при 2+ админах.
- Команды (`/menu` и т.п.) проглатываются text-хендлерами состояний (`custom_date`, `replace_hint`, `profile.py::on_new_text`) — добавить `~F.text.startswith("/")`.
- `%a` в `_user_message` menu_planner → русские аббревиатуры дней.
- Сиротские draft-меню копятся при брошенных/перезапущенных `/plan` — дешевый cleanup в `cmd_plan` (delete_draft старого menu_id до state.clear) или периодическая чистка.
- `parse_start_date("29.02")` коротким форматом всегда None (1900 не високосный).
- Stale-клавиатура `kb_plan_meals` остается видимой под «Подбираю варианты...» (UX-нит).
- Пул соединений PG при долгих LLM-вызовах (мидлварь держит сессию весь хендлер — при генерации меню это десятки секунд; для беты терпимо, для этапа 3 — вынести LLM-вызовы из-под сессии или расширить пул).
