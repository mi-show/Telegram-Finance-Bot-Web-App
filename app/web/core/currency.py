from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...cache import SimpleCache
from ...models import BudgetPlan, CategoryBudgetLimit, Record, RecurringEntry

logger = logging.getLogger(__name__)

SUPPORTED_CONVERSION_CURRENCIES = {"UAH", "USD", "EUR"}
CONVERSION_SCALE = Decimal("0.01")
FALLBACK_RATES_BY_USD = {
    "USD": Decimal("1.00"),
    "UAH": Decimal("40.00"),
    "EUR": Decimal("0.92"),
}
LIVE_FX_API_URL = "https://open.er-api.com/v6/latest/USD"

_fx_cache = SimpleCache(ttl_seconds=1800)
_anchor_cache = SimpleCache(ttl_seconds=86400)


def _anchor_cache_key(session: AsyncSession, user_id: int) -> str:
    bind = session.get_bind()
    bind_id = "default"
    if bind is not None:
        bind_url = getattr(bind, "url", None)
        if bind_url is not None:
            bind_id = str(bind_url)
    return f"currency_anchors:{bind_id}:{user_id}"


def _ensure_anchor_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict):
        payload.setdefault("records", {})
        payload.setdefault("budget_plans", {})
        payload.setdefault("category_limits", {})
        payload.setdefault("recurring", {})
        return payload

    return {
        "records": {},
        "budget_plans": {},
        "category_limits": {},
        "recurring": {},
    }


def _parse_decimal(value: Any, fallback: Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(fallback)


def _read_single_anchor(
    bucket: dict[str, Any],
    row_id: int,
    *,
    fallback_amount: Decimal,
    fallback_currency: str,
) -> tuple[Decimal, str]:
    key = str(row_id)
    row_anchor = bucket.get(key)
    if not isinstance(row_anchor, dict):
        bucket[key] = {
            "amount": str(fallback_amount),
            "currency": fallback_currency,
        }
        return Decimal(fallback_amount), fallback_currency

    anchor_currency = _normalize_currency_code(row_anchor.get("currency")) or fallback_currency
    anchor_amount = _parse_decimal(row_anchor.get("amount"), Decimal(fallback_amount))
    return anchor_amount, anchor_currency


def _read_budget_plan_anchor(
    bucket: dict[str, Any],
    row_id: int,
    *,
    fallback_expense: Decimal,
    fallback_income: Decimal,
    fallback_currency: str,
) -> tuple[Decimal, Decimal, str]:
    key = str(row_id)
    row_anchor = bucket.get(key)
    if not isinstance(row_anchor, dict):
        bucket[key] = {
            "planned_expense": str(fallback_expense),
            "planned_income": str(fallback_income),
            "currency": fallback_currency,
        }
        return Decimal(fallback_expense), Decimal(fallback_income), fallback_currency

    anchor_currency = _normalize_currency_code(row_anchor.get("currency")) or fallback_currency
    anchor_expense = _parse_decimal(row_anchor.get("planned_expense"), Decimal(fallback_expense))
    anchor_income = _parse_decimal(row_anchor.get("planned_income"), Decimal(fallback_income))
    return anchor_expense, anchor_income, anchor_currency


def clear_user_currency_conversion_anchors(session: AsyncSession, *, user_id: int) -> None:
    _anchor_cache.delete(_anchor_cache_key(session, user_id))


def _normalize_currency_code(currency: str | None) -> str | None:
    if not currency:
        return None
    normalized = currency.upper().strip()
    return normalized if normalized in SUPPORTED_CONVERSION_CURRENCIES else None


def _extract_live_rates(payload: dict) -> dict[str, Decimal] | None:
    raw_rates = payload.get("rates") if isinstance(payload, dict) else None
    if not isinstance(raw_rates, dict):
        return None

    parsed = {"USD": Decimal("1.00")}
    for currency in ("UAH", "EUR"):
        raw_value = raw_rates.get(currency)
        if raw_value is None:
            return None
        try:
            rate = Decimal(str(raw_value))
        except (InvalidOperation, ValueError):
            return None
        if rate <= 0:
            return None
        parsed[currency] = rate
    return parsed


async def _get_live_rates_by_usd() -> dict[str, Decimal]:
    cached = _fx_cache.get("rates_by_usd")
    if isinstance(cached, dict):
        return cached

    rates = dict(FALLBACK_RATES_BY_USD)
    try:

        def _fetch_payload() -> dict | None:
            with urlopen(LIVE_FX_API_URL, timeout=6) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8"))

        payload = await asyncio.to_thread(_fetch_payload)
        if isinstance(payload, dict):
            live_rates = _extract_live_rates(payload)
            if live_rates:
                rates = live_rates
    except Exception as exc:
        logger.warning("Failed to fetch live FX rates, using fallback values: %s", exc)

    _fx_cache.set("rates_by_usd", rates)
    return rates


def _convert_amount_with_rates(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    rates_by_usd: dict[str, Decimal],
) -> Decimal:
    source = _normalize_currency_code(from_currency)
    target = _normalize_currency_code(to_currency)
    if source is None or target is None:
        raise ValueError("Unsupported conversion pair")

    if source == target:
        return Decimal(amount).quantize(CONVERSION_SCALE)

    source_rate = rates_by_usd.get(source)
    target_rate = rates_by_usd.get(target)
    if source_rate is None or target_rate is None or source_rate <= 0 or target_rate <= 0:
        raise ValueError("Rates are unavailable for conversion")

    amount_in_usd = Decimal(amount) / source_rate
    converted = amount_in_usd * target_rate
    return converted.quantize(CONVERSION_SCALE)


async def _convert_user_amounts_to_currency(
    session: AsyncSession,
    *,
    user_id: int,
    from_currency: str,
    to_currency: str,
) -> None:
    source = _normalize_currency_code(from_currency)
    target = _normalize_currency_code(to_currency)
    if source is None or target is None or source == target:
        return

    rates = await _get_live_rates_by_usd()
    cache_key = _anchor_cache_key(session, user_id)
    anchors = _ensure_anchor_payload(_anchor_cache.get(cache_key))

    records_anchor = anchors["records"]
    plans_anchor = anchors["budget_plans"]
    limits_anchor = anchors["category_limits"]
    recurring_anchor = anchors["recurring"]

    records = await session.execute(select(Record).where(Record.user_id == user_id))
    for row in records.scalars().all():
        row_source = _normalize_currency_code(row.currency) or source
        anchor_amount, anchor_currency = _read_single_anchor(
            records_anchor,
            row.id,
            fallback_amount=Decimal(row.amount),
            fallback_currency=row_source,
        )
        row.amount = _convert_amount_with_rates(anchor_amount, anchor_currency, target, rates)
        row.currency = target

    plans = await session.execute(select(BudgetPlan).where(BudgetPlan.user_id == user_id))
    for row in plans.scalars().all():
        anchor_expense, anchor_income, anchor_currency = _read_budget_plan_anchor(
            plans_anchor,
            row.id,
            fallback_expense=Decimal(row.planned_expense),
            fallback_income=Decimal(row.planned_income),
            fallback_currency=source,
        )
        row.planned_expense = _convert_amount_with_rates(anchor_expense, anchor_currency, target, rates)
        row.planned_income = _convert_amount_with_rates(anchor_income, anchor_currency, target, rates)

    limits = await session.execute(select(CategoryBudgetLimit).where(CategoryBudgetLimit.user_id == user_id))
    for row in limits.scalars().all():
        anchor_amount, anchor_currency = _read_single_anchor(
            limits_anchor,
            row.id,
            fallback_amount=Decimal(row.limit_amount),
            fallback_currency=source,
        )
        row.limit_amount = _convert_amount_with_rates(anchor_amount, anchor_currency, target, rates)

    recurring = await session.execute(select(RecurringEntry).where(RecurringEntry.user_id == user_id))
    for row in recurring.scalars().all():
        row_source = _normalize_currency_code(row.currency) or source
        anchor_amount, anchor_currency = _read_single_anchor(
            recurring_anchor,
            row.id,
            fallback_amount=Decimal(row.amount),
            fallback_currency=row_source,
        )
        row.amount = _convert_amount_with_rates(anchor_amount, anchor_currency, target, rates)
        row.currency = target

    _anchor_cache.set(cache_key, anchors)
