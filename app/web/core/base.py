from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, Record, UserSettings
from ...scripts.load_custom import CATEGORIES
from ...services.category_service import canonicalize_category, localize_category, localize_subcategory

SETTING_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


def _normalize_setting_tokens(values: list[str], *, max_items: int = 32) -> list[str]:
    normalized: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token:
            continue
        if not SETTING_TOKEN_RE.fullmatch(token):
            continue
        if token in normalized:
            continue
        normalized.append(token)
        if len(normalized) >= max_items:
            break
    return normalized


def _serialize_record(record: Record, language: str | None = None) -> dict:
    category_label = record.category
    subcategory_label = record.subcategory
    if language:
        category_label = localize_category(record.category, language) or record.category
        if record.subcategory:
            subcategory_label = localize_subcategory(record.category, record.subcategory, language) or record.subcategory

    return {
        "id": record.id,
        "type": record.type.value,
        "category": category_label,
        "subcategory": subcategory_label,
        "amount": _to_float(record.amount),
        "currency": record.currency,
        "happened_on": record.happened_on.isoformat(),
        "description": record.description,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _record_audit_payload(record: Record) -> dict[str, Any]:
    return {
        "id": record.id,
        "type": record.type.value,
        "category": record.category,
        "subcategory": record.subcategory,
        "amount": _to_float(record.amount),
        "currency": record.currency,
        "happened_on": record.happened_on.isoformat(),
        "description": record.description,
    }


def _normalize_phrase(text_value: str | None) -> str | None:
    if not text_value:
        return None
    normalized = re.sub(r"\s+", " ", text_value.strip().lower())
    if len(normalized) < 2:
        return None
    return normalized[:128]


async def _learn_from_description(
    session: AsyncSession,
    *,
    user_id: int,
    description: str | None,
    category: str,
    subcategory: str | None,
) -> None:
    phrase = _normalize_phrase(description)
    if not phrase:
        return

    await session.execute(
        text(
            "INSERT INTO user_keywords(user_id, phrase, category, subcategory, use_count) "
            "VALUES (:uid, :phrase, :category, :subcategory, 1) "
            "ON CONFLICT(user_id, phrase) DO UPDATE SET "
            "category = excluded.category, "
            "subcategory = excluded.subcategory, "
            "use_count = user_keywords.use_count + 1, "
            "updated_at = CURRENT_TIMESTAMP"
        ),
        {
            "uid": user_id,
            "phrase": phrase,
            "category": category,
            "subcategory": subcategory,
        },
    )


def _json_dumps_safe(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads_safe(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _serialize_audit_item(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "before": _json_loads_safe(row.before_json),
        "after": _json_loads_safe(row.after_json),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _write_audit(
    session: AsyncSession,
    *,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: int | None,
    before: Any = None,
    after: Any = None,
) -> AuditLog:
    row = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=_json_dumps_safe(before) if before is not None else None,
        after_json=_json_dumps_safe(after) if after is not None else None,
    )
    session.add(row)
    await session.flush()
    return row


def _safe_lang(language: str | None, fallback: str = "uk") -> str:
    value = (language or fallback).lower()
    return value if value in CATEGORIES else fallback


def _localize_category_amounts(rows: list[tuple[str, Decimal]], language: str) -> list[tuple[str, Decimal]]:
    grouped: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for category, amount in rows:
        canonical = canonicalize_category(category) or category
        grouped[canonical] += Decimal(amount or 0)

    localized_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for canonical, amount in grouped.items():
        label = localize_category(canonical, language) or canonical
        localized_totals[label] += amount

    localized: list[tuple[str, Decimal]] = list(localized_totals.items())
    localized.sort(key=lambda item: item[1], reverse=True)
    return localized


def _serialize_settings(settings_row: UserSettings, fallback_language: str = "uk") -> dict:
    lang = _safe_lang(settings_row.interface_language or fallback_language)
    favorites_raw = _json_list(settings_row.favorite_categories)
    favorites_localized: list[str] = []
    for category in favorites_raw:
        canonical = canonicalize_category(category) or category
        localized = localize_category(canonical, lang) or category
        if localized not in favorites_localized:
            favorites_localized.append(localized)

    return {
        "theme": settings_row.theme or "dark",
        "currency": settings_row.currency or "UAH",
        "interface_language": lang,
        "week_starts_on": settings_row.week_starts_on or "monday",
        "notifications_enabled": bool(settings_row.notifications_enabled),
        "limit_alert_mode": (settings_row.limit_alert_mode or "threshold_70"),
        "hidden_blocks": _json_list(settings_row.hidden_blocks),
        "pinned_filters": _json_list(settings_row.pinned_filters),
        "favorite_categories": favorites_localized,
        "desktop_window_width": settings_row.desktop_window_width,
        "desktop_window_height": settings_row.desktop_window_height,
        "desktop_fullscreen_enabled": bool(settings_row.desktop_fullscreen_enabled),
        "budget_warning_percent": int(settings_row.budget_warning_percent or 80),
        "budget_danger_percent": int(settings_row.budget_danger_percent or 100),
    }
