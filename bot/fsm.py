from aiogram.fsm.state import State, StatesGroup


class LoadConfirm(StatesGroup):
    awaiting = State()


class ProfileEdit(StatesGroup):
    waiting_text = State()


class Onboarding(StatesGroup):
    household = State()
    slots = State()
    restrictions = State()
    cook_minutes = State()
    preferences = State()
    extra = State()
    city = State()
    confirm = State()
    edit_profile = State()


class PlanFlow(StatesGroup):
    start_date = State()
    custom_date = State()
    duration = State()
    draft = State()
    replace_pick = State()
    replace_alts = State()
    replace_hint = State()
    approve_confirm = State()
