# Chef-Bot — Phase 4 Design

**Дата:** 2026-05-27
**Статус:** approved
**Базовая спека:** [2026-05-25-chef-bot-design.md](2026-05-25-chef-bot-design.md)

---

## Скоуп

Три фичи из фазы 4 MVP-спеки:

- **#3 Утренний дайджест** — ежедневное сообщение в 8:00 Asia/Bangkok со сегодняшним и завтрашним меню + статичная подсказка про разморозку.
- **#5 Напоминания о незакупленном** — ежедневное сообщение в 19:00 Asia/Bangkok, если в списке есть открытые пункты.
- **#6 Ручной чек-лист `/add`** — простая slash-команда для добавления пункта в общий список покупок.

Фаза не меняет схему БД.

---

## Архитектурные решения

### Шедулер: native asyncio (без APScheduler)

Базовая спека упоминала APScheduler 4 авансом, но для двух фиксированных cron-задач это избыточная зависимость с persistent job store. Реализуем шедулер как две долгоживущие `asyncio.Task`, каждая считает следующее срабатывание через `zoneinfo("Asia/Bangkok")` и спит до него. Stateless: при рестарте бот пересчитывает next-fire от текущего момента.

Когда расписание станет конфигурируемым (например, `/digesttime`), миграция на APScheduler тривиальна.

### Получатели: все family_members

Сейчас в `family_members` только один пользователь. Шедулер итерирует по всем `family_members` всех `families` и шлёт каждому. Когда добавится партнёр — автоматически начнёт получать. Per-member opt-out отложим до момента, когда он реально понадобится.

### Без LLM в фазе 4

Все три фичи — детерминированные. Никаких API-вызовов Claude. Это делает 8:00/19:00-уведомления дешёвыми и устойчивыми к падению Anthropic API.

---

## Компоненты

### `bot/scheduler.py` (new)

```python
def seconds_until_next(hour: int, minute: int, tz: ZoneInfo, now: datetime) -> float:
    """Секунды до следующего HH:MM в указанной TZ, считая от `now`."""

async def start_scheduler(bot: Bot, sessionmaker) -> list[asyncio.Task]:
    """Запускает фоновые таски, возвращает список для cancel при shutdown."""
```

Две внутренние корутины:
- `_morning_digest_loop(bot, sm)` — спит до 8:00 BKK, шлёт дайджест, повторяет
- `_shopping_reminder_loop(bot, sm)` — то же для 19:00

Обе ловят и логируют ошибки внутри одной итерации (чтобы Claude API или Telegram-flake не убивали таск).

### `core/services/digest.py` (new)

```python
async def build_morning_digest(session, *, family_id, today: date) -> str | None:
    """Возвращает текст или None, если на сегодня и завтра в активном меню нет блюд."""
```

Формат:
```
🌅 Сегодня (вторник, 27 мая)
🍴 Обед: Том кха с курицей
🍽 Ужин: Лосось с овощами

📅 Завтра (среда, 28 мая)
🍴 Обед: Стейк рибай с салатом
🍽 Ужин: Креветки в чесночном соусе

🥶 Не забудь поставить разморозку, если надо
```

Если на оба дня нет блюд → вернуть `None` (активного меню нет / закончилось).
Если есть на один из дней — показать что есть.

Дни недели и месяцы — русские, статичный словарь (без `babel`).

### `core/services/reminders.py` (new)

```python
async def build_shopping_reminder(session, *, family_id) -> str | None:
    """Короткое напоминание со счётчиком, или None если всё куплено."""
```

Формат:
```
🛒 В списке покупок ещё 5 незакрытых пунктов. /list
```

Множественное число "пункт/пункта/пунктов" — простой helper по русским правилам.

### `core/services/shopping_list.py` (modify)

Добавить `add_manual_item(session, *, family_id, name, quantity="", store=Store.other) -> ShoppingItem`. Используется и в `/add` хендлере, и в существующем tool'е `add_shopping_item`.

### `bot/handlers/shopping.py` (modify)

Добавить:
```python
@router.message(Command("add"))
async def cmd_add(message, family, db_session):
    text = (message.text or "").removeprefix("/add").strip()
    if not text:
        await message.answer("Использование: /add <название>\nПример: /add молоко")
        return
    await shopping_list.add_manual_item(db_session, family_id=family.id, name=text)
    await db_session.commit()
    await message.answer(f"Добавил: {text}")
```

### `core/tools.py` (modify)

`_tool_add_shopping_item` использует новый helper `shopping_list.add_manual_item` вместо ручного создания.

### `bot/main.py` (modify)

После `dp.start_polling(...)` (но запущенно параллельно):
```python
scheduler_tasks = await start_scheduler(bot, get_sessionmaker())
try:
    await dp.start_polling(bot)
finally:
    for t in scheduler_tasks:
        t.cancel()
```

---

## Тесты

| Файл | Что покрываем |
|---|---|
| `tests/unit/test_scheduler.py` | `seconds_until_next` с фиксированным "now": до полудня → утром, после полудня → завтра, ровно на минуту → завтра |
| `tests/unit/test_digest.py` | формат с двумя днями; формат когда только сегодня; `None` когда меню пустое |
| `tests/unit/test_reminders.py` | формат с N>0; `None` когда всё куплено; склонение 1/2/5 пунктов |
| `tests/integration/test_add_handler.py` (или в `test_shopping_list.py`) | `add_manual_item` создаёт пункт с правильными дефолтами; не тестируем сам handler, тестируем сервис |

Сам цикл `asyncio.Task` не тестируем — это runtime-обвязка.

---

## Out of scope (отдельные итерации)

- Конфигурируемое время дайджеста/напоминаний
- Per-user opt-out (`/reminders off`)
- Разворачивание полного списка покупок в напоминании
- Snooze / повторные напоминания в один день
- LLM-парсинг `/add 2л молока в виллу`
