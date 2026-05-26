from datetime import date as DateType
from datetime import datetime

from pydantic import BaseModel, Field

from core.db import MealSlot, MenuStatus, ProteinKind


class MealDTO(BaseModel):
    date: DateType
    slot: MealSlot
    dish_name: str
    side_dishes: list[str] = Field(default_factory=list)
    protein_kind: ProteinKind


class MenuDTO(BaseModel):
    id: int | None = None
    family_id: int
    start_date: DateType
    days_count: int
    status: MenuStatus = MenuStatus.draft
    meals: list[MealDTO] = Field(default_factory=list)
    created_at: datetime | None = None
    approved_at: datetime | None = None


class IngredientDTO(BaseModel):
    name: str
    quantity: str
    unit: str | None = None
    store: str | None = None


class RecipeDTO(BaseModel):
    meal_id: int | None = None
    content_md: str
    ingredients: list[IngredientDTO] = Field(default_factory=list)
    prep_minutes: int


class LLMMenuResponse(BaseModel):
    """Schema we ask Claude to follow when generating a menu."""

    meals: list[MealDTO]


class LLMRecipeResponse(BaseModel):
    content_md: str
    ingredients: list[IngredientDTO]
    prep_minutes: int


class ShoppingItemDTO(BaseModel):
    name: str
    quantity: str = ""
    store: str = "other"


class LLMShoppingResponse(BaseModel):
    items: list[ShoppingItemDTO]
