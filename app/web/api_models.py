from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RecordUpdateIn(BaseModel):
    type: str | None = Field(default=None)
    category: str | None = Field(default=None, min_length=2, max_length=64)
    subcategory: str | None = Field(default=None, max_length=64)
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=8)
    happened_on: date | None = None
    description: str | None = Field(default=None, max_length=255)


class MonthBudgetIn(BaseModel):
    planned_expense: Decimal = Field(ge=0)
    planned_income: Decimal = Field(ge=0)
    period_start: date
    period_end: date


class CategoryLimitIn(BaseModel):
    category: str = Field(min_length=2, max_length=64)
    subcategory: str | None = Field(default=None, max_length=64)
    limit_amount: Decimal = Field(ge=0)


class CategoryLimitBatchIn(BaseModel):
    period_start: date
    period_end: date
    limits: list[CategoryLimitIn]
    # allows values like "always" or "threshold_70" or "threshold_65" (custom)
    limit_alert_mode: str | None = Field(default=None, pattern=r"^(always|threshold_\d{1,3})$")


class LimitSeriesKeyIn(BaseModel):
    category: str = Field(min_length=2, max_length=64)
    subcategory: str | None = Field(default=None, max_length=64)


class LimitSeriesIn(BaseModel):
    period_start: date
    period_end: date
    keys: list[LimitSeriesKeyIn]


class SettingsUpdateIn(BaseModel):
    theme: Literal["dark", "light"] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8, pattern=r"^[A-Za-z]{3,8}$")
    interface_language: str | None = Field(default=None, min_length=2, max_length=8, pattern=r"^[A-Za-z-]{2,8}$")
    week_starts_on: Literal["monday", "sunday"] | None = None
    notifications_enabled: bool | None = None
    # allows values like "always" or "threshold_70" or "threshold_65" (custom)
    limit_alert_mode: str | None = Field(default=None, pattern=r"^(always|threshold_\d{1,3})$")
    hidden_blocks: list[str] | None = None
    pinned_filters: list[str] | None = None
    favorite_categories: list[str] | None = None
    desktop_window_width: int | None = Field(default=None, ge=320, le=2200)
    desktop_window_height: int | None = Field(default=None, ge=320, le=1600)
    desktop_fullscreen_enabled: bool | None = None
    budget_warning_percent: int | None = Field(default=None, ge=50, le=100)
    budget_danger_percent: int | None = Field(default=None, ge=60, le=150)

    @model_validator(mode="after")
    def validate_budget_thresholds(self):
        if self.budget_warning_percent is not None and self.budget_danger_percent is not None:
            if self.budget_warning_percent >= self.budget_danger_percent:
                raise ValueError("budget_warning_percent must be < budget_danger_percent")
        return self


class RecurringCreateIn(BaseModel):
    title: str = Field(min_length=2, max_length=128)
    type: Literal["income", "expense"]
    category: str | None = Field(default=None, min_length=2, max_length=64)
    subcategory: str | None = Field(default=None, max_length=64)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="UAH", min_length=3, max_length=8, pattern=r"^[A-Za-z]{3,8}$")
    day_of_month: int = Field(ge=1, le=31)
    reminder_days_before: int = Field(default=2, ge=0, le=15)
    is_active: bool = True


class RecurringUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=128)
    type: Literal["income", "expense"] | None = None
    category: str | None = Field(default=None, min_length=2, max_length=64)
    subcategory: str | None = Field(default=None, max_length=64)
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8, pattern=r"^[A-Za-z]{3,8}$")
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    reminder_days_before: int | None = Field(default=None, ge=0, le=15)
    is_active: bool | None = None


__all__ = (
    "RecordUpdateIn",
    "MonthBudgetIn",
    "CategoryLimitIn",
    "CategoryLimitBatchIn",
    "LimitSeriesKeyIn",
    "LimitSeriesIn",
    "SettingsUpdateIn",
    "RecurringCreateIn",
    "RecurringUpdateIn",
)
