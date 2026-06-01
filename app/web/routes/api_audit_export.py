from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    AUDIT_DEFAULT_ACTIONS,
    AggregationService,
    AuditLog,
    Decimal,
    FPDF,
    RecordFilter,
    RecordService,
    XPos,
    YPos,
    _budget_snapshot,
    _build_filters,
    _date_bounds,
    _localize_category_amounts,
    _recommendations,
    _safe_lang,
    _serialize_audit_item,
    _to_ascii,
    _to_float,
    csv,
    date,
    expand_category_aliases,
    func,
    io,
    localize_category,
    select,
)

router = APIRouter()


@router.get("/api/webapp/audit")
async def webapp_audit_trail(
    action: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    user = await _get_or_create_user(session, auth_user)

    def _apply_audit_filters(stmt):
        filtered = stmt.where(AuditLog.user_id == user.id)
        if action and action != "all":
            filtered = filtered.where(AuditLog.action == action)
        if date_from is not None:
            filtered = filtered.where(func.date(AuditLog.created_at) >= date_from)
        if date_to is not None:
            filtered = filtered.where(func.date(AuditLog.created_at) <= date_to)
        return filtered

    total_query = await session.execute(_apply_audit_filters(select(func.count(AuditLog.id))))
    total = int(total_query.scalar_one() or 0)

    rows_query = await session.execute(
        _apply_audit_filters(select(AuditLog))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = rows_query.scalars().all()

    actions_query = await session.execute(
        select(AuditLog.action)
        .where(AuditLog.user_id == user.id)
        .group_by(AuditLog.action)
        .order_by(AuditLog.action.asc())
    )
    existing_actions = [str(value) for (value,) in actions_query.all() if value]
    available_actions = [item for item in AUDIT_DEFAULT_ACTIONS]
    for value in existing_actions:
        if value not in available_actions:
            available_actions.append(value)

    items = [_serialize_audit_item(row) for row in rows]
    return {
        "items": items,
        "available_actions": available_actions,
        "filters": {
            "action": action,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "paging": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(items)) < total,
        },
    }


@router.get("/api/webapp/export/csv")
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
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

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
                localize_category(record.category, lang) or record.category,
                record.subcategory or "",
                f"{record.amount:.2f}",
                record.currency,
                record.description or "",
            ]
        )

    output = io.BytesIO(stream.getvalue().encode("utf-8"))
    headers = {"Content-Disposition": "attachment; filename=finance-report.csv"}
    return StreamingResponse(output, media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/api/webapp/export/pdf")
async def webapp_export_pdf(
    period: str = Query(default="month"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)

    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    service = RecordService(session, auth_user.telegram_id)
    filters = RecordFilter(date_from=start, date_to=end)
    records = await service.list(filters=filters, limit=120, offset=0)

    agg = AggregationService(session, auth_user.telegram_id)
    totals = await agg.totals(filters)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Finance Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Period: {start.isoformat()} - {end.isoformat()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Income: {_to_float(Decimal(totals['incomes'])):.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Expense: {_to_float(Decimal(totals['expenses'])):.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Balance: {_to_float(Decimal(totals['balance'])):.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(26, 8, "Date", border=1)
    pdf.cell(20, 8, "Type", border=1)
    pdf.cell(45, 8, "Category", border=1)
    pdf.cell(24, 8, "Amount", border=1)
    pdf.cell(22, 8, "Curr", border=1)
    pdf.cell(53, 8, "Description", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 9)
    for record in records:
        category_label = localize_category(record.category, lang) or record.category
        if record.subcategory:
            category_label = f"{category_label} ({record.subcategory})"

        pdf.cell(26, 7, _to_ascii(record.happened_on.isoformat())[:10], border=1)
        pdf.cell(20, 7, _to_ascii(record.type.value)[:12], border=1)
        pdf.cell(45, 7, _to_ascii(category_label)[:28], border=1)
        pdf.cell(24, 7, f"{_to_float(record.amount):.2f}", border=1)
        pdf.cell(22, 7, _to_ascii(record.currency)[:8], border=1)
        pdf.cell(53, 7, _to_ascii(record.description)[:36], border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    raw = pdf.output()
    if isinstance(raw, str):
        content = raw.encode("latin-1", errors="ignore")
    else:
        content = bytes(raw)

    headers = {"Content-Disposition": "attachment; filename=finance-report.pdf"}
    return Response(content=content, media_type="application/pdf", headers=headers)


@router.get("/api/webapp/recommendations")
async def webapp_recommendations(
    period: str = Query(default="month"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    start, end = _date_bounds(period, date_from, date_to)
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    lang = _safe_lang(settings_row.interface_language or user.language or "uk")

    agg = AggregationService(session, auth_user.telegram_id)

    totals = await agg.totals(RecordFilter(date_from=start, date_to=end))
    by_category = await agg.sum_by_category(RecordFilter(date_from=start, date_to=end))

    localized_categories = _localize_category_amounts(
        [(item.label, item.amount) for item in by_category],
        language=lang,
    )

    expense_total = sum((amount for _, amount in localized_categories), Decimal("0"))
    distribution = []
    for label, amount in localized_categories:
        percent = float((amount / expense_total * 100) if expense_total else 0)
        distribution.append({
            "category": label,
            "amount": _to_float(amount),
            "percent": round(percent, 2),
        })

    budget = await _budget_snapshot(
        session,
        auth_user.telegram_id,
        user.id,
        period_start=start,
        period_end=end,
        language=lang,
    )

    suggestions = _recommendations(
        distribution,
        Decimal(totals["balance"]),
        budget.get("monthly_plan") if isinstance(budget.get("monthly_plan"), dict) else None,
        language=lang,
    )
    return {"items": suggestions}
