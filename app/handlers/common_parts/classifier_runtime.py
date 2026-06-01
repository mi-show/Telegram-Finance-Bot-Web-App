import logging

from ...db import get_session
from ...repositories.users import UserRepository
from ...scripts.load_custom import ensure_custom_keywords
from ...services.vocabulary_service import VocabularyService
from .i18n import normalize_lang

logger = logging.getLogger(__name__)


class ClassifierRuntime:
    """Owns in-process classifier bootstrap state to keep handlers thin."""

    def __init__(self, user_classifier) -> None:
        self.user_classifier = user_classifier
        self._keywords_bootstrapped = False
        self._classifier_initialized = False
        self._user_history_loaded: set[int] = set()

    async def warmup(self) -> None:
        """Preload shared keyword dictionary and train model once at startup."""
        if self._classifier_initialized:
            return

        if not self._keywords_bootstrapped:
            try:
                await ensure_custom_keywords()
            except Exception as exc:
                logger.warning("Custom keyword bootstrap skipped during warmup: %s", exc)
            self._keywords_bootstrapped = True

        try:
            async with get_session() as session:
                vocab = VocabularyService(session)
                langs = ["uk", "ru", "en"]
                extra_keywords = await vocab.keywords_for_languages(langs)
                self.user_classifier.set_languages(langs, translate_to="uk", extra_keywords=extra_keywords)
                self._classifier_initialized = True
        except Exception as exc:
            logger.warning("Classifier warmup skipped: %s", exc)

    async def prepare_classifier(self, session, telegram_id: int) -> str:
        """Load user language and prepare classifier with minimal per-message overhead."""
        user_repo = UserRepository(session)
        vocab = VocabularyService(session)

        raw_lang = await user_repo.get_language(telegram_id)
        lang = normalize_lang(raw_lang)
        if raw_lang != lang:
            await user_repo.set_language(telegram_id, lang)
            await session.commit()

        if telegram_id not in self._user_history_loaded:
            try:
                await self.user_classifier.load_user_history(session, telegram_id)
                self._user_history_loaded.add(telegram_id)
            except Exception as exc:
                logger.warning("Failed to load user classifier history: %s", exc)

        if not self._keywords_bootstrapped:
            try:
                await ensure_custom_keywords()
            except Exception as exc:
                logger.warning("Custom keyword bootstrap skipped: %s", exc)
            self._keywords_bootstrapped = True

        if not self._classifier_initialized:
            langs = ["uk", "ru", "en"]
            try:
                extra_keywords = await vocab.keywords_for_languages(langs)
            except Exception as exc:
                logger.warning("Keyword lookup failed, using DB dictionary fallback only: %s", exc)
                extra_keywords = {}
            self.user_classifier.set_languages(langs, translate_to=lang, extra_keywords=extra_keywords)
            self._classifier_initialized = True
        else:
            self.user_classifier.translate_to = lang

        return lang

    async def get_user_language(self, telegram_id: int) -> str:
        """Get user's language setting without loading full classifier."""
        try:
            async with get_session() as session:
                user_repo = UserRepository(session)
                return normalize_lang(await user_repo.get_language(telegram_id))
        except Exception:
            return "uk"
