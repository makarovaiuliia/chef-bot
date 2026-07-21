from bot.keyboards import kb_plan_draft, kb_plan_duration, kb_plan_start, kb_retry


def _datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_plan_start_buttons():
    datas = _datas(kb_plan_start())
    assert datas == [
        "plan:date:today",
        "plan:date:tomorrow",
        "plan:date:monday",
        "plan:date:custom",
    ]


def test_plan_duration_buttons():
    assert _datas(kb_plan_duration()) == ["plan:days:3", "plan:days:5", "plan:days:7"]


def test_plan_draft_actions():
    datas = _datas(kb_plan_draft())
    assert datas == ["plan:replace", "plan:regen", "plan:approve"]


def test_retry_keyboard():
    assert _datas(kb_retry("plan:regen")) == ["plan:regen"]
