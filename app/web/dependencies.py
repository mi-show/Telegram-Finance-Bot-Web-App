from __future__ import annotations

from hashlib import sha256

from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import SimpleCache
from ..config import get_settings
from ..db import get_session
from ..models import User, UserSettings
from ..repositories.users import UserRepository
from ..scripts.load_custom import CATEGORIES
from .auth import TelegramAuthError, TelegramWebUser, validate_init_data

settings = get_settings()
_auth_cache = SimpleCache(ttl_seconds=settings.webapp_init_data_ttl_seconds)


def _safe_lang(language: str | None, fallback: str = "uk") -> str:
    value = (language or fallback).lower()
    return value if value in CATEGORIES else fallback


async def _db_session():
    async with get_session() as session:
        yield session


async def _get_auth_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> TelegramWebUser:
    payload = x_telegram_init_data

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
    language = _safe_lang(auth_user.language_code or "uk")
    user = await user_repo.get_or_create(auth_user.telegram_id, language=language)
    return user


async def _get_or_create_settings(session: AsyncSession, user: User) -> UserSettings:
    existing = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    settings_row = existing.scalars().first()
    if settings_row:
        return settings_row

    settings_row = UserSettings(
        user_id=user.id,
        interface_language=_safe_lang(user.language or "uk"),
        limit_alert_mode="threshold_70",
        budget_warning_percent=80,
        budget_danger_percent=100,
    )
    session.add(settings_row)
    await session.flush()
    return settings_row


__all__ = (
    "_db_session",
    "_get_auth_user",
    "_get_or_create_user",
    "_get_or_create_settings",
)
