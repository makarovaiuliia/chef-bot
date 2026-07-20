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
