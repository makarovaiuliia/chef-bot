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


class FamilyError(Exception):
    """Base for family-domain errors."""


class InvalidInviteCode(FamilyError):
    pass


class AlreadyInFamily(FamilyError):
    pass


class MemberNotInFamily(FamilyError):
    pass
