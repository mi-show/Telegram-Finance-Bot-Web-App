"""User-specific category classifier that learns from user history."""
import logging
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from .category_classifier import CategoryClassifier

logger = logging.getLogger(__name__)


class UserClassifier(CategoryClassifier):
    """
    Extends CategoryClassifier with user-specific learning.
    Learns from user's historical records to improve classification accuracy.
    """

    def __init__(self):
        super().__init__()
        self._user_phrase_cache = defaultdict(dict)  # {user_id: {phrase: (category, subcategory)}}
        self._user_history_stats = defaultdict(lambda: defaultdict(int))  # {user_id: {category: count}}

    async def load_user_history(self, session: AsyncSession, telegram_id: int, limit: int = 500):
        """
        Load user-specific phrase mappings and category usage stats.
        Phrase mappings are loaded from user_keywords table (explicit confirmation only).
        Category stats are loaded from records table.
        telegram_id is the user's Telegram ID (message.from_user.id).
        """
        try:
            logger.info(f"Loading user history for telegram_id={telegram_id}...")
            from sqlalchemy import text

            user_query = "SELECT id FROM users WHERE telegram_id = :tid"
            user_result = await session.execute(text(user_query), {"tid": telegram_id})
            user_row = user_result.first()
            
            if not user_row:
                logger.debug(f"No user found for telegram_id {telegram_id}")
                return
            
            user_id = user_row[0]
            logger.debug(f"Found user: user_id={user_id}")

            records_query = (
                "SELECT category FROM records "
                "WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim"
            )
            records_result = await session.execute(
                text(records_query), 
                {"uid": user_id, "lim": limit}
            )
            records = records_result.all()
            category_counts = defaultdict(int)
            for (category,) in records:
                if category:
                    category_counts[category] += 1

            keywords_query = (
                "SELECT phrase, category, subcategory FROM user_keywords "
                "WHERE user_id = :uid ORDER BY use_count DESC, updated_at DESC LIMIT :lim"
            )
            keywords_result = await session.execute(
                text(keywords_query),
                {"uid": user_id, "lim": limit},
            )
            keywords = keywords_result.all()

            phrase_map = {}
            for phrase, category, subcategory in keywords:
                if phrase:
                    key = phrase.lower().strip()
                    phrase_map[key] = (category, subcategory)

            self._user_phrase_cache[telegram_id] = phrase_map
            self._user_history_stats[telegram_id] = category_counts

            logger.info(
                f"✓ Loaded history for telegram_id {telegram_id}: {len(phrase_map)} phrases, {len(category_counts)} categories"
            )
        except Exception as e:
            logger.exception(f"Failed to load user history for {telegram_id}: {e}")

    async def remember_user_phrase(
        self,
        session: AsyncSession,
        telegram_id: int,
        phrase: str,
        category: str,
        subcategory: str | None = None,
    ) -> bool:
        """Persist explicitly confirmed phrase mapping for a specific user."""
        if not phrase or not category:
            return False

        normalized_phrase = phrase.lower().strip()
        if not normalized_phrase:
            return False

        from sqlalchemy import text

        user_query = "SELECT id FROM users WHERE telegram_id = :tid"
        user_result = await session.execute(text(user_query), {"tid": telegram_id})
        user_row = user_result.first()
        if not user_row:
            return False

        user_id = user_row[0]
        upsert_query = (
            "INSERT INTO user_keywords(user_id, phrase, category, subcategory, use_count) "
            "VALUES (:uid, :phrase, :category, :subcategory, 1) "
            "ON CONFLICT(user_id, phrase) DO UPDATE SET "
            "category = excluded.category, "
            "subcategory = excluded.subcategory, "
            "use_count = user_keywords.use_count + 1, "
            "updated_at = CURRENT_TIMESTAMP"
        )
        await session.execute(
            text(upsert_query),
            {
                "uid": user_id,
                "phrase": normalized_phrase,
                "category": category,
                "subcategory": subcategory,
            },
        )

        self._user_phrase_cache[telegram_id][normalized_phrase] = (category, subcategory)
        return True

    def predict_with_user_context(
        self, text: str, telegram_id: int, language: str = "uk"
    ) -> tuple[str, str | None]:
        """
        Predict category with user-specific context.
        Priority:
        1. Exact user phrase match
        2. Fuzzy user phrase match
        3. Standard classifier (keyword + ML)
        """
        text_lower = text.lower().strip()
        logger.debug(f"predict_with_user_context: text='{text}', telegram_id={telegram_id}, lang={language}")

        # Check for exact user phrase match
        user_phrases = self._user_phrase_cache.get(telegram_id, {})
        logger.debug(f"User phrases cache size: {len(user_phrases)}")
        
        if text_lower in user_phrases:
            cat, subcat = user_phrases[text_lower]
            logger.info(f"✓ User phrase EXACT match: '{text}' -> {cat}/{subcat}")
            return cat, subcat

        # Try fuzzy match against user phrases
        if user_phrases:
            try:
                from rapidfuzz import fuzz, process

                matches = process.extract(
                    text_lower,
                    list(user_phrases.keys()),
                    scorer=fuzz.WRatio,
                    score_cutoff=80,
                    limit=1,
                )
                if matches:
                    matched_phrase, score, _ = matches[0]
                    cat, subcat = user_phrases[matched_phrase]
                    logger.info(
                        f"✓ User phrase FUZZY match (score {score}): '{text}' -> {matched_phrase} -> {cat}/{subcat}"
                    )
                    return cat, subcat
            except ImportError:
                logger.warning("rapidfuzz not available for user phrase matching")

        # Fall back to standard classifier
        logger.debug(f"No user match, using standard classifier for '{text}'")
        cat, subcat = self.predict_with_subcategory(text, language=language)
        logger.info(f"Standard classification: '{text}' -> {cat}/{subcat}")
        return cat, subcat

    def predict_with_user_context_confidence(
        self,
        text: str,
        telegram_id: int,
        language: str = "uk",
    ) -> tuple[str, str | None, float, str]:
        """
        Predict category with confidence and source info.
        Source can be: user_exact, user_fuzzy, override, dictionary, fuzzy, ml, fallback.
        """
        text_lower = (text or "").lower().strip()
        if not text_lower:
            return self.predict_with_subcategory_confidence(text, language=language)

        user_phrases = self._user_phrase_cache.get(telegram_id, {})
        if text_lower in user_phrases:
            cat, subcat = user_phrases[text_lower]
            return cat, subcat, 1.0, "user_exact"

        if user_phrases:
            try:
                from rapidfuzz import fuzz, process

                matches = process.extract(
                    text_lower,
                    list(user_phrases.keys()),
                    scorer=fuzz.WRatio,
                    score_cutoff=80,
                    limit=1,
                )
                if matches:
                    matched_phrase, score, _ = matches[0]
                    cat, subcat = user_phrases[matched_phrase]
                    confidence = max(0.8, min(float(score) / 100.0, 0.99))
                    return cat, subcat, confidence, "user_fuzzy"
            except ImportError:
                logger.warning("rapidfuzz not available for user phrase matching")

        return self.predict_with_subcategory_confidence(text, language=language)

    def get_user_top_categories(self, telegram_id: int, limit: int = 5) -> list[tuple[str, int]]:
        """Get user's most used categories."""
        stats = self._user_history_stats.get(telegram_id, {})
        return sorted(stats.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_user_phrase_suggestions(self, telegram_id: int, prefix: str = "", limit: int = 5) -> list[str]:
        """Get phrases from user history matching a prefix."""
        user_phrases = self._user_phrase_cache.get(telegram_id, {})
        prefix_lower = prefix.lower()
        matching = [p for p in user_phrases.keys() if p.startswith(prefix_lower)]
        return sorted(matching)[:limit]

    def clear_user_cache(self, telegram_id: int):
        """Clear user-specific cache."""
        self._user_phrase_cache.pop(telegram_id, None)
        self._user_history_stats.pop(telegram_id, None)
        logger.info(f"Cleared cache for telegram_id {telegram_id}")

    def was_word_recognized(self, text: str, language: str = "uk") -> bool:
        """
        Check if a word/phrase was recognized with acceptable confidence.
        Returns False for fallback or low-confidence ML guesses.
        """
        if not text:
            return False

        category, _subcat, confidence, source = self.predict_with_subcategory_confidence(
            text,
            language=language,
        )
        recognized = source in {"override", "dictionary", "fuzzy"} or (
            source == "ml" and confidence >= 0.8 and category != "Other"
        )
        logger.info(
            "[RECOGNITION] text='%s' source=%s confidence=%.3f recognized=%s",
            text,
            source,
            confidence,
            recognized,
        )
        return recognized

    def get_all_categories(self, language: str = "uk") -> list[str]:
        """
        Get all available top-level categories in the specified language.
        """
        categories = set()
        
        # Get from dictionary entries
        for value in self.dictionary.values():
            if isinstance(value, tuple):
                cat = value[0]  # (category, subcategory)
            else:
                cat = value  # Just category
            
            if cat and cat != "Other":
                categories.add(cat)
        
        # Add fallback categories
        categories.add("Other")
        
        return sorted(list(categories))

    def get_subcategories_for_category(self, category: str) -> list[str]:
        """Get all subcategories available for a given category."""
        subcategories = set()
        
        for value in self.dictionary.values():
            if isinstance(value, tuple):
                cat, subcat = value
                if cat == category and subcat:
                    subcategories.add(subcat)
        
        return sorted(list(subcategories))
