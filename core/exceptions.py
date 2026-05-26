class ChefBotError(Exception):
    """Base exception."""


class NotAuthorized(ChefBotError):
    """Telegram user is not in allowlist."""


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
