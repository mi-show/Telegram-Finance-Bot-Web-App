from datetime import date, timedelta

from app.web.core.budget import _date_bounds


def test_date_bounds_week_uses_current_calendar_week():
    today = date.today()
    start, end = _date_bounds("week", None, None)

    assert start == today - timedelta(days=today.weekday())
    assert end == today


def test_date_bounds_month_uses_current_calendar_month():
    today = date.today()
    start, end = _date_bounds("month", None, None)

    assert start == today.replace(day=1)
    assert end == today


def test_date_bounds_aliases_match_calendar_week_and_month():
    today = date.today()

    week_start, week_end = _date_bounds("7d", None, None)
    month_start, month_end = _date_bounds("30d", None, None)

    assert week_start == today - timedelta(days=today.weekday())
    assert week_end == today
    assert month_start == today.replace(day=1)
    assert month_end == today
