from bot.keyboards import kb_household, kb_multiselect, kb_profile_confirm

SLOT_OPTIONS = {"breakfast": "Завтрак", "lunch": "Обед", "dinner": "Ужин"}


def test_multiselect_marks_selected():
    kb = kb_multiselect("onb:slot", SLOT_OPTIONS, selected={"lunch"})
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Обед" in t and "✅" in t for t in texts)
    assert any("Завтрак" in t and "✅" not in t for t in texts)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "onb:slot:lunch" in datas
    assert "onb:slot:done" in datas


def test_household_and_confirm_keyboards():
    kb = kb_household()
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "onb:hh:2" in datas
    kb2 = kb_profile_confirm()
    datas2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert "onb:profile:ok" in datas2 and "onb:profile:edit" in datas2
