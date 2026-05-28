from aiogram.fsm.state import State, StatesGroup


class LoadConfirm(StatesGroup):
    awaiting = State()
