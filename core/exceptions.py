class ChefBotError(Exception):
    """Base exception."""


class FamilyNotFound(ChefBotError):
    pass


class MenuNotFound(ChefBotError):
    pass


class MealNotFound(ChefBotError):
    pass


class LLMError(ChefBotError):
    """Generic LLM failure (timeout, invalid JSON, etc)."""


class LLMInvalidResponse(LLMError):
    pass


class MenuTooLong(ChefBotError):
    """Запрошенная длительность меню превышает MENU_MAX_DAYS."""


class FamilyError(Exception):
    """Base for family-domain errors."""


class InvalidInviteCode(FamilyError):
    pass


class AlreadyInFamily(FamilyError):
    pass


class MemberNotInFamily(FamilyError):
    pass


class LimitExceeded(ChefBotError):
    """База: лимит триала или месячный токен-потолок исчерпан."""


class TrialLimitExceeded(LimitExceeded):
    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(operation)


class MonthlyCapExceeded(LimitExceeded):
    def __init__(self, subscribed: bool = False) -> None:
        self.subscribed = subscribed
        super().__init__()
