from __future__ import annotations

import csv
import io
import json
import logging
import unicodedata
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fpdf import FPDF
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import SimpleCache
from ..config import get_settings
from ..db import Base, engine, ensure_schema, get_session
from ..models import BudgetPlan, CategoryBudgetLimit, Record, RecordType, User, UserSettings
from ..repositories.users import UserRepository
from ..schemas import BudgetPlanCreate, RecordCreate, RecordFilter
from ..scripts.load_custom import CATEGORIES
from ..services.aggregation_service import AggregationService, clear_stats_cache
from ..services.record_service import RecordService
from .auth import TelegramAuthError, TelegramWebUser, validate_init_data

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema()
    yield


app = FastAPI(
    title="Telegram Finance Web App",
    version="1.0.0",
    lifespan=_lifespan,
)
app.mount("/webapp/assets", StaticFiles(directory=STATIC_DIR), name="webapp-assets")

_auth_cache = SimpleCache(ttl_seconds=settings.webapp_init_data_ttl_seconds)


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
    limit_amount: Decimal = Field(ge=0)


class CategoryLimitBatchIn(BaseModel):
    period_start: date
    period_end: date
    limits: list[CategoryLimitIn]


class SettingsUpdateIn(BaseModel):
    theme: str | None = None
    currency: str | None = None
    interface_language: str | None = None
    week_starts_on: str | None = None
    notifications_enabled: bool | None = None
    hidden_blocks: list[str] | None = None
    pinned_filters: list[str] | None = None
    favorite_categories: list[str] | None = None


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/webapp", status_code=307)


@app.get("/webapp", include_in_schema=False)
async def webapp_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/webapp/", include_in_schema=False)
async def webapp_index_slash():
    return FileResponse(STATIC_DIR / "index.html")


async def _db_session():
    async with get_session() as session:
        yield session


def _to_float(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _to_ascii(value: str | None) -> str:
    if not value:
        return "-"
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return ascii_value or "-"


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _serialize_record(record: Record) -> dict:
    return {
        "id": record.id,
        "type": record.type.value,
        "category": record.category,
        "subcategory": record.subcategory,
        "amount": _to_float(record.amount),
        "currency": record.currency,
        "happened_on": record.happened_on.isoformat(),
        "description": record.description,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _serialize_settings(settings_row: UserSettings, fallback_language: str = "uk") -> dict:
    return {
        "theme": settings_row.theme or "dark",
        "currency": settings_row.currency or "UAH",
        "interface_language": settings_row.interface_language or fallback_language,
        "week_starts_on": settings_row.week_starts_on or "monday",
        "notifications_enabled": bool(settings_row.notifications_enabled),
        "hidden_blocks": _json_list(settings_row.hidden_blocks),
        "pinned_filters": _json_list(settings_row.pinned_filters),
        "favorite_categories": _json_list(settings_row.favorite_categories),
    }


def _date_bounds(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    if date_from and date_to:
        if date_from > date_to:
            raise HTTPException(status_code=400, detail="date_from must be <= date_to")
        return date_from, date_to

    today = date.today()
    normalized = (period or "30d").lower()

    if normalized == "today":
        return today, today
    if normalized in {"week", "7d"}:
        return today - timedelta(days=6), today
    if normalized in {"month", "30d"}:
        return today - timedelta(days=29), today
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


async def _get_auth_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    init_data: str | None = Query(default=None, alias="initData"),
) -> TelegramWebUser:
    payload = x_telegram_init_data or init_data

    if not payload:
        if settings.webapp_dev_telegram_id:
            return TelegramWebUser(
                telegram_id=settings.webapp_dev_telegram_id,
                first_name="Dev",
                username="local-dev",
            )
        raise HTTPException(status_code=401, detail="Telegram initData is required")

    cache_key = sha256(payload.encode("utf-8")).hexdigest()
    cached = _auth_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        verified = validate_init_data(
            payload,
            settings.bot_token,
            max_age_seconds=settings.webapp_init_data_ttl_seconds,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _auth_cache.set(cache_key, verified)
    return verified


async def _get_or_create_user(session: AsyncSession, auth_user: TelegramWebUser) -> User:
    user_repo = UserRepository(session)
    language = (auth_user.language_code or "uk").lower()
    user = await user_repo.get_or_create(auth_user.telegram_id, language=language)
    return user


async def _get_or_create_settings(session: AsyncSession, user: User) -> UserSettings:
    existing = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    settings_row = existing.scalars().first()
    if settings_row:
        return settings_row

    settings_row = UserSettings(
        user_id=user.id,
        interface_language=(user.language or "uk").lower(),
    )
    session.add(settings_row)
    await session.flush()
    return settings_row


async def _category_spend(
    session: AsyncSession,
    telegram_id: int,
    period_start: date,
    period_end: date,
) -> dict[str, Decimal]:
    stmt = (
        select(Record.category, func.coalesce(func.sum(Record.amount), 0))
        .join(User, Record.user_id == User.id)
        .where(
            User.telegram_id == telegram_id,
            Record.type == RecordType.EXPENSE,
            Record.happened_on >= period_start,
            Record.happened_on <= period_end,
        )
        .group_by(Record.category)
    )
    rows = await session.execute(stmt)
    return {category: Decimal(total or 0) for category, total in rows.all()}


async def _budget_snapshot(
    session: AsyncSession,
    telegram_id: int,
    user_id: int,
    period_start: date,
    period_end: date,
) -> dict:
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

    category_spend = await _category_spend(session, telegram_id, period_start, period_end)

    limit_rows = await session.execute(
        select(CategoryBudgetLimit)
        .where(
            CategoryBudgetLimit.user_id == user_id,
            CategoryBudgetLimit.period_start == period_start,
            CategoryBudgetLimit.period_end == period_end,
        )
        .order_by(CategoryBudgetLimit.category.asc())
    )
    limits = []
    alerts = []

    for row in limit_rows.scalars().all():
        spent_cat = category_spend.get(row.category, Decimal("0"))
        remaining = Decimal(row.limit_amount) - spent_cat
        used_percent = float((spent_cat / row.limit_amount * 100) if row.limit_amount else 0)

        if used_percent > 100:
            status = "exceeded"
        elif used_percent >= 80:
            status = "near_limit"
        else:
            status = "normal"

        payload = {
            "id": row.id,
            "category": row.category,
            "limit": _to_float(Decimal(row.limit_amount)),
            "spent": _to_float(spent_cat),
            "remaining": _to_float(remaining),
            "used_percent": round(used_percent, 2),
            "status": status,
        }
        limits.append(payload)
        if status != "normal":
            alerts.append(payload)

    if plan:
        planned_expense = Decimal(plan.planned_expense)
        month_remaining = planned_expense - spent
        month_used = float((spent / planned_expense * 100) if planned_expense else 0)
    else:
        planned_expense = Decimal("0")
        month_remaining = Decimal("0")
        month_used = 0.0

    if month_used > 100:
        month_status = "exceeded"
    elif month_used >= 80:
        month_status = "near_limit"
    else:
        month_status = "normal"

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "monthly_plan": {
            "id": plan.id if plan else None,
            "planned_expense": _to_float(Decimal(plan.planned_expense)) if plan else None,
            "planned_income": _to_float(Decimal(plan.planned_income)) if plan else None,
            "spent": _to_float(spent),
            "remaining": _to_float(month_remaining),
            "used_percent": round(month_used, 2),
            "status": month_status,
        },
        "category_limits": limits,
        "alerts": alerts,
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
) -> list[str]:
    tips: list[str] = []
    if expense_by_category:
        top = max(expense_by_category, key=lambda item: item["amount"])
        if top["percent"] >= 40:
            tips.append(
                f"Category '{top['category']}' consumes {top['percent']:.1f}% of expenses. Consider setting a stricter limit."
            )

    if balance < 0:
        tips.append("Your selected period balance is negative. Try reducing non-essential spending.")

    if month_budget and month_budget.get("status") in {"near_limit", "exceeded"}:
        tips.append("Monthly budget is close to limit. Shift discretionary spend to next period.")

    if not tips:
        tips.append("Spending profile looks stable. Keep tracking to improve forecast accuracy.")

    return tips


@app.get("/api/webapp/health")
async def webapp_health():
    return {"ok": True, "service": "webapp"}


@app.get("/api/webapp/bootstrap")
async def webapp_bootstrap(
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    await session.commit()

    lang = (settings_row.interface_language or user.language or "uk").lower()
    categories = list(CATEGORIES.get(lang, {}).keys())

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


@app.get("/api/webapp/categories")
async def webapp_categories(
    language: str | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    lang = (language or user.language or "uk").lower()
    if lang not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Unsupported language")

    payload = []
    for category, subcategories in CATEGORIES[lang].items():
        payload.append({
            "category": category,
            "subcategories": list(subcategories),
        })

    return {"language": lang, "items": payload}


@app.get("/api/webapp/dashboard")
async def webapp_dashboard(
    period: str = Query(default="30d"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)
    prev_start, prev_end = _prev_bounds(start, end)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)

    agg = AggregationService(session, auth_user.telegram_id)
    current_filter = RecordFilter(date_from=start, date_to=end)
    previous_filter = RecordFilter(date_from=prev_start, date_to=prev_end)

    totals = await agg.totals(current_filter)
    previous_totals = await agg.totals(previous_filter)
    by_category = await agg.sum_by_category(current_filter)

    total_expense = sum((item.amount for item in by_category), Decimal("0"))
    category_items = []
    for item in by_category:
        percent = float((item.amount / total_expense * 100) if total_expense else 0)
        category_items.append(
            {
                "category": item.label,
                "amount": _to_float(item.amount),
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
        period_start=start.replace(day=1),
        period_end=end,
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
        "recent_operations": [_serialize_record(record) for record in recent],
        "heatmap": heatmap,
        "budget": budget,
        "currency": settings_row.currency,
    }


@app.get("/api/webapp/records")
async def webapp_records(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    categories: list[str] | None = Query(default=None),
    record_type: str | None = Query(default=None, alias="type"),
    min_amount: str | None = Query(default=None),
    max_amount: str | None = Query(default=None),
    query: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    filters = _build_filters(
        date_from,
        date_to,
        categories,
        record_type,
        min_amount,
        max_amount,
        query,
    )

    service = RecordService(session, auth_user.telegram_id)
    records = await service.list(filters, limit=limit, offset=offset)
    total = await service.count(filters)

    items = [_serialize_record(record) for record in records]
    grouped = defaultdict(list)
    for item in items:
        grouped[item["happened_on"]].append(item)

    grouped_items = [
        {"date": key, "items": value}
        for key, value in sorted(grouped.items(), key=lambda pair: pair[0], reverse=True)
    ]

    return {
        "items": items,
        "grouped": grouped_items,
        "paging": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(items)) < total,
        },
    }


@app.patch("/api/webapp/records/{record_id}")
async def webapp_update_record(
    record_id: int,
    payload: RecordUpdateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    service = RecordService(session, auth_user.telegram_id)
    current = await service.get(record_id)
    if not current:
        raise HTTPException(status_code=404, detail="Record not found")

    record_type = payload.type or current.type.value
    if record_type not in {"income", "expense"}:
        raise HTTPException(status_code=400, detail="type must be income or expense")

    updated = RecordCreate(
        type=record_type,
        category=payload.category or current.category,
        subcategory=payload.subcategory if payload.subcategory is not None else current.subcategory,
        amount=payload.amount if payload.amount is not None else current.amount,
        currency=payload.currency or current.currency,
        happened_on=payload.happened_on or current.happened_on,
        description=payload.description if payload.description is not None else current.description,
    )

    record = await service.update(record_id, updated)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    await session.commit()
    clear_stats_cache()
    return {"item": _serialize_record(record)}


@app.delete("/api/webapp/records/{record_id}")
async def webapp_delete_record(
    record_id: int,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    service = RecordService(session, auth_user.telegram_id)
    ok = await service.delete(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Record not found")

    await session.commit()
    clear_stats_cache()
    return {"ok": True}


@app.get("/api/webapp/analytics")
async def webapp_analytics(
    period: str = Query(default="30d"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)
    prev_start, prev_end = _prev_bounds(start, end)

    agg = AggregationService(session, auth_user.telegram_id)

    selected_filter = RecordFilter(date_from=start, date_to=end)
    selected_totals = await agg.totals(selected_filter)
    previous_totals = await agg.totals(RecordFilter(date_from=prev_start, date_to=prev_end))

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    day_totals = await agg.totals(RecordFilter(date_from=today, date_to=today))
    week_totals = await agg.totals(RecordFilter(date_from=week_start, date_to=today))
    month_totals = await agg.totals(RecordFilter(date_from=month_start, date_to=today))

    avg_expense = await agg.averages(selected_filter)
    max_expense = await agg.max_expense(selected_filter)
    by_category = await agg.sum_by_category(selected_filter)

    total_expense = sum((row.amount for row in by_category), Decimal("0"))
    distribution = []
    for row in by_category:
        percent = float((row.amount / total_expense * 100) if total_expense else 0)
        distribution.append(
            {
                "category": row.label,
                "amount": _to_float(row.amount),
                "percent": round(percent, 2),
            }
        )

    current_month_start = end.replace(day=1)
    monthly_points = []
    for offset in range(-5, 1):
        point_start = _month_shift(current_month_start, offset)
        point_end = _month_shift(point_start, 1) - timedelta(days=1)
        point_totals = await agg.totals(RecordFilter(date_from=point_start, date_to=point_end))
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

    user = await _get_or_create_user(session, auth_user)
    budget = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start=current_month_start,
        period_end=end,
    )

    month_budget = budget.get("monthly_plan")
    tips = _recommendations(
        distribution,
        Decimal(selected_totals["balance"]),
        month_budget if isinstance(month_budget, dict) else None,
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
        "avg_expense": _to_float(avg_expense),
        "max_expense": _to_float(max_expense),
        "distribution": distribution,
        "comparison": {
            "expenses_pct": _pct_change(Decimal(selected_totals["expenses"]), Decimal(previous_totals["expenses"])),
            "incomes_pct": _pct_change(Decimal(selected_totals["incomes"]), Decimal(previous_totals["incomes"])),
            "balance_pct": _pct_change(Decimal(selected_totals["balance"]), Decimal(previous_totals["balance"])),
        },
        "monthly_comparison": monthly_points,
        "forecast_next_month_expense": forecast_next_month,
        "budget": budget,
        "recommendations": tips,
    }


@app.get("/api/webapp/budget")
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
    snapshot = await _budget_snapshot(session, auth_user.telegram_id, user.id, period_start, period_end)
    return snapshot


@app.put("/api/webapp/budget/month")
async def webapp_budget_month_update(
    payload: MonthBudgetIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    agg = AggregationService(session, auth_user.telegram_id)
    plan = BudgetPlanCreate(
        period_start=payload.period_start,
        period_end=payload.period_end,
        planned_expense=payload.planned_expense,
        planned_income=payload.planned_income,
    )

    saved = await agg.save_budget(plan)
    await session.commit()
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


@app.put("/api/webapp/budget/category-limits")
async def webapp_category_limits_update(
    payload: CategoryLimitBatchIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    user = await _get_or_create_user(session, auth_user)

    await session.execute(
        delete(CategoryBudgetLimit).where(
            CategoryBudgetLimit.user_id == user.id,
            CategoryBudgetLimit.period_start == payload.period_start,
            CategoryBudgetLimit.period_end == payload.period_end,
        )
    )

    for item in payload.limits:
        row = CategoryBudgetLimit(
            user_id=user.id,
            category=item.category,
            period_start=payload.period_start,
            period_end=payload.period_end,
            limit_amount=item.limit_amount,
        )
        session.add(row)

    await session.commit()

    snapshot = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        payload.period_start,
        payload.period_end,
    )
    return snapshot


@app.get("/api/webapp/settings")
async def webapp_get_settings(
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    await session.commit()
    return _serialize_settings(settings_row, fallback_language=user.language or "uk")


@app.put("/api/webapp/settings")
async def webapp_update_settings(
    payload: SettingsUpdateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)

    if payload.theme is not None:
        settings_row.theme = payload.theme
    if payload.currency is not None:
        settings_row.currency = payload.currency
    if payload.interface_language is not None:
        settings_row.interface_language = payload.interface_language
    if payload.week_starts_on is not None:
        settings_row.week_starts_on = payload.week_starts_on
    if payload.notifications_enabled is not None:
        settings_row.notifications_enabled = payload.notifications_enabled
    if payload.hidden_blocks is not None:
        settings_row.hidden_blocks = json.dumps(payload.hidden_blocks)
    if payload.pinned_filters is not None:
        settings_row.pinned_filters = json.dumps(payload.pinned_filters)
    if payload.favorite_categories is not None:
        settings_row.favorite_categories = json.dumps(payload.favorite_categories)

    await session.commit()

    return _serialize_settings(settings_row, fallback_language=user.language or "uk")


@app.get("/api/webapp/export/csv")
async def webapp_export_csv(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    categories: list[str] | None = Query(default=None),
    record_type: str | None = Query(default=None, alias="type"),
    min_amount: str | None = Query(default=None),
    max_amount: str | None = Query(default=None),
    query: str | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    filters = _build_filters(
        date_from,
        date_to,
        categories,
        record_type,
        min_amount,
        max_amount,
        query,
    )

    service = RecordService(session, auth_user.telegram_id)
    records = await service.list(filters=filters, limit=5000, offset=0)

    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "date", "type", "category", "subcategory", "amount", "currency", "description"])
    for record in records:
        writer.writerow(
            [
                record.id,
                record.happened_on.isoformat(),
                record.type.value,
                record.category,
                record.subcategory or "",
                f"{record.amount:.2f}",
                record.currency,
                record.description or "",
            ]
        )

    output = io.BytesIO(stream.getvalue().encode("utf-8"))
    headers = {"Content-Disposition": "attachment; filename=finance-report.csv"}
    return StreamingResponse(output, media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/webapp/export/pdf")
async def webapp_export_pdf(
    period: str = Query(default="30d"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)

    service = RecordService(session, auth_user.telegram_id)
    filters = RecordFilter(date_from=start, date_to=end)
    records = await service.list(filters=filters, limit=120, offset=0)

    agg = AggregationService(session, auth_user.telegram_id)
    totals = await agg.totals(filters)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Finance Report", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Period: {start.isoformat()} - {end.isoformat()}", ln=True)
    pdf.cell(0, 8, f"Income: {_to_float(Decimal(totals['incomes'])):.2f}", ln=True)
    pdf.cell(0, 8, f"Expense: {_to_float(Decimal(totals['expenses'])):.2f}", ln=True)
    pdf.cell(0, 8, f"Balance: {_to_float(Decimal(totals['balance'])):.2f}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(26, 8, "Date", border=1)
    pdf.cell(20, 8, "Type", border=1)
    pdf.cell(45, 8, "Category", border=1)
    pdf.cell(24, 8, "Amount", border=1)
    pdf.cell(22, 8, "Curr", border=1)
    pdf.cell(53, 8, "Description", border=1, ln=True)

    pdf.set_font("Helvetica", "", 9)
    for record in records:
        category_label = record.category
        if record.subcategory:
            category_label = f"{category_label} ({record.subcategory})"

        pdf.cell(26, 7, _to_ascii(record.happened_on.isoformat())[:10], border=1)
        pdf.cell(20, 7, _to_ascii(record.type.value)[:12], border=1)
        pdf.cell(45, 7, _to_ascii(category_label)[:28], border=1)
        pdf.cell(24, 7, f"{_to_float(record.amount):.2f}", border=1)
        pdf.cell(22, 7, _to_ascii(record.currency)[:8], border=1)
        pdf.cell(53, 7, _to_ascii(record.description)[:36], border=1, ln=True)

    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        content = raw.encode("latin-1", errors="ignore")
    else:
        content = bytes(raw)

    headers = {"Content-Disposition": "attachment; filename=finance-report.pdf"}
    return Response(content=content, media_type="application/pdf", headers=headers)


@app.get("/api/webapp/recommendations")
async def webapp_recommendations(
    period: str = Query(default="30d"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)
    agg = AggregationService(session, auth_user.telegram_id)

    totals = await agg.totals(RecordFilter(date_from=start, date_to=end))
    by_category = await agg.sum_by_category(RecordFilter(date_from=start, date_to=end))

    expense_total = sum((item.amount for item in by_category), Decimal("0"))
    distribution = []
    for item in by_category:
        percent = float((item.amount / expense_total * 100) if expense_total else 0)
        distribution.append({
            "category": item.label,
            "amount": _to_float(item.amount),
            "percent": round(percent, 2),
        })

    user = await _get_or_create_user(session, auth_user)
    budget = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start=start.replace(day=1),
        period_end=end,
    )

    suggestions = _recommendations(
        distribution,
        Decimal(totals["balance"]),
        budget.get("monthly_plan") if isinstance(budget.get("monthly_plan"), dict) else None,
    )
    return {"items": suggestions}
