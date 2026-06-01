from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


class RecordCreate(BaseModel):
    type: Literal["income", "expense"]
    category: str = Field(min_length=2, max_length=64)
    subcategory: Optional[str] = Field(default=None, max_length=64)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="UAH", max_length=8)
    happened_on: date
    description: Optional[str] = Field(default=None, max_length=255)

    @field_validator("category", mode="before")
    @classmethod
    def strip_category(cls, value: str) -> str:
        return value.strip()

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class RecordFilter(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    categories: Optional[list[str]] = None
    type: Optional[Literal["income", "expense"]] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    description_query: Optional[str] = None

    @field_validator("categories", mode="before")
    @classmethod
    def normalize_categories(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value:
            return [v.strip() for v in value]
        return value

    @field_validator("description_query", mode="before")
    @classmethod
    def normalize_query(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class BudgetPlanCreate(BaseModel):
    period_start: date
    period_end: date
    planned_expense: Decimal = Field(ge=0)
    planned_income: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class BudgetPlanOut(BudgetPlanCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class AggregatedAmount(BaseModel):
    label: str
    amount: Decimal
