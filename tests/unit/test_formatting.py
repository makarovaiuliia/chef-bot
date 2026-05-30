from bot.formatting import md_to_telegram_html


def test_bold_double_asterisk():
    assert md_to_telegram_html("**Обед**") == "<b>Обед</b>"


def test_bold_label_inline():
    assert md_to_telegram_html("**Было:** котлеты") == "<b>Было:</b> котлеты"


def test_italic_single_asterisk():
    assert md_to_telegram_html("*курсив*") == "<i>курсив</i>"


def test_italic_underscore():
    assert md_to_telegram_html("_курсив_") == "<i>курсив</i>"


def test_dash_bullets_become_dots():
    src = "- Паприка — 1 ч.л.\n- Соль, перец — по вкусу"
    assert md_to_telegram_html(src) == "• Паприка — 1 ч.л.\n• Соль, перец — по вкусу"


def test_markdown_heading_becomes_bold():
    assert md_to_telegram_html("## Готовка") == "<b>Готовка</b>"


def test_horizontal_rule_dropped():
    assert md_to_telegram_html("текст\n---\nещё") == "текст\nещё"


def test_table_rendered_as_lines():
    src = (
        "| Приём | Блюдо |\n"
        "|-------|-------|\n"
        "| Обед | Стейк |\n"
        "| Ужин | Бёдра |"
    )
    assert md_to_telegram_html(src) == "Приём — Блюдо\nОбед — Стейк\nУжин — Бёдра"


def test_preserves_existing_telegram_html_tags():
    src = "<b>🍳 Рецепт</b>\n<i>2 порции</i>"
    assert md_to_telegram_html(src) == "<b>🍳 Рецепт</b>\n<i>2 порции</i>"


def test_escapes_stray_lt_gt_amp():
    src = "температура < 70°C & готово"
    assert md_to_telegram_html(src) == "температура &lt; 70°C &amp; готово"


def test_escapes_stray_lt_but_keeps_real_tags():
    src = "<b>Готовка</b> при t < 70"
    assert md_to_telegram_html(src) == "<b>Готовка</b> при t &lt; 70"


def test_inline_code_backticks():
    assert md_to_telegram_html("значение `airfryer` тут") == "значение <code>airfryer</code> тут"


def test_plain_text_unchanged():
    src = "Готово. Завтрашний обед обновлён."
    assert md_to_telegram_html(src) == "Готово. Завтрашний обед обновлён."


def test_bold_inside_bullet():
    src = "- **Обед** Говяжий стейк"
    assert md_to_telegram_html(src) == "• <b>Обед</b> Говяжий стейк"


def test_idempotent_on_converted_output():
    once = md_to_telegram_html("**Обед**")
    assert md_to_telegram_html(once) == once
