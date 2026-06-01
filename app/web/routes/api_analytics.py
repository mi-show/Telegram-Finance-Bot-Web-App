from __future__ import annotations

from statistics import pstdev

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    AggregationService,
    Decimal,
    Record,
    RecordFilter,
    RecordType,
    RecurringEntry,
    User,
    _auto_apply_recurring_for_current_month,
    _budget_snapshot,
    _date_bounds,
    _localize_category_amounts,
    _month_shift,
    _pct_change,
    _prev_bounds,
    _recurring_income_expected_for_period,
    _recurring_income_spikes_in_actual_records,
    _recommendations,
    _safe_lang,
    _to_float,
    canonicalize_category,
    canonicalize_subcategory,
    date,
    defaultdict,
    func,
    localize_category,
    localize_subcategory,
    select,
    timedelta,
)

router = APIRouter()


@router.get("/api/webapp/analytics")
async def webapp_analytics(
    period: str = Query(default="month"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)
    prev_start, prev_end = _prev_bounds(start, end)
    period_for_recurring = None if (date_from and date_to) else period

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    recurring_income_rows_query = await session.execute(
        select(RecurringEntry).where(
            RecurringEntry.user_id == user.id,
            RecurringEntry.type == RecordType.INCOME,
            RecurringEntry.is_active.is_(True),
        )
    )
    recurring_income_rows = recurring_income_rows_query.scalars().all()

    def apply_recurring_income_delta(
        totals: dict[str, Decimal],
        *,
        period_start: date,
        period_end: date,
        period_name: str | None = None,
    ) -> None:
        if not recurring_income_rows:
            return
        expected = _recurring_income_expected_for_period(
            recurring_income_rows,
            period_start=period_start,
            period_end=period_end,
            period=period_name,
        )
        spikes = _recurring_income_spikes_in_actual_records(
            recurring_income_rows,
            period_start=period_start,
            period_end=period_end,
        )
        delta = (expected - spikes).quantize(Decimal("0.01"))
        if not delta:
            return
        totals["incomes"] = Decimal(totals["incomes"]) + delta
        totals["balance"] = Decimal(totals["balance"]) + delta

    agg = AggregationService(session, auth_user.telegram_id)

    selected_filter = RecordFilter(date_from=start, date_to=end)
    selected_totals = await agg.totals(selected_filter)
    previous_totals = await agg.totals(RecordFilter(date_from=prev_start, date_to=prev_end))

    apply_recurring_income_delta(
        selected_totals,
        period_start=start,
        period_end=end,
        period_name=period_for_recurring,
    )
    apply_recurring_income_delta(
        previous_totals,
        period_start=prev_start,
        period_end=prev_end,
        period_name=period_for_recurring,
    )

    # Anchor day/week/month cards to the selected period end (not always "today").
    anchor_day = end
    week_start = anchor_day - timedelta(days=anchor_day.weekday())
    if week_start < start:
        week_start = start
    month_start = anchor_day.replace(day=1)
    if month_start < start:
        month_start = start

    day_totals = await agg.totals(RecordFilter(date_from=anchor_day, date_to=anchor_day))
    week_totals = await agg.totals(RecordFilter(date_from=week_start, date_to=anchor_day))
    month_totals = await agg.totals(RecordFilter(date_from=month_start, date_to=anchor_day))

    apply_recurring_income_delta(day_totals, period_start=anchor_day, period_end=anchor_day)
    apply_recurring_income_delta(week_totals, period_start=week_start, period_end=anchor_day, period_name="week")
    apply_recurring_income_delta(month_totals, period_start=month_start, period_end=anchor_day, period_name="month")

    week_size_days = (anchor_day - week_start).days + 1
    week_prev_end = week_start - timedelta(days=1)
    week_prev_start = week_prev_end - timedelta(days=week_size_days - 1)
    prev_week_totals = await agg.totals(RecordFilter(date_from=week_prev_start, date_to=week_prev_end))

    recent_start = max(start, anchor_day - timedelta(days=29))
    daily_points = await agg.sum_by_period("day", RecordFilter(date_from=recent_start, date_to=anchor_day))
    daily_map = {point.label: Decimal(point.amount) for point in daily_points}
    daily_values: list[Decimal] = []
    cursor = recent_start
    while cursor <= anchor_day:
        label = cursor.isoformat()
        daily_values.append(Decimal(daily_map.get(label, Decimal("0"))))
        cursor += timedelta(days=1)

    if daily_values:
        mean_daily = sum(daily_values) / Decimal(len(daily_values))
        stdev_daily = Decimal(str(pstdev([float(value) for value in daily_values]))) if len(daily_values) > 1 else Decimal("0")
        volatility_index = float((stdev_daily / mean_daily) if mean_daily > 0 else Decimal("0"))
    else:
        mean_daily = Decimal("0")
        stdev_daily = Decimal("0")
        volatility_index = 0.0

    avg_expense = await agg.averages(selected_filter)
    max_expense = await agg.max_expense(selected_filter)
    by_category = await agg.sum_by_category(selected_filter)

    localized_categories = _localize_category_amounts(
        [(row.label, row.amount) for row in by_category],
        language=lang,
    )

    total_expense = sum((amount for _, amount in localized_categories), Decimal("0"))
    distribution = []
    for label, amount in localized_categories:
        percent = float((amount / total_expense * 100) if total_expense else 0)
        distribution.append(
            {
                "category": label,
                "amount": _to_float(amount),
                "percent": round(percent, 2),
            }
        )

    subcategory_stmt = (
        select(
            Record.category,
            Record.subcategory,
            func.coalesce(func.sum(Record.amount), 0).label("total"),
        )
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == auth_user.telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= start,
            Record.happened_on <= end,
        )
        .group_by(Record.category, Record.subcategory)
    )
    subcategory_rows = await session.execute(subcategory_stmt)

    grouped_subcategories: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for category, subcategory, amount in subcategory_rows.all():
        canonical = canonicalize_category(category) or category
        normalized_subcategory = (subcategory or "").strip() or None
        if normalized_subcategory:
            canonical_subcategory = canonicalize_subcategory(canonical, normalized_subcategory) or normalized_subcategory
        else:
            canonical_subcategory = "-"
        grouped_subcategories[canonical][canonical_subcategory] += Decimal(amount or 0)

    subcategory_distribution = []
    for canonical in sorted(grouped_subcategories.keys(), key=lambda value: localize_category(value, lang) or value):
        category_label = localize_category(canonical, lang) or canonical
        values = grouped_subcategories[canonical]
        total_sub = sum(values.values(), Decimal("0"))

        subcategories = []
        for canonical_subcategory, amount in sorted(values.items(), key=lambda item: item[1], reverse=True):
            if canonical_subcategory == "-":
                sub_label = "-"
            else:
                sub_label = localize_subcategory(canonical, canonical_subcategory, lang) or canonical_subcategory
            percent = float((amount / total_sub * 100) if total_sub else 0)
            subcategories.append(
                {
                    "subcategory": sub_label,
                    "amount": _to_float(amount),
                    "percent": round(percent, 2),
                }
            )

        subcategory_distribution.append(
            {
                "category": category_label,
                "subcategories": subcategories,
            }
        )

    current_month_start = end.replace(day=1)
    monthly_points = []
    for offset in range(-5, 1):
        point_start = _month_shift(current_month_start, offset)
        point_end = _month_shift(point_start, 1) - timedelta(days=1)
        point_totals = await agg.totals(RecordFilter(date_from=point_start, date_to=point_end))

        apply_recurring_income_delta(point_totals, period_start=point_start, period_end=point_end, period_name="month")
        monthly_points.append(
            {
                "month": point_start.strftime("%Y-%m"),
                "expenses": _to_float(Decimal(point_totals["expenses"])),
                "incomes": _to_float(Decimal(point_totals["incomes"])),
                "balance": _to_float(Decimal(point_totals["balance"])),
            }
        )

    last_three = [Decimal(point["expenses"]) for point in monthly_points[-3:]]
    if last_three:
        forecast_next_month = round(float(sum(last_three) / Decimal(len(last_three))), 2)
    else:
        forecast_next_month = 0.0

    budget_period_start = start
    budget_period_end = end
    if period.lower() in {"month", "30d"}:
        month_end = _month_shift(start, 1) - timedelta(days=1)
        if not date_from and not date_to:
            # Show full monthly budget plan in analytics when the user selects the
            # month preset, even though the analytics cards use month-to-date values.
            budget_period_end = month_end
        elif date_from == start and date_to == end:
            # Preserve month preset semantics when the active custom range is
            # exactly current month-to-date.
            budget_period_end = month_end

    budget = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start=budget_period_start,
        period_end=budget_period_end,
        language=lang,
    )

    month_budget = budget.get("monthly_plan")
    tips = _recommendations(
        distribution,
        Decimal(selected_totals["balance"]),
        month_budget if isinstance(month_budget, dict) else None,
        language=lang,
    )

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "totals": {
            "selected": {
                "expenses": _to_float(Decimal(selected_totals["expenses"])),
                "incomes": _to_float(Decimal(selected_totals["incomes"])),
                "balance": _to_float(Decimal(selected_totals["balance"])),
            },
            "day": {
                "expenses": _to_float(Decimal(day_totals["expenses"])),
                "incomes": _to_float(Decimal(day_totals["incomes"])),
            },
            "week": {
                "expenses": _to_float(Decimal(week_totals["expenses"])),
                "incomes": _to_float(Decimal(week_totals["incomes"])),
            },
            "month": {
                "expenses": _to_float(Decimal(month_totals["expenses"])),
                "incomes": _to_float(Decimal(month_totals["incomes"])),
            },
        },
        "week_over_week": {
            "expenses_pct": _pct_change(Decimal(week_totals["expenses"]), Decimal(prev_week_totals["expenses"])),
            "current": _to_float(Decimal(week_totals["expenses"])),
            "previous": _to_float(Decimal(prev_week_totals["expenses"])),
        },
        "daily_volatility": {
            "mean": _to_float(mean_daily),
            "stdev": _to_float(stdev_daily),
            "index": round(float(volatility_index), 3),
        },
        "avg_expense": _to_float(avg_expense),
        "max_expense": _to_float(max_expense),
        "distribution": distribution,
        "subcategory_distribution": subcategory_distribution,
        "comparison": {
            "expenses_pct": _pct_change(Decimal(selected_totals["expenses"]), Decimal(previous_totals["expenses"])),
            "incomes_pct": _pct_change(Decimal(selected_totals["incomes"]), Decimal(previous_totals["incomes"])),
            "balance_pct": _pct_change(Decimal(selected_totals["balance"]), Decimal(previous_totals["balance"])),
        },
        "monthly_comparison": monthly_points,
        "forecast_next_month_expense": forecast_next_month,
        "budget": budget,
        "category_forecast": budget.get("category_forecast", []),
        "forecast_alerts": budget.get("forecast_alerts", []),
        "recommendations": tips,
    }


