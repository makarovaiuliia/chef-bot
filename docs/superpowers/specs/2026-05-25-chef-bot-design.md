# Chef-Bot — Design Spec

**Дата:** 2026-05-25
**Статус:** draft (ожидает review пользователя)

---

## 1. Краткое описание

Персональный Telegram-бот для планирования меню для семьи из 2 человек, живущих на Пхукете, Таиланд. Использует Claude API (Sonnet 4.6) для генерации меню, рецептов и списков покупок с учётом ЗОЖ/ПП-предпочтений и доступных продуктов. Язык интерфейса — русский.

**Минимальная ценность (MVP):**
1. Сгенерировать сбалансированное меню на 7 или 14 дней
2. Получить рецепт конкретного блюда
3. Автоматический список покупок, сгруппированный по магазинам (Makro / Villa Market / Lotus's / 7-Eleven)
4. Свободный диалог на русском: "поменяй четверг на что-то с рыбой", "что у нас сегодня на ужин?", "добавь молоко в список покупок"

**Контекст пользователя** (передаётся в LLM как system prompt) — полностью описан в исходном бизнес-документе (семья, фитнес, ЗОЖ, непереносимость лука/чеснока, доступные продукты, кухонная техника, базовая кладовка, избранные блюда). При разработке вынесем его в `core/prompts/base_context.md`.

---

## 2. Принятые решения

| Параметр | Решение |
|---|---|
| Язык | Python 3.12+ |
| Telegram-фреймворк | aiogram 3 |
| LLM | Claude Sonnet 4.6 (`claude-sonnet-4-6`) везде |
| LLM SDK | официальный `anthropic` Python SDK |
| База данных | SQLite через SQLAlchemy 2.0 (async) + Alembic для миграций |
| Хостинг | Railway / Fly.io / Render (PaaS) с persistent volume для SQLite |
| Модель доступа | Shared family bot — 2 telegram_id в allowlist, общее состояние |
| Часовой пояс | Asia/Bangkok |
| Подключение к Telegram | long polling (без webhook'ов / публичного URL) |
| Архитектурный подход | Гибрид: slash-команды и кнопки идут напрямую в core; свободный текст — через tool-use агент |

---

## 3. Фичи

### 3.1 MVP (фазы 0–3)

**[#1] Планирование меню** — Пользователь запускает `/plan`, бот мастером уточняет дней (7/14) и что есть в холодильнике, генерирует меню (обед + ужин на каждый день). Меню можно утвердить или попросить заменить отдельные блюда. Утверждённое меню сохраняется как `status=active`.

**[#2] Рецепты по запросу** — `/recipe` выдаёт рецепт текущего приёма (по времени дня определяет обед/ужин). Можно запросить рецепт на конкретный день/приём через свободный текст. Можно искать рецепт по ингредиенту ("хочу что-то с креветками").

**[#4] Список покупок** — После утверждения меню бот генерирует список с группировкой по магазинам (Makro / Villa Market / Lotus's / 7-Eleven), исключает базовую кладовку, считает количество на 2 порции. `/list` показывает с inline-кнопками; нажатие на кнопку = "куплено".

**[#8] Свободный диалог** — Любой текст не-команда идёт в tool-use агента. Claude получает контекст активного меню, последние сообщения, и список tools — сам решает что вызвать.

### 3.2 Фаза 4+ (после MVP)

**[#3] Утренний дайджест** — Ежедневное уведомление в 8:00 Asia/Bangkok: что сегодня в меню, что разморозить к завтрашнему дню, какие ингредиенты должны быть в холодильнике.

**[#5] Напоминания о незакупленном** — Пока в списке есть незакрытые пункты, периодические напоминания (настраиваемая частота, можно отключить).

**[#6] Ручной чек-лист** — `/add закончилось молоко` добавляет пункт в общий список покупок (без привязки к меню). Объединяется с основным списком при просмотре.

**[#7] Оценки и favorites** — Вечером бот спрашивает 👍/👎 для сегодняшних блюд. Лайкнутые → таблица `favorites`, используются как контекст для будущих меню. Дизлайкнутые — список "не предлагать".

### 3.3 Фазы 5–6 (расширения)

Из брейншторма утверждены:
- **B1** — отметки выполнения приёмов (готовил / пропустил / заказал)
- **B3** — замены блюд день-в-день
- **C1** — оценки КБЖУ для каждого блюда
- **C2** — недельный recap по КБЖУ
- **E3** — интеграция с онлайн-заказом Makro/Lotus's (предварительный research-спайк — есть ли API; решение делать или нет на основе результата)
- **F2** — пропуск дней (отъезд/ресторан)
- **F3** — праздничные/особые приёмы

---

## 4. Архитектура

### 4.1 Слои

```
ENTRYPOINT (bot/main.py)
    │
    ▼
BOT LAYER (bot/)               — Telegram handlers, FSM, клавиатуры, middlewares.
    │                            Ничего не знает про БД и Claude.
    ▼
CORE LAYER (core/)             — Бизнес-логика, доменные модели, LLM-интеграция,
                                 БД. Ничего не знает про Telegram.
```

Зависимости только вниз: bot → core. Core самодостаточен (можно подменить bot/ на web/CLI без правок в core/).

### 4.2 Структура папок

```
chef-bot/
├── bot/                  # тонкий Telegram-слой
│   ├── main.py
│   ├── handlers/         # plan.py, recipes.py, shopping.py, freetext.py
│   ├── keyboards.py
│   ├── fsm.py
│   └── middlewares.py    # allowlist, family_resolver, logging
├── core/                 # бизнес-логика + инфра
│   ├── services/         # menu_planner.py, recipe_service.py,
│   │                     # shopping_list.py, dish_replacer.py, conversation.py,
│   │                     # family_service.py
│   ├── llm.py            # Claude клиент + загрузка промптов
│   ├── prompts/          # .md-файлы: base_context, menu_planner, recipe, conversation
│   ├── tools.py          # определения tools для LLM-агента
│   ├── db.py             # SQLAlchemy ORM модели + session factory
│   ├── repositories.py   # доступ к БД
│   ├── models.py         # Pydantic domain модели
│   └── exceptions.py
├── alembic/              # миграции
├── config.py             # pydantic-settings
├── tests/
│   ├── unit/
│   ├── integration/
│   └── llm/              # помечены маркером @pytest.mark.llm, не в CI по умолчанию
├── docs/
│   └── superpowers/specs/
├── pyproject.toml
├── Dockerfile
└── README.md
```

### 4.3 Сервисы core/

| Сервис | Ответственность |
|---|---|
| `family_service` | allowlist, привязка `telegram_user_id` → `family` |
| `menu_planner` | генерация и управление меню (мастер `/plan`, утверждение, активное меню) |
| `recipe_service` | рецепты по запросу (генерация + кэш в БД), определение "что сейчас готовить" по времени |
| `shopping_list` | сборка списка из меню, ручные пункты, отметки куплено |
| `dish_replacer` | точечная замена блюда без пересборки меню |
| `conversation` | tool-use агент для свободного текста |

### 4.4 Архитектурный паттерн "гибрид"

```
Slash-команды/кнопки → bot handler → core service (без LLM или с прямым LLM-вызовом)
Свободный текст      → bot handler → conversation.handle_message() → LLM с tools → tools зовут те же core services
```

Один и тот же core-сервис вызывается из двух мест (handler и tool). Это даёт согласованность без дублирования логики.

---

## 5. Схема данных (MVP)

```sql
families
├── id              PK
├── created_at
└── name?

family_members
├── id              PK
├── family_id       FK → families
├── telegram_user_id  UNIQUE
├── display_name
└── created_at

menus
├── id              PK
├── family_id       FK → families
├── start_date      DATE
├── days_count      INT             -- 7 или 14
├── status          ENUM(draft, active, archived)
├── created_at
└── approved_at?

meals
├── id              PK
├── menu_id         FK → menus
├── date            DATE
├── slot            ENUM(lunch, dinner)
├── dish_name       TEXT
├── side_dishes     TEXT (json)
├── protein_kind    ENUM(chicken, fish, seafood, beef, pork, vegetarian, mixed)
└── UNIQUE(menu_id, date, slot)

recipes
├── id              PK
├── meal_id         FK → meals  UNIQUE
├── content_md      TEXT
├── ingredients     TEXT (json)
├── prep_minutes    INT
└── generated_at

shopping_lists
├── id              PK
├── menu_id         FK → menus
└── created_at

shopping_items
├── id              PK
├── shopping_list_id?  FK → shopping_lists   -- NULL = ручной чек-лист
├── family_id       FK → families
├── name            TEXT
├── quantity        TEXT
├── store           ENUM(makro, villa, lotus, seven_eleven, other)
├── bought          BOOLEAN  DEFAULT FALSE
├── bought_at?
└── created_at

claude_conversations
├── id              PK
├── family_id       FK → families
├── telegram_user_id
├── role            ENUM(user, assistant, tool)
├── content         TEXT
├── tokens_in?      INT
├── tokens_out?     INT
└── created_at
```

**В фазе 2+ добавляются миграциями:** `dish_ratings`, `favorites`, `skipped_days`, доп. поля в `meals` (cook_status, kcal/protein/fat/carbs, is_special, replaced_from).

---

## 6. LLM-интеграция

### 6.1 Клиент

`core/llm.py` — тонкая обёртка над `anthropic.AsyncAnthropic`:
- Конструктор читает `ANTHROPIC_API_KEY` из env
- Метод `chat(system, messages, tools=None)` — основной интерфейс
- Retry с экспоненциальной задержкой при 429/529/transient (SDK делает сам, мы только настраиваем параметры)
- Логирование токенов в `claude_conversations`
- Возвращает `LLMResponse(text, tool_calls, stop_reason, tokens_in, tokens_out)`

### 6.2 Промпт-кэширование

Anthropic prompt cache даёт скидку ~90% на закэшированный input. Структура:

```
system: [
  { "type": "text", "text": base_context.md,           "cache_control": {"type": "ephemeral"} },
  { "type": "text", "text": <task-specific prompt>,    "cache_control": {"type": "ephemeral"} }
],
messages: [
  { "role": "user", "content": <конкретный запрос> }
]
```

`base_context.md` — большой статичный текст (~3-4K токенов: семья, образ жизни, правила, продукты, техника, кладовка, избранные блюда). Кэшируется на TTL 5 минут — при активном использовании последующие запросы дешёвые.

### 6.3 Tool use для свободного диалога

Tools (MVP):
- `get_active_menu()` — текущее меню
- `get_meal(date, slot)` — блюдо на конкретный день/приём
- `get_recipe(meal_id)` — рецепт
- `replace_meal(meal_id, hint)` — заменить блюдо в меню
- `add_shopping_item(name, quantity?, store?)` — добавить в чек-лист
- `mark_shopping_item_bought(item_id)` — отметить купленным

Loop (упрощённо):

```python
messages = [user_msg]
for _ in range(MAX_ITERATIONS):  # например, 5
    resp = await llm.chat(system=..., messages=messages, tools=TOOLS)
    if resp.stop_reason == "end_turn":
        return resp.text
    for tc in resp.tool_calls:
        result = await execute_tool(tc.name, tc.input)
        messages.append({"role": "assistant", "content": resp.raw})
        messages.append({"role": "user",
                         "content": [{"type": "tool_result", "tool_use_id": tc.id, "content": result}]})
```

Защита: max 5 итераций, таймаут 60 сек, graceful fallback.

### 6.4 Структурированный вывод

Для генерации меню/рецептов/списка покупок Claude возвращает JSON по схеме. Парсим через Pydantic. На ошибке парсинга — 1 retry с подсказкой.

Пример JSON-схемы для меню:
```json
{
  "meals": [
    {"date": "2026-05-26", "slot": "lunch", "dish_name": "...",
     "side_dishes": ["..."], "protein_kind": "chicken"},
    ...
  ]
}
```

---

## 7. Bot Layer (Telegram)

### 7.1 Команды (MVP)

| Команда | Что делает |
|---|---|
| `/start` | приветствие, проверка allowlist, создание family_member |
| `/plan` | мастер планирования меню (FSM) |
| `/menu` | показывает активное меню |
| `/today` | сегодняшние обед+ужин |
| `/recipe` | рецепт текущего приёма по времени дня |
| `/list` | список покупок с inline-кнопками |
| `/help` | список команд |

Свободный текст → `conversation.handle_message()`.

### 7.2 FSM мастера `/plan`

```
[start] /plan
  ↓
[ask_days]          Bot: "На сколько дней? 7 или 14?" + inline-кнопки
  ↓
[ask_fridge]        Bot: "Что уже есть в холодильнике? (или 'ничего')"
  ↓
[generating]        Bot: "Генерирую меню..." (LLM, 10-20 сек)
  ↓
[draft_review]      Bot: показывает черновик + [Утвердить / Заменить блюдо / Отмена]
  ├── Утвердить    → status=active, выход
  ├── Заменить     → [ask_which_meal] → [ask_replace_hint] → LLM → [draft_review]
  └── Отмена       → выход
```

### 7.3 Inline-клавиатуры

- **Список покупок:** каждый незакрытый пункт — кнопка `[☐ Куриные бёдра 500г]`. Нажатие = `mark_bought` → правка сообщения, кнопка → `[✓ Куриные бёдра 500г]`
- **Меню:** навигация `[<] [День 2] [>]`, на каждом блюде — `[📖 Рецепт]`
- **`/plan`:** кнопки 7/14, "Утвердить/Заменить/Отмена"

### 7.4 Middlewares

1. **AllowlistMiddleware** — отсекает `update.from_user.id` не из allowlist
2. **FamilyResolverMiddleware** — кладёт `family` в `data`
3. **LoggingMiddleware** — структурное логирование

### 7.5 Конфиг

```python
class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    allowlist_telegram_ids: list[int]
    db_url: str = "sqlite+aiosqlite:///./data/chef.db"
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"
    claude_model: str = "claude-sonnet-4-6"
```

---

## 8. Фазы реализации

| Фаза | Содержание | Время |
|---|---|---|
| **Фаза 0** — Скелет | Структура папок, aiogram + `/start`, AllowlistMiddleware, SQLAlchemy + первая миграция, ruff + pytest, деплой | 1-2 дня |
| **Фаза 1** — MVP: меню + рецепт | `base_context.md`, `llm.py`, таблицы menu/meals/recipes, `menu_planner.start_planning()`, FSM `/plan`, `/menu`, `/today`, `/recipe` | 3-5 дней |
| **Фаза 2** — MVP: список покупок | Таблицы shopping_*, `shopping_list.build_from_menu()`, `/list` с inline-кнопками | 1-2 дня |
| **Фаза 3** — MVP: свободный диалог | Таблица claude_conversations, `core/tools.py`, `conversation.handle_message()` (tool-use loop), хендлер свободного текста, `conversation.md` промпт | 2-4 дня |
| **🎯 Конец MVP** | | ~10-15 дней |
| **Фаза 4** — Уведомления и ручной чек-лист | APScheduler 4, утренний дайджест (#3), напоминания о незакупленном (#5), ручной чек-лист `/add` (#6) | 2-3 дня |
| **Фаза 5** — Оценки + favorites | Миграция dish_ratings/favorites, вечернее сообщение с 👍/👎, контекст favorites в LLM | 2 дня |
| **Фаза 6** — Расширения | B1, B3, C1, C2, F2, F3, E1, E3-спайк | итеративно |

---

## 9. Тестирование и обработка ошибок

### 9.1 Тесты

| Уровень | Покрытие | Когда |
|---|---|---|
| Unit | Парсеры, форматтеры, чистые функции | в CI |
| Integration | Сервисы + БД (in-memory SQLite) | в CI |
| LLM-смоук | Реальный Claude API, 1-2 теста на сервис | вручную / по флагу `@pytest.mark.llm` |
| Бот e2e | Критичные пути через `aiogram.test_utils` | опционально |

**Мокаем:** Anthropic клиент в unit-тестах. **Не мокаем:** БД (используем реальный SQLite).

Для сложных сервисов (`menu_planner`, `dish_replacer`) — TDD-подход: сначала тест с замокаными ответами, потом имплементация.

### 9.2 Обработка ошибок

| Ошибка | Реакция |
|---|---|
| LLM таймаут | "Думаю слишком долго, попробуй ещё раз", retry (1) |
| LLM 429/529 | Backoff (SDK), на финальную неудачу — сообщение пользователю |
| LLM невалидный JSON | 1 retry с подсказкой, fallback с человеческим сообщением |
| LLM tool с невалидными аргументами | Возвращаем Claude `tool_result` с ошибкой, он переформулирует |
| БД недоступна | Лог + сообщение пользователю |
| Telegram API недоступен | aiogram retry автоматически |
| Не в allowlist | Игнорируем (или вежливый отказ на `/start`) |
| Uncaught exception | Глобальный error handler aiogram: лог + "что-то пошло не так" |

### 9.3 Логирование и бэкапы

- **Логи:** loguru, structured (JSON в проде). На каждый LLM-вызов — токены и латенция. На каждое сообщение — telegram_id, тип update, время обработки.
- **Бэкапы:** cron job → `sqlite3 chef.db .dump | gzip` → S3-совместимое хранилище. Раз в день. Не блокирует MVP, добавится при деплое.

---

## 10. Открытые вопросы

- **E3 (Makro/Lotus's API):** не известно, есть ли публичный API или удобный deep-link. Перед фазой 6 — research-спайк. Если API нет — оставим как форматированный экспорт списка.
- **Бэкап БД:** конкретное хранилище (Backblaze B2 / S3 / Cloudflare R2) выберем при деплое.
- **Подбор картинок к блюдам / фото готовых блюд:** не в скоупе MVP, может быть рассмотрено позже.

---

## 11. Что вне скоупа

- Веб-интерфейс (только Telegram)
- Мультисемейный режим (если когда-то понадобится — отдельная фаза с миграцией модели)
- Интеграция с фитнес-трекерами / Apple Health
- Голосовой ввод
- OCR чеков (рассмотрено в брейншторме как E2, не выбрано)
- Учёт бюджета на продукты
