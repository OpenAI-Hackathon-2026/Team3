from typing import Literal

from pydantic import BaseModel, Field


class DonationItem(BaseModel):
    title: str
    description: str
    quantity: float = Field(gt=0)
    unit: Literal["meals", "boxes", "lb", "kg", "items", "trays"]
    category: Literal["meal", "ingredient"]
    readiness: Literal["ready_to_eat", "needs_cooking"]
    allergens: list[str] = Field(default_factory=list)
    storage: str | None = None
    pickup_start: str | None = None
    pickup_end: str | None = None
    confidence: float = Field(ge=0, le=1)
    needs_review: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    items: list[DonationItem]
    summary: str
    follow_up_questions: list[str] = Field(default_factory=list)


class RecipeIngredient(BaseModel):
    listing_id: str
    name: str
    quantity: float = Field(gt=0)
    unit: Literal["meals", "boxes", "lb", "kg", "items", "trays"]


class RecipePlan(BaseModel):
    title: str
    servings: int = Field(gt=0)
    instructions: list[str]
    ingredients: list[RecipeIngredient] = Field(min_length=1)
    listing_ids: list[str]
    pantry_items: list[str] = Field(default_factory=list)
    stops: int = Field(gt=0)
    estimated_route_miles: float = Field(ge=0)
    safety_notes: list[str] = Field(default_factory=list)


class RecipeResult(BaseModel):
    plans: list[RecipePlan]
    explanation: str
