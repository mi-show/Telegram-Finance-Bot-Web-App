from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..api_models import SettingsUpdateIn
from ..auth import TelegramWebUser
from ..dependencies import _db_session, _get_auth_user, _get_or_create_settings, _get_or_create_user
from ..core import (
    ALLOWED_HIDDEN_BLOCKS,
    _convert_user_amounts_to_currency,
    _normalize_setting_tokens,
    _safe_lang,
    _serialize_settings,
    canonicalize_category,
    clear_stats_cache,
    json,
)

router = APIRouter()


@router.get("/api/webapp/settings")
async def webapp_get_settings(
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)
    await session.commit()
    return _serialize_settings(settings_row, fallback_language=user.language or "uk")


@router.put("/api/webapp/settings")
async def webapp_update_settings(
    payload: SettingsUpdateIn,
    auth_user: TelegramWebUser = Depends(_get_auth_user),
    session: AsyncSession = Depends(_db_session),
):
    user = await _get_or_create_user(session, auth_user)
    settings_row = await _get_or_create_settings(session, user)

    current_currency = (settings_row.currency or "UAH").upper()

    if payload.theme is not None:
        settings_row.theme = payload.theme
    if payload.currency is not None:
        requested_currency = payload.currency.upper()
        if requested_currency != current_currency:
            await _convert_user_amounts_to_currency(
                session,
                user_id=user.id,
                from_currency=current_currency,
                to_currency=requested_currency,
            )
        settings_row.currency = requested_currency
    if payload.interface_language is not None:
        normalized_lang = _safe_lang(
            payload.interface_language.lower(),
            fallback=settings_row.interface_language or user.language or "uk",
        )
        settings_row.interface_language = normalized_lang
        user.language = normalized_lang
    if payload.week_starts_on is not None:
        settings_row.week_starts_on = payload.week_starts_on
    if payload.notifications_enabled is not None:
        settings_row.notifications_enabled = payload.notifications_enabled
    if payload.limit_alert_mode is not None:
        settings_row.limit_alert_mode = payload.limit_alert_mode
    if payload.hidden_blocks is not None:
        hidden_blocks = _normalize_setting_tokens(payload.hidden_blocks, max_items=16)
        hidden_blocks = [item for item in hidden_blocks if item in ALLOWED_HIDDEN_BLOCKS]
        settings_row.hidden_blocks = json.dumps(hidden_blocks)
    if payload.pinned_filters is not None:
        pinned_filters = _normalize_setting_tokens(payload.pinned_filters, max_items=32)
        settings_row.pinned_filters = json.dumps(pinned_filters)
    if payload.favorite_categories is not None:
        favorites: list[str] = []
        for category in payload.favorite_categories:
            category = category.strip()
            if not category:
                continue
            canonical = canonicalize_category(category) or category
            if canonical not in favorites:
                favorites.append(canonical)
            if len(favorites) >= 64:
                break
        settings_row.favorite_categories = json.dumps(favorites)
    if payload.desktop_window_width is not None:
        settings_row.desktop_window_width = payload.desktop_window_width
    if payload.desktop_window_height is not None:
        settings_row.desktop_window_height = payload.desktop_window_height
    if payload.desktop_fullscreen_enabled is not None:
        settings_row.desktop_fullscreen_enabled = payload.desktop_fullscreen_enabled
    if payload.budget_warning_percent is not None:
        settings_row.budget_warning_percent = payload.budget_warning_percent
    if payload.budget_danger_percent is not None:
        settings_row.budget_danger_percent = payload.budget_danger_percent

    await session.commit()
    clear_stats_cache()

    return _serialize_settings(settings_row, fallback_language=user.language or "uk")


