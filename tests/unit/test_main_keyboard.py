from bot.keyboards import (
    BTN_ADD,
    BTN_LIST,
    BTN_PLAN,
    BTN_TODAY,
    MAIN_BUTTONS,
    kb_main,
)


def test_kb_main_layout():
    kb = kb_main()
    assert kb.resize_keyboard is True
    assert kb.is_persistent is True
    assert len(kb.keyboard) == 2  # два ряда
    assert [b.text for b in kb.keyboard[0]] == [BTN_ADD, BTN_TODAY, BTN_LIST]
    # второй ряд — одна кнопка, Telegram растянет ее на всю ширину
    assert [b.text for b in kb.keyboard[1]] == [BTN_PLAN]


def test_keyboard_buttons_are_in_main_buttons_set():
    """MAIN_BUTTONS — то, что исключают FSM-хэндлеры свободного ввода:
    любая кнопка клавиатуры обязана в нем быть."""
    for row in kb_main().keyboard:
        for button in row:
            assert button.text in MAIN_BUTTONS


def test_button_texts_are_not_commands():
    for text in MAIN_BUTTONS:
        assert not text.startswith("/")
