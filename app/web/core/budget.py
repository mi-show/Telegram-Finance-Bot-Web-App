from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from ...cache import SimpleCache
from ...models import BudgetPlan, CategoryBudgetLimit, Record, RecordType, RecurringEntry, User, UserSettings
from ...schemas import RecordCreate, RecordFilter
from ...services.aggregation_service import AggregationService, clear_stats_cache
from ...services.category_service import (
    canonicalize_category,
    canonicalize_subcategory,
    localize_category,
    localize_subcategory,
)
from ...services.record_service import RecordService
from ...handlers.common_parts.constants import ONBOARDING_INCOME_MARKER
from .base import _learn_from_description, _record_audit_payload, _safe_lang, _to_float, _write_audit
from .currency import clear_user_currency_conversion_anchors

FORECAST_WARNING_THRESHOLD = Decimal("85")
DEFAULT_LIMIT_ALERT_MODE = "threshold_70"
LIMIT_ALERT_THRESHOLDS = {
    "threshold_50": Decimal("50"),
    "threshold_70": Decimal("70"),
}

_limit_series_cache = SimpleCache(ttl_seconds=60)


async def _carry_over_category_limits_from_previous_month(
    session: AsyncSession,
    *,
    user_id: int,
    period_start: date,
    period_end: date,
) -> int:
    """If the exact month has no limits yet, copy them from the previous month.

    This is intentionally lightweight and only applies to exact month bounds.
    """
    if period_start.day != 1:
        return 0

    existing_count = await session.execute(
        select(func.count(CategoryBudgetLimit.id)).where(
            CategoryBudgetLimit.user_id == user_id,
            CategoryBudgetLimit.period_start == period_start,
            CategoryBudgetLimit.period_end == period_end,
        )
    )
    if int(existing_count.scalar_one() or 0) > 0:
        return 0

    prev_start = _month_shift(period_start, -1)
    prev_end = period_start - timedelta(days=1)
    prev_rows = await session.execute(
        select(CategoryBudgetLimit)
        .where(
            CategoryBudgetLimit.user_id == user_id,
            CategoryBudgetLimit.period_start == prev_start,
            CategoryBudgetLimit.period_end == prev_end,
        )
        .order_by(CategoryBudgetLimit.category.asc(), CategoryBudgetLimit.subcategory.asc())
    )
    source = prev_rows.scalars().all()
    if not source:
        return 0

    for row in source:
        session.add(
            CategoryBudgetLimit(
                user_id=user_id,
                category=row.category,
                subcategory=row.subcategory,
                period_start=period_start,
                period_end=period_end,
                limit_amount=row.limit_amount,
            )
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return 0

    clear_limit_series_cache()
    return len(source)


def get_limit_series_cache(key: str) -> dict | None:
    return _limit_series_cache.get(key)


def set_limit_series_cache(key: str, payload: dict) -> None:
    _limit_series_cache.set(key, payload)


def clear_limit_series_cache() -> None:
    _limit_series_cache.clear()


def _normalize_limit_alert_mode(mode: str | None) -> str:
    normalized = (mode or DEFAULT_LIMIT_ALERT_MODE).strip().lower()
    if normalized == "always":
        return "always"
    # accept threshold_N (N between 1 and 100)
    if normalized.startswith("threshold_"):
        try:
            n = int(normalized.split("_")[1])
            if 1 <= n <= 100:
                return f"threshold_{n}"
        except Exception:
            pass
    return DEFAULT_LIMIT_ALERT_MODE


def _limit_alert_threshold(mode: str) -> Decimal | None:
    if mode == "always":
        return None
    if mode.startswith("threshold_"):
        try:
            n = int(mode.split("_")[1])
            return Decimal(n)
        except Exception:
            return LIMIT_ALERT_THRESHOLDS.get("threshold_70")
    return LIMIT_ALERT_THRESHOLDS.get("threshold_70")


def _overlap_days(start_a: date, end_a: date, start_b: date, end_b: date) -> int:
    start = max(start_a, start_b)
    end = min(end_a, end_b)
    if start > end:
        return 0
    return (end - start).days + 1


def _scaled_amount_for_overlap(amount: Decimal, overlap_days: int, total_days: int) -> Decimal:
    if overlap_days <= 0 or total_days <= 0:
        return Decimal("0")
    if overlap_days >= total_days:
        return Decimal(amount)
    scaled = Decimal(amount) * (Decimal(overlap_days) / Decimal(total_days))
    return scaled.quantize(Decimal("0.01"))


def _recurring_income_multiplier_for_period(period: str | None) -> Decimal | None:
    normalized = (period or "").strip().lower()
    if normalized in {"week", "7d"}:
        return Decimal("0.25")
    if normalized in {"month", "30d"}:
        return Decimal("1")
    if normalized in {"quarter", "90d"}:
        return Decimal("3")
    if normalized in {"6m", "halfyear"}:
        return Decimal("6")
    if normalized == "year":
        return Decimal("12")
    return None


def _due_date_for_period(period_start: date, day_of_month: int) -> date:
    month_end = _month_shift(period_start, 1) - timedelta(days=1)
    normalized_day = max(1, min(int(day_of_month), month_end.day))
    return date(period_start.year, period_start.month, normalized_day)


def _iter_month_starts(period_start: date, period_end: date) -> list[date]:
    if period_end < period_start:
        return []
    cursor = date(period_start.year, period_start.month, 1)
    month_starts: list[date] = []
    while cursor <= period_end:
        month_starts.append(cursor)
        cursor = _month_shift(cursor, 1)
    return month_starts


async def _sync_legacy_onboarding_recurring_income_confirmation(
    session: AsyncSession,
    *,
    user_id: int,
    current_day: date,
) -> int:
    """Backfill confirmation period for legacy onboarding recurring incomes.

    Older onboarding flows could create income record + recurring entry while
    leaving recurring.last_confirmed_period empty. That causes recurring
    smoothing to count the same salary twice on rolling periods.
    """
    rows_query = await session.execute(
        select(RecurringEntry).where(
            RecurringEntry.user_id == user_id,
            RecurringEntry.type == RecordType.INCOME,
            RecurringEntry.is_active.is_(True),
            RecurringEntry.last_confirmed_period.is_(None),
        )
    )
    rows = rows_query.scalars().all()
    if not rows:
        return 0

    synced = 0
    now_utc = datetime.utcnow()
    for row in rows:
        recurring_subcategory = (row.subcategory or "").strip()
        onboarding_record_query = await session.execute(
            select(Record.happened_on)
            .where(
                Record.user_id == user_id,
                Record.type == RecordType.INCOME,
                Record.category == row.category,
                func.coalesce(Record.subcategory, "") == recurring_subcategory,
                Record.amount == row.amount,
                Record.currency == row.currency,
                Record.description.like(f"%{ONBOARDING_INCOME_MARKER}%"),
                Record.happened_on <= current_day,
            )
            .order_by(Record.happened_on.desc(), Record.id.desc())
            .limit(1)
        )
        latest_onboarding_income_day = onboarding_record_query.scalars().first()
        if latest_onboarding_income_day is None:
            continue

        row.last_confirmed_period = latest_onboarding_income_day.replace(day=1)
        row.last_confirmed_at = row.last_confirmed_at or now_utc
        synced += 1

    return synced


def _recurring_income_expected_for_period(
    rows: Sequence[RecurringEntry],
    *,
    period_start: date,
    period_end: date,
    period: str | None = None,
) -> Decimal:
    """Estimate recurring income for a period.

    For named dashboard periods we use fixed multipliers:
    week=1/4, month=1, quarter=3, halfyear=6, year=12.
    For custom date ranges we keep overlap-based accrual.
    """
    if period_end < period_start:
        return Decimal("0")

    named_multiplier = _recurring_income_multiplier_for_period(period)
    if named_multiplier is not None:
        monthly_sum = Decimal("0")
        for row in rows:
            if not row.is_active:
                continue
            if row.type != RecordType.INCOME:
                continue
            monthly_sum += Decimal(row.amount or 0)
        return (monthly_sum * named_multiplier).quantize(Decimal("0.01"))

    total = Decimal("0")
    month_starts = _iter_month_starts(period_start, period_end)
    for month_start in month_starts:
        month_end = _month_shift(month_start, 1) - timedelta(days=1)
        month_days = (month_end - month_start).days + 1
        overlap_days = _overlap_days(month_start, month_end, period_start, period_end)
        if overlap_days <= 0:
            continue

        for row in rows:
            if not row.is_active:
                continue
            if row.type != RecordType.INCOME:
                continue
            total += _scaled_amount_for_overlap(Decimal(row.amount), overlap_days, month_days)

    return total


def _recurring_income_spikes_in_actual_records(
    rows: Sequence[RecurringEntry],
    *,
    period_start: date,
    period_end: date,
) -> Decimal:
    """Sum recurring income amounts that are likely already present as single records.

    A recurring entry is treated as "spike in records" for a month if it was confirmed
    for that month and its due date falls into the selected period.
    """
    if period_end < period_start:
        return Decimal("0")

    total = Decimal("0")
    month_starts = _iter_month_starts(period_start, period_end)
    for month_start in month_starts:
        month_end = _month_shift(month_start, 1) - timedelta(days=1)
        if _overlap_days(month_start, month_end, period_start, period_end) <= 0:
            continue

        for row in rows:
            if not row.is_active:
                continue
            if row.type != RecordType.INCOME:
                continue

            if row.last_confirmed_period != month_start:
                continue

            due_date = _due_date_for_period(month_start, row.day_of_month)
            if due_date < period_start or due_date > period_end:
                continue

            total += Decimal(row.amount)

    return total


async def _recurring_income_delta_for_period(
    session: AsyncSession,
    *,
    user_id: int,
    period_start: date,
    period_end: date,
    period: str | None = None,
) -> Decimal:
    """Return delta to add to actual totals to get smoothed recurring income."""
    rows_query = await session.execute(
        select(RecurringEntry).where(
            RecurringEntry.user_id == user_id,
            RecurringEntry.type == RecordType.INCOME,
            RecurringEntry.is_active.is_(True),
        )
    )
    rows = rows_query.scalars().all()
    if not rows:
        return Decimal("0")

    expected = _recurring_income_expected_for_period(
        rows,
        period_start=period_start,
        period_end=period_end,
        period=period,
    )
    spikes = _recurring_income_spikes_in_actual_records(
        rows,
        period_start=period_start,
        period_end=period_end,
    )
    return (expected - spikes).quantize(Decimal("0.01"))


def _serialize_recurring_entry(
    row: RecurringEntry,
    *,
    language: str,
    period_start: date,
    today: date | None = None,
) -> dict[str, Any]:
    now = today or date.today()
    due_date = _due_date_for_period(period_start, row.day_of_month)
    reminder_date = due_date - timedelta(days=max(int(row.reminder_days_before or 0), 0))
    confirmed_for_month = row.last_confirmed_period == period_start
    reminder_due = bool(row.is_active and not confirmed_for_month and now >= reminder_date)

    return {
        "id": row.id,
        "title": row.title,
        "type": row.type.value,
        "category": localize_category(row.category, language) or row.category,
        "subcategory": row.subcategory,
        "amount": _to_float(row.amount),
        "currency": row.currency,
        "day_of_month": row.day_of_month,
        "reminder_days_before": row.reminder_days_before,
        "is_active": bool(row.is_active),
        "due_date": due_date.isoformat(),
        "confirmed_for_month": confirmed_for_month,
        "reminder_due": reminder_due,
        "last_confirmed_period": row.last_confirmed_period.isoformat() if row.last_confirmed_period else None,
        "last_confirmed_at": row.last_confirmed_at.isoformat() if row.last_confirmed_at else None,
    }


async def _auto_apply_recurring_for_current_month(
    session: AsyncSession,
    *,
    telegram_id: int,
    user_id: int,
    default_currency: str,
    today: date | None = None,
) -> int:
    current_day = today or date.today()
    period_start = current_day.replace(day=1)

    synced_legacy = await _sync_legacy_onboarding_recurring_income_confirmation(
        session,
        user_id=user_id,
        current_day=current_day,
    )

    pending_stmt = (
        select(RecurringEntry)
        .where(
            RecurringEntry.user_id == user_id,
            RecurringEntry.is_active.is_(True),
            (RecurringEntry.last_confirmed_period.is_(None))
            | (RecurringEntry.last_confirmed_period < period_start),
        )
        .order_by(RecurringEntry.id.asc())
        .with_for_update()
    )
    pending_rows = (await session.execute(pending_stmt)).scalars().all()

    if not pending_rows:
        if synced_legacy:
            await session.commit()
            clear_user_currency_conversion_anchors(session, user_id=user_id)
            clear_stats_cache()
            clear_limit_series_cache()
        return 0

    service = RecordService(session, telegram_id)
    auto_applied = 0

    for row in pending_rows:
        if row.last_confirmed_period == period_start:
            continue

        due_date = _due_date_for_period(period_start, row.day_of_month)
        if due_date > current_day:
            continue

        description = (row.title or "").strip()
        if not description:
            continue

        payload = RecordCreate(
            type=row.type.value,
            category=row.category,
            subcategory=row.subcategory,
            amount=Decimal(row.amount),
            currency=(row.currency or default_currency or "UAH").upper(),
            happened_on=due_date,
            description=description,
        )
        try:
            record = await service.add(payload)
        except ValueError:
            continue

        before_period = row.last_confirmed_period
        before_confirmed_at = row.last_confirmed_at
        before_confirm = {
            "last_confirmed_period": before_period.isoformat() if before_period is not None else None,
            "last_confirmed_at": before_confirmed_at.isoformat() if before_confirmed_at is not None else None,
        }

        row.last_confirmed_period = period_start
        row.last_confirmed_at = datetime.utcnow()

        after_confirm = {
            "last_confirmed_period": row.last_confirmed_period.isoformat() if row.last_confirmed_period is not None else None,
            "last_confirmed_at": row.last_confirmed_at.isoformat() if row.last_confirmed_at is not None else None,
        }

        await _write_audit(
            session,
            user_id=user_id,
            action="recurring.auto_confirm",
            entity_type="recurring_entry",
            entity_id=row.id,
            before=before_confirm,
            after=after_confirm,
        )
        await _write_audit(
            session,
            user_id=user_id,
            action="record.create",
            entity_type="record",
            entity_id=record.id,
            before=None,
            after=_record_audit_payload(record),
        )

        await _learn_from_description(
            session,
            user_id=user_id,
            description=record.description,
            category=record.category,
            subcategory=record.subcategory,
        )

        auto_applied += 1

    if auto_applied or synced_legacy:
        await session.commit()
        clear_user_currency_conversion_anchors(session, user_id=user_id)
        clear_stats_cache()
        clear_limit_series_cache()

    return auto_applied


async def _recurring_month_summary(
    session: AsyncSession,
    *,
    user_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    rows_query = await session.execute(
        select(RecurringEntry).where(
            RecurringEntry.user_id == user_id,
            RecurringEntry.is_active.is_(True),
        )
    )
    rows = rows_query.scalars().all()

    planned_income = Decimal("0")
    planned_expense = Decimal("0")
    confirmed_income = Decimal("0")
    confirmed_expense = Decimal("0")
    pending_items = 0

    for row in rows:
        due_date = _due_date_for_period(period_start, row.day_of_month)
        if due_date < period_start or due_date > period_end:
            continue

        amount = Decimal(row.amount or 0)
        is_confirmed = row.last_confirmed_period == period_start

        if row.type == RecordType.INCOME:
            planned_income += amount
            if is_confirmed:
                confirmed_income += amount
        else:
            planned_expense += amount
            if is_confirmed:
                confirmed_expense += amount

        if not is_confirmed:
            pending_items += 1

    return {
        "planned_income": _to_float(planned_income),
        "planned_expense": _to_float(planned_expense),
        "confirmed_income": _to_float(confirmed_income),
        "confirmed_expense": _to_float(confirmed_expense),
        "pending_items": pending_items,
    }


def _category_projection(
    category_spend: dict[tuple[str, str | None], Decimal],
    period_start: date,
    period_end: date,
) -> tuple[dict[tuple[str, str | None], Decimal], int, int]:
    total_days = (period_end - period_start).days + 1
    elapsed_end = min(date.today(), period_end)
    if elapsed_end < period_start:
        return {}, 0, total_days

    elapsed_days = (elapsed_end - period_start).days + 1
    projected: dict[tuple[str, str | None], Decimal] = {}

    for bucket, spent in category_spend.items():
        if elapsed_days <= 0 or total_days <= 0:
            projected[bucket] = Decimal("0")
            continue
        projected_amount = (Decimal(spent) / Decimal(elapsed_days)) * Decimal(total_days)
        projected[bucket] = projected_amount.quantize(Decimal("0.01"))

    return projected, elapsed_days, total_days


def _date_bounds(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    if date_from and date_to:
        if date_from > date_to:
            raise HTTPException(status_code=400, detail="date_from must be <= date_to")
        return date_from, date_to

    today = date.today()
    normalized = (period or "month").lower()

    if normalized == "today":
        return today, today
    if normalized in {"week", "7d"}:
        week_start = today - timedelta(days=today.weekday())
        return week_start, today
    if normalized in {"month", "30d"}:
        month_start = today.replace(day=1)
        return month_start, today
    if normalized in {"6m", "halfyear"}:
        return today - timedelta(days=182), today
    if normalized in {"quarter", "90d"}:
        return today - timedelta(days=89), today
    if normalized == "year":
        return today - timedelta(days=364), today

    return today - timedelta(days=29), today


def _prev_bounds(start: date, end: date) -> tuple[date, date]:
    size = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=size - 1)
    return prev_start, prev_end


def _pct_change(current: Decimal, previous: Decimal) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(float((current - previous) / previous * Decimal("100")), 2)


def _month_shift(base_month_start: date, delta: int) -> date:
    month_index = base_month_start.month - 1 + delta
    year = base_month_start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _month_bounds(target_year: int, target_month: int) -> tuple[date, date]:
    start = date(target_year, target_month, 1)
    if target_month == 12:
        end = date(target_year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(target_year, target_month + 1, 1) - timedelta(days=1)
    return start, end


async def _get_recurring_entry(
    session: AsyncSession,
    *,
    user_id: int,
    recurring_id: int,
) -> RecurringEntry | None:
    row = await session.execute(
        select(RecurringEntry).where(
            RecurringEntry.user_id == user_id,
            RecurringEntry.id == recurring_id,
        )
    )
    return row.scalars().first()


async def _category_spend(
    session: AsyncSession,
    telegram_id: int,
    period_start: date,
    period_end: date,
) -> dict[tuple[str, str | None], Decimal]:
    stmt = (
        select(Record.category, Record.subcategory, func.coalesce(func.sum(Record.amount), 0))
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= period_start,
            Record.happened_on <= period_end,
        )
        .group_by(Record.category, Record.subcategory)
    )
    rows = await session.execute(stmt)
    grouped: dict[tuple[str, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    for category, subcategory, total in rows.all():
        canonical = canonicalize_category(category) or category
        normalized_subcategory = (subcategory or "").strip() or None
        if normalized_subcategory is not None:
            normalized_subcategory = canonicalize_subcategory(canonical, normalized_subcategory) or normalized_subcategory
        grouped[(canonical, normalized_subcategory)] += Decimal(total or 0)
    return dict(grouped)


async def _budget_snapshot(
    session: AsyncSession,
    telegram_id: int,
    user_id: int,
    period_start: date,
    period_end: date,
    language: str,
    *,
    limit_alert_mode_override: str | None = None,
) -> dict:
    ui_language = _safe_lang(language)
    agg = AggregationService(session, telegram_id)
    totals = await agg.totals(RecordFilter(date_from=period_start, date_to=period_end))
    spent = Decimal(totals["expenses"])

    plan_query = await session.execute(
        select(BudgetPlan)
        .where(
            BudgetPlan.user_id == user_id,
            BudgetPlan.period_start <= period_end,
            BudgetPlan.period_end >= period_start,
        )
        .order_by(BudgetPlan.created_at.desc())
        .limit(1)
    )
    plan = plan_query.scalars().first()

    settings_mode_query = await session.execute(
        select(
            UserSettings.limit_alert_mode,
            UserSettings.budget_warning_percent,
            UserSettings.budget_danger_percent,
        ).where(UserSettings.user_id == user_id)
    )
    settings_row = settings_mode_query.first()
    limit_alert_mode = _normalize_limit_alert_mode(
        limit_alert_mode_override if limit_alert_mode_override is not None else (settings_row[0] if settings_row else None)
    )
    warning_threshold = int(settings_row[1] if settings_row and settings_row[1] is not None else 80)
    danger_threshold = int(settings_row[2] if settings_row and settings_row[2] is not None else 100)
    alert_threshold = _limit_alert_threshold(limit_alert_mode)

    category_spend = await _category_spend(session, telegram_id, period_start, period_end)
    category_projection, elapsed_days, total_days = _category_projection(
        category_spend,
        period_start,
        period_end,
    )

    limit_rows = await session.execute(
        select(CategoryBudgetLimit)
        .where(
            CategoryBudgetLimit.user_id == user_id,
            CategoryBudgetLimit.period_start <= period_end,
            CategoryBudgetLimit.period_end >= period_start,
        )
        .order_by(CategoryBudgetLimit.category.asc(), CategoryBudgetLimit.subcategory.asc())
    )

    limit_totals: dict[tuple[str, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    limit_ids: dict[tuple[str, str | None], int] = {}
    protected_subcategories_by_category: dict[str, set[str]] = defaultdict(set)
    for row in limit_rows.scalars().all():
        limit_days = (row.period_end - row.period_start).days + 1
        overlap_days = _overlap_days(row.period_start, row.period_end, period_start, period_end)
        if overlap_days <= 0:
            continue

        scaled_limit = _scaled_amount_for_overlap(Decimal(row.limit_amount), overlap_days, limit_days)
        canonical_category = canonicalize_category(row.category) or row.category
        normalized_subcategory = (row.subcategory or "").strip() or None
        if normalized_subcategory is not None:
            normalized_subcategory = (
                canonicalize_subcategory(canonical_category, normalized_subcategory) or normalized_subcategory
            )
        key = (canonical_category, normalized_subcategory)
        limit_totals[key] += scaled_limit
        limit_ids.setdefault(key, row.id)
        if normalized_subcategory is not None:
            protected_subcategories_by_category[canonical_category].add(normalized_subcategory)

    category_spend_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for (canonical_category, _subcategory), amount in category_spend.items():
        category_spend_totals[canonical_category] += amount

    category_projection_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for (canonical_category, _subcategory), amount in category_projection.items():
        category_projection_totals[canonical_category] += amount

    category_limit_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for (canonical_category, _subcategory), amount in limit_totals.items():
        category_limit_totals[canonical_category] += amount

    today = date.today()
    if period_end < today:
        days_remaining = 0
    elif today <= period_start:
        days_remaining = (period_end - period_start).days + 1
    else:
        days_remaining = (period_end - today).days + 1

    limits = []
    alerts = []
    forecast_alerts = []

    sorted_categories = sorted(
        limit_totals.keys(),
        key=lambda key: (
            localize_category(key[0], ui_language) or key[0],
            (localize_subcategory(key[0], key[1], ui_language) or key[1] or ""),
        ),
    )

    for canonical_category, canonical_subcategory in sorted_categories:
        limit_amount = limit_totals[(canonical_category, canonical_subcategory)]

        if canonical_subcategory is None:
            protected_subcategories = protected_subcategories_by_category.get(canonical_category, set())
            spent_cat = Decimal("0")
            for (bucket_category, bucket_subcategory), bucket_spend in category_spend.items():
                if bucket_category != canonical_category:
                    continue
                if bucket_subcategory is not None and bucket_subcategory in protected_subcategories:
                    continue
                spent_cat += bucket_spend

            projected_cat = Decimal("0")
            for (bucket_category, bucket_subcategory), bucket_projection in category_projection.items():
                if bucket_category != canonical_category:
                    continue
                if bucket_subcategory is not None and bucket_subcategory in protected_subcategories:
                    continue
                projected_cat += bucket_projection
        else:
            spent_cat = category_spend.get((canonical_category, canonical_subcategory), Decimal("0"))
            projected_cat = category_projection.get((canonical_category, canonical_subcategory), Decimal("0"))

        remaining = limit_amount - spent_cat
        used_percent_decimal = ((spent_cat / limit_amount) * Decimal("100")) if limit_amount else Decimal("0")
        forecast_used_percent_decimal = ((projected_cat / limit_amount) * Decimal("100")) if limit_amount else Decimal("0")
        used_percent = float(used_percent_decimal)
        forecast_used_percent = float(forecast_used_percent_decimal)

        if used_percent > 100:
            status = "exceeded"
        elif used_percent >= 80:
            status = "near_limit"
        else:
            status = "normal"

        if forecast_used_percent > 100:
            forecast_status = "forecast_exceeded"
        elif forecast_used_percent >= float(FORECAST_WARNING_THRESHOLD):
            forecast_status = "forecast_near_limit"
        else:
            forecast_status = "forecast_normal"

        category_label = localize_category(canonical_category, ui_language) or canonical_category
        subcategory_label = None
        if canonical_subcategory:
            subcategory_label = (
                localize_subcategory(canonical_category, canonical_subcategory, ui_language) or canonical_subcategory
            )

        if days_remaining > 0 and remaining > 0:
            recommended_daily_spend = (remaining / Decimal(days_remaining)).quantize(Decimal("0.01"))
            recommended_daily_value = _to_float(recommended_daily_spend)
        elif days_remaining > 0:
            recommended_daily_value = 0.0
        else:
            recommended_daily_value = None

        payload = {
            "canonical_category": canonical_category,
            "canonical_subcategory": canonical_subcategory,
            "id": limit_ids.get((canonical_category, canonical_subcategory)),
            "category": category_label,
            "subcategory": subcategory_label,
            "limit": _to_float(limit_amount),
            "spent": _to_float(spent_cat),
            "forecast": _to_float(projected_cat),
            "forecast_used_percent": round(forecast_used_percent, 2),
            "forecast_status": forecast_status,
            "remaining": _to_float(remaining),
            "used_percent": round(used_percent, 2),
            "recommended_daily_spend": recommended_daily_value,
            "status": status,
        }
        limits.append(payload)

        if limit_alert_mode == "always":
            should_alert = limit_amount > 0
            should_forecast_alert = limit_amount > 0
        else:
            threshold = alert_threshold or LIMIT_ALERT_THRESHOLDS["threshold_70"]
            should_alert = used_percent_decimal >= threshold
            should_forecast_alert = forecast_used_percent_decimal >= threshold

        if should_alert:
            alerts.append(payload)
        if should_forecast_alert:
            forecast_alerts.append(payload)

    forecast_categories = sorted(
        set(category_projection_totals.keys())
        | set(category_limit_totals.keys())
        | set(category_spend_totals.keys()),
        key=lambda canonical: (localize_category(canonical, ui_language) or canonical),
    )
    category_forecast = []
    for canonical in forecast_categories:
        projected_cat = category_projection_totals.get(canonical, Decimal("0"))
        spent_cat = category_spend_totals.get(canonical, Decimal("0"))
        limit_amount = category_limit_totals.get(canonical)
        category_label = localize_category(canonical, ui_language) or canonical

        if limit_amount is not None and limit_amount > 0:
            projected_used_percent = float((projected_cat / limit_amount) * Decimal("100"))
            if projected_used_percent > 100:
                projected_status = "forecast_exceeded"
            elif projected_used_percent >= float(FORECAST_WARNING_THRESHOLD):
                projected_status = "forecast_near_limit"
            else:
                projected_status = "forecast_normal"
            limit_value = _to_float(limit_amount)
        else:
            projected_used_percent = None
            projected_status = "forecast_unbounded"
            limit_value = None

        if limit_amount is not None and limit_amount > 0 and days_remaining > 0:
            category_remaining = max(Decimal("0"), limit_amount - spent_cat)
            recommended_daily_spend = (category_remaining / Decimal(days_remaining)).quantize(Decimal("0.01"))
            recommended_daily_value = _to_float(recommended_daily_spend)
        elif days_remaining > 0:
            recommended_daily_value = 0.0
        else:
            recommended_daily_value = None

        category_forecast.append(
            {
                "category": category_label,
                "spent": _to_float(spent_cat),
                "projected": _to_float(projected_cat),
                "limit": limit_value,
                "projected_used_percent": round(projected_used_percent, 2) if projected_used_percent is not None else None,
                "recommended_daily_spend": recommended_daily_value,
                "status": projected_status,
            }
        )

    if plan:
        plan_days = (plan.period_end - plan.period_start).days + 1
        overlap_days = _overlap_days(plan.period_start, plan.period_end, period_start, period_end)
        planned_expense = _scaled_amount_for_overlap(Decimal(plan.planned_expense), overlap_days, plan_days)
        planned_income = _scaled_amount_for_overlap(Decimal(plan.planned_income), overlap_days, plan_days)
        month_remaining = planned_expense - spent
        month_used = float((spent / planned_expense * 100) if planned_expense else 0)
    else:
        planned_expense = Decimal("0")
        planned_income = Decimal("0")
        month_remaining = Decimal("0")
        month_used = 0.0

    if days_remaining > 0 and month_remaining > 0:
        month_recommended_daily_spend = (month_remaining / Decimal(days_remaining)).quantize(Decimal("0.01"))
        month_recommended_daily_value = _to_float(month_recommended_daily_spend)
    elif days_remaining > 0:
        month_recommended_daily_value = 0.0
    else:
        month_recommended_daily_value = None

    if month_used >= danger_threshold:
        month_status = "exceeded"
    elif month_used >= warning_threshold:
        month_status = "near_limit"
    else:
        month_status = "normal"

    recurring_summary = await _recurring_month_summary(
        session,
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
    )

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "forecast_threshold_percent": float(FORECAST_WARNING_THRESHOLD),
        "limit_alert_mode": limit_alert_mode,
        "limit_alert_threshold_percent": float(alert_threshold) if alert_threshold is not None else None,
        "budget_warning_percent": warning_threshold,
        "budget_danger_percent": danger_threshold,
        "projection_context": {
            "elapsed_days": elapsed_days,
            "total_days": total_days,
            "days_remaining": days_remaining,
        },
        "monthly_plan": {
            "id": plan.id if plan else None,
            "planned_expense": _to_float(planned_expense) if plan else None,
            "planned_income": _to_float(planned_income) if plan else None,
            "spent": _to_float(spent),
            "remaining": _to_float(month_remaining),
            "used_percent": round(month_used, 2),
            "recommended_daily_spend": month_recommended_daily_value,
            "status": month_status,
        },
        "category_limits": limits,
        "alerts": alerts,
        "forecast_alerts": forecast_alerts,
        "category_forecast": category_forecast,
        "recurring": recurring_summary,
    }


def _build_filters(
    date_from: date | None,
    date_to: date | None,
    categories: list[str] | None,
    record_type: str | None,
    min_amount: str | None,
    max_amount: str | None,
    query: str | None,
) -> RecordFilter:
    min_value = None
    max_value = None

    try:
        if min_amount is not None and min_amount != "":
            min_value = Decimal(min_amount)
        if max_amount is not None and max_amount != "":
            max_value = Decimal(max_amount)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid min_amount/max_amount") from exc

    if record_type and record_type not in {"income", "expense"}:
        raise HTTPException(status_code=400, detail="type must be income or expense")

    return RecordFilter(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        type=record_type,  # type: ignore[arg-type]
        min_amount=min_value,
        max_amount=max_value,
        description_query=query,
    )


def _recommendations(
    expense_by_category: list[dict],
    balance: Decimal,
    month_budget: dict | None,
    *,
    language: str = "en",
) -> list[str]:
    lang = _safe_lang(language, fallback="en")
    messages = {
        "en": {
            "top_category": "Category '{category}' consumes {percent:.1f}% of expenses. Consider setting a stricter limit.",
            "negative_balance": "Your selected period balance is negative. Try reducing non-essential spending.",
            "budget_near_limit": "Monthly budget is close to limit. Shift discretionary spend to next period.",
            "stable": "Spending profile looks stable. Keep tracking to improve forecast accuracy.",
        },
        "ru": {
            "top_category": "Категория «{category}» занимает {percent:.1f}% расходов. Рекомендуется установить более строгий лимит.",
            "negative_balance": "Баланс за выбранный период отрицательный. Попробуйте сократить необязательные расходы.",
            "budget_near_limit": "Месячный бюджет близок к лимиту. Перенесите необязательные траты на следующий период.",
            "stable": "Профиль расходов выглядит стабильно. Продолжайте вести учет для более точного прогноза.",
        },
        "uk": {
            "top_category": "Категорія «{category}» займає {percent:.1f}% витрат. Рекомендується встановити суворіший ліміт.",
            "negative_balance": "Баланс за вибраний період від'ємний. Спробуйте зменшити необов'язкові витрати.",
            "budget_near_limit": "Місячний бюджет наближається до ліміту. Перенесіть необов'язкові витрати на наступний період.",
            "stable": "Профіль витрат виглядає стабільним. Продовжуйте облік для точнішого прогнозу.",
        },
    }[lang]

    tips: list[str] = []
    if expense_by_category:
        top = max(expense_by_category, key=lambda item: item["amount"])
        if top["percent"] >= 40:
            tips.append(
                messages["top_category"].format(category=top["category"], percent=top["percent"])
            )

    if balance < 0:
        tips.append(messages["negative_balance"])

    if month_budget and month_budget.get("status") in {"near_limit", "exceeded"}:
        tips.append(messages["budget_near_limit"])

    if not tips:
        tips.append(messages["stable"])

    return tips
