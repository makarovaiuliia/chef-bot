from aiogram.fsm.state import State, StatesGroup


class LoadConfirm(StatesGroup):
    awaiting = State()


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
