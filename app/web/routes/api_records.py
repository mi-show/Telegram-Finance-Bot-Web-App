from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_models import RecordUpdateIn
from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    Literal,
    Record,
    RecordCreate,
    RecordService,
    RecordType,
    User,
    _auto_apply_recurring_for_current_month,
    _build_filters,
    _learn_from_description,
    _record_audit_payload,
    _safe_lang,
    _serialize_record,
    _write_audit,
    canonicalize_category,
    cast,
    clear_limit_series_cache,
    clear_stats_cache,
    clear_user_currency_conversion_anchors,
    date,
    defaultdict,
    expand_category_aliases,
    func,
    localize_category,
    select,
)

router = APIRouter()


@router.get("/api/webapp/records")
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
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    await _auto_apply_recurring_for_current_month(
        session,
        telegram_id=auth_user.telegram_id,
        user_id=user.id,
        default_currency=(settings_row.currency or "UAH"),
    )

    filters = _build_filters(
        date_from,
        date_to,
        expand_category_aliases(categories),
        record_type,
        min_amount,
        max_amount,
        query,
    )

    service = RecordService(session, auth_user.telegram_id)
    records = await service.list(filters, limit=limit, offset=offset)
    total = await service.count(filters)

    items = [_serialize_record(record, language=lang) for record in records]
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


@router.get("/api/webapp/records/templates")
async def webapp_record_templates(
    limit: int = Query(default=8, ge=1, le=20),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    stmt = (
        select(
            Record.type,
            Record.category,
            Record.subcategory,
            func.max(Record.happened_on).label("last_used"),
            func.count(Record.id).label("usage_count"),
        )
        .join(User, Record.user_id == User.id)
        .where(User.telegram_id == auth_user.telegram_id)
        .group_by(Record.type, Record.category, Record.subcategory)
        .order_by(func.max(Record.happened_on).desc(), func.count(Record.id).desc())
        .limit(limit)
    )
    rows = await session.execute(stmt)

    items = []
    for record_type, category, subcategory, last_used, usage_count in rows.all():
        items.append(
            {
                "type": record_type.value if isinstance(record_type, RecordType) else str(record_type),
                "category": localize_category(category, lang) or category,
                "subcategory": subcategory,
                "last_used": last_used.isoformat() if last_used else None,
                "usage_count": int(usage_count or 0),
            }
        )

    return {"items": items}


@router.post("/api/webapp/records")
async def webapp_create_record(
    payload: RecordCreate,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    description = (payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    normalized = RecordCreate(
        type=payload.type,
        category=canonicalize_category(payload.category) or payload.category,
        subcategory=payload.subcategory,
        amount=payload.amount,
        currency=(payload.currency or settings_row.currency or "UAH").upper(),
        happened_on=payload.happened_on,
        description=description,
    )

    service = RecordService(session, auth_user.telegram_id)
    try:
        record = await service.add(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        description=description,
        category=record.category,
        subcategory=record.subcategory,
    )

    await session.commit()
    await session.refresh(record)
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    clear_limit_series_cache()
    return {"item": _serialize_record(record, language=lang)}


@router.patch("/api/webapp/records/{record_id}")
async def webapp_update_record(
    record_id: int,
    payload: RecordUpdateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    service = RecordService(session, auth_user.telegram_id)
    current = await service.get(record_id)
    if not current:
        raise HTTPException(status_code=404, detail="Record not found")
    before_payload = _record_audit_payload(current)

    record_type = payload.type or current.type.value
    if record_type not in {"income", "expense"}:
        raise HTTPException(status_code=400, detail="type must be income or expense")
    typed_record_type = cast(Literal["income", "expense"], record_type)

    selected_category = payload.category or current.category
    selected_currency = payload.currency or current.currency
    selected_description = (payload.description if payload.description is not None else current.description or "").strip()
    if not selected_description:
        raise HTTPException(status_code=400, detail="description is required")

    updated = RecordCreate(
        type=typed_record_type,
        category=canonicalize_category(selected_category) or selected_category,
        subcategory=payload.subcategory if payload.subcategory is not None else current.subcategory,
        amount=payload.amount if payload.amount is not None else current.amount,
        currency=selected_currency.upper(),
        happened_on=payload.happened_on or current.happened_on,
        description=selected_description,
    )

    record = await service.update(record_id, updated)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    await _write_audit(
        session,
        user_id=user.id,
        action="record.update",
        entity_type="record",
        entity_id=record.id,
        before=before_payload,
        after=_record_audit_payload(record),
    )

    await _learn_from_description(
        session,
        user_id=user.id,
        description=selected_description,
        category=record.category,
        subcategory=record.subcategory,
    )

    await session.commit()
    await session.refresh(record)
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    clear_limit_series_cache()
    return {"item": _serialize_record(record, language=lang)}


@router.delete("/api/webapp/records/{record_id}")
async def webapp_delete_record(
    record_id: int,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    service = RecordService(session, auth_user.telegram_id)
    existing = await service.get(record_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Record not found")

    ok = await service.delete(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Record not found")

    await _write_audit(
        session,
        user_id=user.id,
        action="record.delete",
        entity_type="record",
        entity_id=record_id,
        before=_record_audit_payload(existing),
        after=None,
    )

    await session.commit()
    clear_user_currency_conversion_anchors(session, user_id=user.id)
    clear_stats_cache()
    clear_limit_series_cache()
    return {"ok": True}
