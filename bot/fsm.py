from aiogram.fsm.state import State, StatesGroup


class PlanWizard(StatesGroup):
    ask_days = State()
    ask_start_date = State()
    ask_fridge = State()
    draft_review = State()
    ask_which_meal = State()
    ask_replace_hint = State()
