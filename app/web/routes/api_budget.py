from __future__ import annotations

from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_models import (
    CategoryLimitBatchIn,
    LimitSeriesIn,
    MonthBudgetIn,
)
from ..auth import TelegramWebUser
from ..core.budget import get_limit_series_cache, set_limit_series_cache
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    AggregationService,
    BudgetPlan,
    BudgetPlanCreate,
    CategoryBudgetLimit,
    Decimal,
    Record,
    RecordType,
    User,
    _auto_apply_recurring_for_current_month,
    _budget_snapshot,
    _carry_over_category_limits_from_previous_month,
    _month_bounds,
    _safe_lang,
    _to_float,
    _write_audit,
    canonicalize_category,
    canonicalize_subcategory,
    clear_stats_cache,
    clear_user_currency_conversion_anchors,
    date,
    defaultdict,
    delete,
    func,
    localize_category,
    localize_subcategory,
    select,
    timedelta,
)

router = APIRouter()


@router.get("/api/webapp/budget")
async def webapp_budget(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    today = date.today()
    target_year = year or today.year
    target_month = month or today.month
    if target_month < 1 or target_month > 12:
        raise HTTPException(status_code=400, detail="month must be in range 1..12")

    period_start, period_end = _month_bounds(target_year, target_month)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    # If user didn't set limits for this month yet, keep last month's ones.
    await _carry_over_category_limits_from_previous_month(
        session,
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
    )

    snapshot = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start,
        period_end,
        language=lang,
    )
    return snapshot


@router.put("/api/webapp/budget/month")
async def webapp_budget_month_update(
    payload: MonthBudgetIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    user = await _get_or_create_user(session, auth_user)
    previous_query = await session.execute(
        select(BudgetPlan)
        .where(
            BudgetPlan.user_id == user.id,
            BudgetPlan.period_start == payload.period_start,
            BudgetPlan.period_end == payload.period_end,
        )
        .order_by(BudgetPlan.created_at.desc())
        .limit(1)
    )
    previous = previous_query.scalars().first()
    previous_payload = None
    if previous is not None:
        previous_payload = {
            "id": previous.id,
            "period_start": previous.period_start.isoformat(),
            "period_end": previous.period_end.isoformat(),
            "planned_expense": _to_float(previous.planned_expense),
            "planned_income": _to_float(previous.planned_income),
        }

    agg = AggregationService(session, auth_user.telegram_id)
    plan = BudgetPlanCreate(
        period_start=payload.period_start,
        period_end=payload.period_end,
        planned_expense=payload.planned_expense,
        planned_income=payload.planned_income,
    )

    saved = await agg.save_budget(plan)

    await _write_audit(
        session,
        user_id=user.id,
        action="budget.month.update",
        entity_type="budget_plan",
        entity_id=saved.id,
        before=previous_payload,
        after={
            "id": saved.id,
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
            "planned_expense": _to_float(payload.planned_expense),
            "planned_income": _to_float(payload.planned_income),
        },
    )

    await session.commit()
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()

    status = await agg.budget_status(plan)
    return {
        "id": saved.id,
        "planned_expense": _to_float(payload.planned_expense),
        "planned_income": _to_float(payload.planned_income),
        "period_start": payload.period_start.isoformat(),
        "period_end": payload.period_end.isoformat(),
        "spent": _to_float(Decimal(status["spent"])),
        "remaining": _to_float(Decimal(status["remaining"])),
        "used_percent": float(status["used_percent"]),
    }


@router.put("/api/webapp/budget/category-limits")
async def webapp_category_limits_update(
    payload: CategoryLimitBatchIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")
    previous_limit_alert_mode = settings_row.limit_alert_mode or "threshold_70"
    limit_alert_mode_override = None
    if payload.limit_alert_mode is not None:
        requested = (payload.limit_alert_mode or "").strip().lower()
        # Persist only preset modes; allow custom thresholds for preview without
        # changing the stored user setting.
        if requested in {"always", "threshold_50", "threshold_70"}:
            settings_row.limit_alert_mode = requested
        else:
            limit_alert_mode_override = requested

    existing_rows = await session.execute(
        select(CategoryBudgetLimit)
        .where(
            CategoryBudgetLimit.user_id == user.id,
            CategoryBudgetLimit.period_start == payload.period_start,
            CategoryBudgetLimit.period_end == payload.period_end,
        )
        .order_by(CategoryBudgetLimit.category.asc(), CategoryBudgetLimit.subcategory.asc())
    )
    before_limits = [
        {
            "id": row.id,
            "category": row.category,
            "subcategory": row.subcategory,
            "limit_amount": _to_float(Decimal(row.limit_amount)),
        }
        for row in existing_rows.scalars().all()
    ]

    await session.execute(
        delete(CategoryBudgetLimit).where(
            CategoryBudgetLimit.user_id == user.id,
            CategoryBudgetLimit.period_start == payload.period_start,
            CategoryBudgetLimit.period_end == payload.period_end,
        )
    )

    normalized_limits: dict[tuple[str, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    for item in payload.limits:
        canonical = canonicalize_category(item.category) or item.category
        normalized_subcategory = (item.subcategory or "").strip() or None
        if normalized_subcategory is not None:
            normalized_subcategory = (
                canonicalize_subcategory(canonical, normalized_subcategory) or normalized_subcategory
            )
        normalized_limits[(canonical, normalized_subcategory)] += Decimal(item.limit_amount)

    for (category, subcategory), limit_amount in normalized_limits.items():
        row = CategoryBudgetLimit(
            user_id=user.id,
            category=category,
            subcategory=subcategory,
            period_start=payload.period_start,
            period_end=payload.period_end,
            limit_amount=limit_amount,
        )
        session.add(row)

    after_limits = [
        {
            "category": category,
            "subcategory": subcategory,
            "limit_amount": _to_float(limit_amount),
        }
        for (category, subcategory), limit_amount in sorted(
            normalized_limits.items(),
            key=lambda item: (item[0][0], item[0][1] or ""),
        )
    ]

    await _write_audit(
        session,
        user_id=user.id,
        action="budget.category_limits.update",
        entity_type="category_limits",
        entity_id=None,
        before={
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
            "limit_alert_mode": previous_limit_alert_mode,
            "limits": before_limits,
        },
        after={
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
            "limit_alert_mode": settings_row.limit_alert_mode or "threshold_70",
            "limits": after_limits,
        },
    )

    await session.commit()
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    snapshot = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        payload.period_start,
        payload.period_end,
        language=lang,
        limit_alert_mode_override=limit_alert_mode_override,
    )
    return snapshot


@router.post("/api/webapp/budget/limit-series")
async def webapp_budget_limit_series(
    payload: LimitSeriesIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    # Canonicalize keys for matching
    requested = []
    key_labels = {}
    for item in payload.keys:
        canonical = canonicalize_category(item.category) or item.category
        normalized_sub = (item.subcategory or "").strip() or None
        if normalized_sub is not None:
            normalized_sub = canonicalize_subcategory(canonical, normalized_sub) or normalized_sub
        requested.append((canonical, normalized_sub))
        localized_category = localize_category(canonical, lang) or canonical
        localized_sub = None
        if normalized_sub:
            localized_sub = localize_subcategory(canonical, normalized_sub, lang) or normalized_sub
        key_labels[(canonical, normalized_sub)] = (localized_category, localized_sub)

    keys_seed = "|".join(
        [f"{cat}::{sub or ''}" for cat, sub in requested]
    )
    cache_key = sha256(
        f"{user.id}:{lang}:{payload.period_start.isoformat()}:{payload.period_end.isoformat()}:{keys_seed}".encode(
            "utf-8"
        )
    ).hexdigest()
    cached = get_limit_series_cache(cache_key)
    if cached is not None:
        return cached

    # Build daily series for each requested key
    series_map = {}
    current = payload.period_start
    while current <= payload.period_end:
        current += timedelta(days=1)

    daily_stmt = (
        select(Record.happened_on, Record.category, Record.subcategory, func.coalesce(func.sum(Record.amount), 0))
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == auth_user.telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= payload.period_start,
            Record.happened_on <= payload.period_end,
        )
        .group_by(Record.happened_on, Record.category, Record.subcategory)
    )
    daily_rows = await session.execute(daily_stmt)

    # Initialize map with zeros
    day_labels = []
    cursor = payload.period_start
    while cursor <= payload.period_end:
        day_labels.append(cursor.isoformat())
        cursor += timedelta(days=1)

    for key in requested:
        series_map[key] = {label: 0.0 for label in day_labels}

    for happened_on, category, subcategory, total in daily_rows.all():
        canonical = canonicalize_category(category) or category
        normalized_sub = (subcategory or "").strip() or None
        if normalized_sub is not None:
            normalized_sub = canonicalize_subcategory(canonical, normalized_sub) or normalized_sub
        key = (canonical, normalized_sub)
        if key not in series_map:
            continue
        series_map[key][happened_on.isoformat()] += float(total or 0)

    payload_items = []
    for canonical, subcategory in requested:
        localized_category, localized_subcategory = key_labels.get(
            (canonical, subcategory),
            (localize_category(canonical, lang) or canonical, None),
        )
        data = series_map.get((canonical, subcategory), {})
        points = [round(float(data[label]), 2) for label in day_labels]

        payload_items.append(
            {
                "category": localized_category,
                "subcategory": localized_subcategory,
                "canonical_category": canonical,
                "canonical_subcategory": subcategory,
                "days": day_labels,
                "amounts": points,
            }
        )

    response_payload = {
        "period_start": payload.period_start.isoformat(),
        "period_end": payload.period_end.isoformat(),
        "items": payload_items,
    }
    set_limit_series_cache(cache_key, response_payload)
    return response_payload


@router.delete("/api/webapp/budget/{budget_id}")
async def webapp_budget_delete(
    budget_id: int,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    query = await session.execute(
        select(BudgetPlan).where(BudgetPlan.user_id == user.id, BudgetPlan.id == budget_id)
    )
    row = query.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="budget not found")

    before_payload = {
        "id": row.id,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "planned_expense": _to_float(row.planned_expense),
        "planned_income": _to_float(row.planned_income),
    }

    await session.delete(row)

    await _write_audit(
        session,
        user_id=user.id,
        action="budget.month.delete",
        entity_type="budget_plan",
        entity_id=budget_id,
        before=before_payload,
        after=None,
    )

    await session.commit()
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()

    return {"ok": True, "deleted": before_payload}


