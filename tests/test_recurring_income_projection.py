from datetime import date
from decimal import Decimal

from app.models import RecordType, RecurringEntry
from app.web.core.budget import _recurring_income_expected_for_period


def _recurring_income(amount: str) -> RecurringEntry:
    return RecurringEntry(
        user_id=1,
        title="Salary",
        type=RecordType.INCOME,
        category="Salary",
        subcategory="Main",
        amount=Decimal(amount),
        currency="UAH",
        day_of_month=20,
        reminder_days_before=2,
        is_active=True,
    )


def test_recurring_income_expected_uses_fixed_month_amount_for_month_period():
    rows = [_recurring_income("27000.00")]
    expected = _recurring_income_expected_for_period(
        rows,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 12),
        period="month",
    )
    assert expected == Decimal("27000.00")


def test_recurring_income_expected_uses_quarter_of_month_for_week_period():
    rows = [_recurring_income("27000.00")]
    expected = _recurring_income_expected_for_period(
        rows,
        period_start=date(2026, 5, 11),
        period_end=date(2026, 5, 12),
        period="week",
    )
    assert expected == Decimal("6750.00")


def test_recurring_income_expected_uses_twelve_months_for_year_period():
    rows = [_recurring_income("27000.00")]
    expected = _recurring_income_expected_for_period(
        rows,
        period_start=date(2025, 5, 13),
        period_end=date(2026, 5, 12),
        period="year",
    )
    assert expected == Decimal("324000.00")


def test_recurring_income_expected_keeps_overlap_accrual_for_custom_ranges():
    rows = [_recurring_income("27000.00")]
    expected = _recurring_income_expected_for_period(
        rows,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 12),
    )
    assert expected == Decimal("10451.61")

