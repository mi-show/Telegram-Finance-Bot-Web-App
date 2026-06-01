import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User, UserSettings

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {"uk", "ru", "en"}


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _normalize_language(language: Optional[str], fallback: str = "uk") -> str:
        value = (language or fallback).lower().strip()
        return value if value in SUPPORTED_LANGUAGES else fallback

    async def get_or_create(
        self,
        telegram_id: int,
        language: Optional[str] = None,
        *,
        sync_existing_language: bool = False,
    ) -> User:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().first()
        if user:
            if sync_existing_language and language:
                normalized_language = self._normalize_language(language, fallback=user.language or "uk")
                if user.language != normalized_language:
                    user.language = normalized_language
            return user

        normalized_language = self._normalize_language(language)
        user = User(telegram_id=telegram_id, language=normalized_language)
        self.session.add(user)
        await self.session.flush()
        logger.info("Created user %s with lang=%s", telegram_id, user.language)
        return user

    async def set_language(self, telegram_id: int, language: str) -> User:
        normalized_language = self._normalize_language(language)
        user = await self.get_or_create(
            telegram_id,
            language=normalized_language,
            sync_existing_language=True,
        )
        user.language = normalized_language

        settings_result = await self.session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        settings_row = settings_result.scalars().first()
        if settings_row is None:
            settings_row = UserSettings(
                user_id=user.id,
                interface_language=normalized_language,
            )
            self.session.add(settings_row)
        else:
            settings_row.interface_language = normalized_language

        await self.session.flush()
        return user

    async def get_language(self, telegram_id: int) -> str:
        settings_result = await self.session.execute(
            select(UserSettings.interface_language)
            .join(User, User.id == UserSettings.user_id)
            .where(User.telegram_id == telegram_id)
        )
        settings_lang = settings_result.scalar_one_or_none()
        if isinstance(settings_lang, str) and settings_lang.strip():
            return self._normalize_language(settings_lang)

        result = await self.session.execute(select(User.language).where(User.telegram_id == telegram_id))
        lang = result.scalar_one_or_none()
        if isinstance(lang, str) and lang.strip():
            return self._normalize_language(lang)
        return "uk"
