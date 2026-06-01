from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BudgetPlan, CategoryBudgetLimit, Record, RecordType, RecurringEntry, User, UserSettings
from .services.aggregation_service import AggregationService
from .services.category_service import canonicalize_category, canonicalize_subcategory, localize_category, localize_subcategory


def _to_float(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _safe_lang(language: str | None, fallback: str = "uk") -> str:
    value = (language or fallback).lower()
    return value if value in {"uk", "ru", "en"} else fallback


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


def _limit_alert_threshold(mode: str) -> Decimal | None:
    if mode == "always":
        return None
    if mode == "threshold_50":
        return Decimal("50")
    return Decimal("70")


def _normalize_limit_alert_mode(mode: str | None) -> str:
    normalized = (mode or "threshold_70").strip().lower()
    if normalized == "always":
        return "always"
    if normalized.startswith("threshold_"):
        try:
            n = int(normalized.split("_")[1])
            if 1 <= n <= 100:
                return f"threshold_{n}"
        except Exception:
            pass
    return "threshold_70"


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


async def _category_spend(
    session: AsyncSession,
    telegram_id: int,
    period_start: date,
    period_end: date,
) -> dict[tuple[str, str | None], Decimal]:
    stmt = (
        select(Record.category, Record.subcategory, Record.amount)
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= period_start,
            Record.happened_on <= period_end,
        )
    )
    rows = await session.execute(stmt)
    grouped: dict[tuple[str, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    for category, subcategory, amount in rows.all():
        canonical = canonicalize_category(category) or category
        normalized_subcategory = (subcategory or "").strip() or None
        if normalized_subcategory is not None:
            normalized_subcategory = canonicalize_subcategory(canonical, normalized_subcategory) or normalized_subcategory
        grouped[(canonical, normalized_subcategory)] += Decimal(amount or 0)
    return dict(grouped)


async def _budget_snapshot(
    session: AsyncSession,
    telegram_id: int,
    user_id: int,
    period_start: date,
    period_end: date,
    language: str,
) -> dict:
    ui_language = _safe_lang(language)
    agg = AggregationService(session, telegram_id)
    totals = await agg.totals()
    spent = Decimal(totals["expenses"])

    settings_mode_query = await session.execute(
        select(UserSettings.limit_alert_mode).where(UserSettings.user_id == user_id)
    )
    limit_alert_mode = _normalize_limit_alert_mode(settings_mode_query.scalar_one_or_none())
    alert_threshold = _limit_alert_threshold(limit_alert_mode)

    category_spend = await _category_spend(session, telegram_id, period_start, period_end)
    category_projection, elapsed_days, total_days = _category_projection(category_spend, period_start, period_end)

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
            normalized_subcategory = canonicalize_subcategory(canonical_category, normalized_subcategory) or normalized_subcategory
        key = (canonical_category, normalized_subcategory)
        limit_totals[key] += scaled_limit
        limit_ids.setdefault(key, row.id)
        if normalized_subcategory is not None:
            protected_subcategories_by_category[canonical_category].add(normalized_subcategory)

    today = date.today()
    if period_end < today:
        days_remaining = 0
    elif today <= period_start:
        days_remaining = (period_end - period_start).days + 1
    else:
        days_remaining = (period_end - today).days + 1

    limits = []
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

        if days_remaining > 0 and remaining > 0:
            recommended_daily_spend = (remaining / Decimal(days_remaining)).quantize(Decimal("0.01"))
            recommended_daily_value = _to_float(recommended_daily_spend)
        elif days_remaining > 0:
            recommended_daily_value = 0.0
        else:
            recommended_daily_value = None

        category_label = localize_category(canonical_category, ui_language) or canonical_category
        subcategory_label = None
        if canonical_subcategory:
            subcategory_label = localize_subcategory(canonical_category, canonical_subcategory, ui_language) or canonical_subcategory

        payload = {
            "id": limit_ids.get((canonical_category, canonical_subcategory)),
            "category": category_label,
            "subcategory": subcategory_label,
            "limit": _to_float(limit_amount),
            "spent": _to_float(spent_cat),
            "forecast": _to_float(projected_cat),
            "forecast_used_percent": round(float(forecast_used_percent_decimal), 2),
            "forecast_status": "forecast_exceeded" if forecast_used_percent_decimal > 100 else ("forecast_near_limit" if forecast_used_percent_decimal >= 85 else "forecast_normal"),
            "remaining": _to_float(remaining),
            "used_percent": round(float(used_percent_decimal), 2),
            "recommended_daily_spend": recommended_daily_value,
            "status": "exceeded" if used_percent_decimal > 100 else ("near_limit" if used_percent_decimal >= 80 else "normal"),
        }
        limits.append(payload)

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "limit_alert_mode": limit_alert_mode,
        "limit_alert_threshold_percent": float(alert_threshold) if alert_threshold is not None else None,
        "projection_context": {
            "elapsed_days": elapsed_days,
            "total_days": total_days,
            "days_remaining": days_remaining,
        },
        "category_limits": limits,
        "monthly_plan": None,
        "recurring_summary": None,
        "alerts": [],
        "forecast_alerts": [],
    }