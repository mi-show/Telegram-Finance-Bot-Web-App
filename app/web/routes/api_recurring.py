from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_models import (
    RecurringCreateIn,
    RecurringUpdateIn,
)
from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    Decimal,
    RecordCreate,
    RecordService,
    RecordType,
    RecurringEntry,
    _auto_apply_recurring_for_current_month,
    _due_date_for_period,
    _get_recurring_entry,
    _learn_from_description,
    _record_audit_payload,
    _safe_lang,
    _serialize_record,
    _serialize_recurring_entry,
    _to_float,
    _write_audit,
    canonicalize_category,
    clear_limit_series_cache,
    clear_stats_cache,
    clear_user_currency_conversion_anchors,
    date,
    datetime,
    select,
)

router = APIRouter()

_INCOME_DEFAULT_CATEGORY = "Salary"
_INCOME_DEFAULT_SUBCATEGORY = "Main"


def _normalize_recurring_for_create(*, entry_type: RecordType, category: str | None, subcategory: str | None) -> tuple[str, str | None]:
    if entry_type == RecordType.INCOME:
        normalized_subcategory = (subcategory or "").strip() or _INCOME_DEFAULT_SUBCATEGORY
        return _INCOME_DEFAULT_CATEGORY, normalized_subcategory

    normalized_category = (category or "").strip()
    if not normalized_category:
        raise HTTPException(status_code=400, detail="category is required for expense recurring")

    normalized_subcategory = (subcategory or "").strip() or None
    return canonicalize_category(normalized_category) or normalized_category, normalized_subcategory


def _recurring_entry_audit_payload(row: RecurringEntry) -> dict[str, object]:
    return {
        "id": row.id,
        "title": row.title,
        "type": row.type.value,
        "category": row.category,
        "subcategory": row.subcategory,
        "amount": _to_float(row.amount),
        "currency": row.currency,
        "day_of_month": row.day_of_month,
        "reminder_days_before": row.reminder_days_before,
        "is_active": bool(row.is_active),
        "last_confirmed_period": row.last_confirmed_period.isoformat() if row.last_confirmed_period else None,
        "last_confirmed_at": row.last_confirmed_at.isoformat() if row.last_confirmed_at else None,
    }


@router.get("/api/webapp/recurring")
async def webapp_list_recurring(
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

    period_start = date(target_year, target_month, 1)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    stmt = select(RecurringEntry).where(RecurringEntry.user_id == user.id).order_by(RecurringEntry.id.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            _serialize_recurring_entry(
                row,
                language=lang,
                period_start=period_start,
                today=today,
            )
            for row in rows
        ],
        "total": len(rows),
    }


@router.post("/api/webapp/recurring")
async def webapp_create_recurring(
    payload: RecurringCreateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    today = date.today()
    period_start = today.replace(day=1)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    entry_type = RecordType(payload.type)
    category, subcategory = _normalize_recurring_for_create(
        entry_type=entry_type,
        category=payload.category,
        subcategory=payload.subcategory,
    )

    row = RecurringEntry(
        user_id=user.id,
        type=entry_type,
        category=category,
        subcategory=subcategory,
        amount=Decimal(payload.amount),
        currency=(payload.currency or settings_row.currency or "UAH").upper(),
        title=payload.title,
        day_of_month=payload.day_of_month,
        reminder_days_before=payload.reminder_days_before,
        is_active=payload.is_active,
    )
    session.add(row)
    await session.flush()

    await _write_audit(
        session,
        user_id=user.id,
        action="recurring.create",
        entity_type="recurring_entry",
        entity_id=row.id,
        before=None,
        after=_recurring_entry_audit_payload(row),
    )

    await session.commit()
    await session.refresh(row)
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    return {
        "item": _serialize_recurring_entry(
            row,
            language=lang,
            period_start=period_start,
            today=today,
        )
    }


@router.patch("/api/webapp/recurring/{recurring_id}")
async def webapp_update_recurring(
    recurring_id: int,
    payload: RecurringUpdateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    today = date.today()
    period_start = today.replace(day=1)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    row = await _get_recurring_entry(
        session,
        user_id=user.id,
        recurring_id=recurring_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recurring entry not found")

    before_payload = _recurring_entry_audit_payload(row)

    previous_type = row.type
    next_type = RecordType(payload.type) if payload.type is not None else row.type

    if payload.type is not None:
        row.type = next_type

    if next_type == RecordType.INCOME:
        row.category = _INCOME_DEFAULT_CATEGORY

        if payload.subcategory is not None:
            row.subcategory = payload.subcategory.strip() or _INCOME_DEFAULT_SUBCATEGORY
        elif not row.subcategory or previous_type != RecordType.INCOME:
            row.subcategory = _INCOME_DEFAULT_SUBCATEGORY
    else:
        if payload.category is not None:
            normalized_category = payload.category.strip()
            if not normalized_category:
                raise HTTPException(status_code=400, detail="category is required for expense recurring")
            row.category = canonicalize_category(normalized_category) or normalized_category
        elif previous_type != RecordType.EXPENSE:
            raise HTTPException(status_code=400, detail="category is required when switching recurring to expense")

        if payload.subcategory is not None:
            row.subcategory = payload.subcategory.strip() or None
        elif previous_type != RecordType.EXPENSE:
            row.subcategory = None

    if payload.amount is not None:
        row.amount = Decimal(payload.amount)
    if payload.currency is not None:
        row.currency = payload.currency.upper()
    if payload.title is not None:
        row.title = payload.title
    if payload.day_of_month is not None:
        row.day_of_month = payload.day_of_month
    if payload.reminder_days_before is not None:
        row.reminder_days_before = payload.reminder_days_before
    if payload.is_active is not None:
        row.is_active = payload.is_active

    await _write_audit(
        session,
        user_id=user.id,
        action="recurring.update",
        entity_type="recurring_entry",
        entity_id=row.id,
        before=before_payload,
        after=_recurring_entry_audit_payload(row),
    )

    await session.commit()
    await session.refresh(row)
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    return {
        "item": _serialize_recurring_entry(
            row,
            language=lang,
            period_start=period_start,
            today=today,
        )
    }


@router.delete("/api/webapp/recurring/{recurring_id}")
async def webapp_delete_recurring(
    recurring_id: int,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    row = await _get_recurring_entry(
        session,
        user_id=user.id,
        recurring_id=recurring_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recurring entry not found")

    before_payload = _recurring_entry_audit_payload(row)
    await session.delete(row)

    await _write_audit(
        session,
        user_id=user.id,
        action="recurring.delete",
        entity_type="recurring_entry",
        entity_id=recurring_id,
        before=before_payload,
        after=None,
    )

    await session.commit()
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    return {"ok": True}


@router.post("/api/webapp/recurring/{recurring_id}/confirm")
async def webapp_confirm_recurring(
    recurring_id: int,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    today = date.today()
    period_start = today.replace(day=1)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    row = await _get_recurring_entry(
        session,
        user_id=user.id,
        recurring_id=recurring_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recurring entry not found")

    if row.last_confirmed_period == period_start:
        return {
            "item": _serialize_recurring_entry(
                row,
                language=lang,
                period_start=period_start,
                today=today,
            )
        }

    happened_on = _due_date_for_period(period_start, row.day_of_month)
    description = (row.title or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    record_payload = RecordCreate(
        type=row.type.value,
        category=row.category,
        subcategory=row.subcategory,
        amount=Decimal(row.amount),
        currency=(row.currency or settings_row.currency or "UAH").upper(),
        happened_on=happened_on,
        description=description,
    )

    service = RecordService(session, auth_user.telegram_id)
    try:
        record = await service.add(record_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    before_period = row.last_confirmed_period
    before_confirmed_at = row.last_confirmed_at
    before_confirm = {
        "last_confirmed_period": before_period.isoformat() if before_period is not None else None,
        "last_confirmed_at": before_confirmed_at.isoformat() if before_confirmed_at is not None else None,
    }
    row.last_confirmed_period = period_start
    row.last_confirmed_at = datetime.utcnow()

    after_period = row.last_confirmed_period
    after_confirmed_at = row.last_confirmed_at
    after_confirm = {
        "last_confirmed_period": after_period.isoformat() if after_period is not None else None,
        "last_confirmed_at": after_confirmed_at.isoformat() if after_confirmed_at is not None else None,
    }

    await _write_audit(
        session,
        user_id=user.id,
        action="recurring.confirm",
        entity_type="recurring_entry",
        entity_id=row.id,
        before=before_confirm,
        after=after_confirm,
    )
    await _write_audit(
        session,
        user_id=user.id,
        action="record.create",
        entity_type="record",
        entity_id=record.id,
        before=None,
        after=_record_audit_payload(record),
    )

    await _learn_from_description(
        session,
        user_id=user.id,
        description=record.description,
        category=record.category,
        subcategory=record.subcategory,
    )

    await session.commit()
    await session.refresh(row)
    await session.refresh(record)
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    clear_limit_series_cache()

    return {
        "item": _serialize_recurring_entry(
            row,
            language=lang,
            period_start=period_start,
            today=today,
        ),
        "record": _serialize_record(record, language=lang),
    }


