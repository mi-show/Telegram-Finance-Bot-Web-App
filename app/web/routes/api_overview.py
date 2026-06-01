from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    AggregationService,
    CATEGORIES,
    Decimal,
    Record,
    RecordFilter,
    RecordService,
    RecordType,
    User,
    _auto_apply_recurring_for_current_month,
    _budget_snapshot,
    _date_bounds,
    _localize_category_amounts,
    _pct_change,
    _prev_bounds,
    _recurring_income_delta_for_period,
    _safe_lang,
    _serialize_record,
    _serialize_settings,
    _to_float,
    date,
    defaultdict,
    func,
    get_categories_for_lang,
    get_subcategories_for_category,
    select,
    timedelta,
)

router = APIRouter()


@router.get("/api/webapp/bootstrap")
async def webapp_bootstrap(
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    await session.commit()

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    lang = _safe_lang(settings_row.interface_language or user.language or "uk")
    categories = get_categories_for_lang(lang)

    return {
        "user": {
            "telegram_id": user.telegram_id,
            "language": user.language,
            "first_name": auth_user.first_name,
            "last_name": auth_user.last_name,
            "username": auth_user.username,
        },
        "settings": _serialize_settings(settings_row, fallback_language=user.language or "uk"),
        "categories": categories,
        "supported_languages": sorted(CATEGORIES.keys()),
    }


@router.get("/api/webapp/categories")
async def webapp_categories(
    language: str | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(
        language if language is not None else (settings_row.interface_language or user.language or "uk"),
        fallback=settings_row.interface_language or user.language or "uk",
    )

    payload = []
    for category in get_categories_for_lang(lang):
        payload.append({
            "category": category,
            "subcategories": get_subcategories_for_category(category, lang),
        })

    return {"language": lang, "items": payload}


@router.get("/api/webapp/dashboard")
async def webapp_dashboard(
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

    agg = AggregationService(session, auth_user.telegram_id)
    current_filter = RecordFilter(date_from=start, date_to=end)
    previous_filter = RecordFilter(date_from=prev_start, date_to=prev_end)

    totals = await agg.totals(current_filter)
    previous_totals = await agg.totals(previous_filter)

    income_delta = await _recurring_income_delta_for_period(
        session,
        user_id=user.id,
        period_start=start,
        period_end=end,
        period=period_for_recurring,
    )
    if income_delta:
        totals["incomes"] = Decimal(totals["incomes"]) + income_delta
        totals["balance"] = Decimal(totals["balance"]) + income_delta

    prev_income_delta = await _recurring_income_delta_for_period(
        session,
        user_id=user.id,
        period_start=prev_start,
        period_end=prev_end,
        period=period_for_recurring,
    )
    if prev_income_delta:
        previous_totals["incomes"] = Decimal(previous_totals["incomes"]) + prev_income_delta
        previous_totals["balance"] = Decimal(previous_totals["balance"]) + prev_income_delta
    by_category = await agg.sum_by_category(current_filter)
    localized_categories = _localize_category_amounts(
        [(item.label, item.amount) for item in by_category],
        language=lang,
    )

    total_expense = sum((amount for _, amount in localized_categories), Decimal("0"))
    category_items = []
    for label, amount in localized_categories:
        percent = float((amount / total_expense * 100) if total_expense else 0)
        category_items.append(
            {
                "category": label,
                "amount": _to_float(amount),
                "percent": round(percent, 2),
            }
        )

    trend_stmt = (
        select(
            Record.happened_on,
            Record.type,
            func.coalesce(func.sum(Record.amount), 0).label("total"),
        )
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == auth_user.telegram_id,
            Record.happened_on >= start,
            Record.happened_on <= end,
        )
        .group_by(Record.happened_on, Record.type)
        .order_by(Record.happened_on.asc())
    )
    trend_rows = await session.execute(trend_stmt)

    trend_by_day: dict[date, dict[str, Decimal]] = defaultdict(
        lambda: {"income": Decimal("0"), "expense": Decimal("0")}
    )
    for happened_on, record_type, total in trend_rows.all():
        key = "expense" if record_type == RecordType.EXPENSE else "income"
        trend_by_day[happened_on][key] = Decimal(total or 0)

    trend = [
        {
            "date": day.isoformat(),
            "income": _to_float(values["income"]),
            "expense": _to_float(values["expense"]),
        }
        for day, values in sorted(trend_by_day.items(), key=lambda item: item[0])
    ]

    record_service = RecordService(session, auth_user.telegram_id)
    recent = await record_service.list(current_filter, limit=10, offset=0)

    heatmap_start = end - timedelta(days=90)
    heatmap_stmt = (
        select(
            Record.happened_on,
            func.coalesce(func.sum(Record.amount), 0).label("total"),
        )
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == auth_user.telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= heatmap_start,
            Record.happened_on <= end,
        )
        .group_by(Record.happened_on)
        .order_by(Record.happened_on.asc())
    )
    heatmap_rows = await session.execute(heatmap_stmt)
    heatmap = [
        {"date": day.isoformat(), "total": _to_float(Decimal(total or 0))}
        for day, total in heatmap_rows.all()
    ]

    budget = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start=start,
        period_end=end,
        language=lang,
    )

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "totals": {
            "incomes": _to_float(Decimal(totals["incomes"])),
            "expenses": _to_float(Decimal(totals["expenses"])),
            "balance": _to_float(Decimal(totals["balance"])),
            "remaining": _to_float(Decimal(totals["balance"])),
        },
        "comparison": {
            "income_pct": _pct_change(Decimal(totals["incomes"]), Decimal(previous_totals["incomes"])),
            "expense_pct": _pct_change(Decimal(totals["expenses"]), Decimal(previous_totals["expenses"])),
            "balance_pct": _pct_change(Decimal(totals["balance"]), Decimal(previous_totals["balance"])),
        },
        "categories": category_items,
        "trend": trend,
        "recent_operations": [_serialize_record(record, language=lang) for record in recent],
        "heatmap": heatmap,
        "budget": budget,
        "currency": settings_row.currency,
    }


