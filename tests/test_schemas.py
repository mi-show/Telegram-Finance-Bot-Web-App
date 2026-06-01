"""Tests for schemas module."""
import pytest
from datetime import date
from decimal import Decimal
from pydantic import ValidationError
from app.schemas import RecordCreate, RecordFilter, BudgetPlanCreate


def test_record_create_valid():
    """Test creating valid RecordCreate."""
    record = RecordCreate(
        type="expense",
        category="Food",
        amount=Decimal("10.50"),
        happened_on=date(2024, 1, 15),
    )
    assert record.type == "expense"
    assert record.category == "Food"
    assert record.amount == Decimal("10.50")


def test_record_create_invalid_type():
    """Test RecordCreate with invalid type."""
    with pytest.raises(ValidationError):
        RecordCreate(
            type="invalid",
            category="Food",
            amount=Decimal("10.50"),
            happened_on=date(2024, 1, 15),
        )


def test_record_create_negative_amount():
    """Test RecordCreate rejects negative amounts."""
    with pytest.raises(ValidationError):
        RecordCreate(
            type="expense",
            category="Food",
            amount=Decimal("-10.50"),
            happened_on=date(2024, 1, 15),
        )


def test_record_filter_empty():
    """Test creating empty RecordFilter."""
    f = RecordFilter()
    assert f.date_from is None
    assert f.date_to is None
    assert f.type is None


def test_record_filter_with_dates():
    """Test RecordFilter with date range."""
    f = RecordFilter(
        date_from=date(2024, 1, 1),
        date_to=date(2024, 1, 31),
    )
    assert f.date_from == date(2024, 1, 1)
    assert f.date_to == date(2024, 1, 31)


def test_budget_plan_create_valid():
    """Test creating valid BudgetPlanCreate."""
    plan = BudgetPlanCreate(
        planned_expense=Decimal("1000.00"),
        planned_income=Decimal("2000.00"),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    assert plan.planned_expense == Decimal("1000.00")
    assert plan.planned_income == Decimal("2000.00")
