from typing import Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.keywords import KeywordRepository


def _normalize(text: str) -> str:
    if not text:
        return text
    if "Ð" in text or "Р" in text:
        try:
            return text.encode("latin1").decode("utf-8")
        except Exception:
            return text
    return text


class VocabularyService:
    """
    Keeps category keywords in the database.
    Uses DB-backed keyword dictionary and learns from receipts.
    """

    def __init__(self, session: AsyncSession):
        self.repo = KeywordRepository(session)
        self.session = session

    async def keywords_for_languages(self, languages: Sequence[str]) -> dict[str, tuple[str, str]]:
        """
        Get keywords for specified languages.
        Returns dict with format {phrase: (category, subcategory)}
        """
        return await self.repo.keywords_for_languages(languages)

    async def learn_from_items(self, language: str, items: Iterable[dict]) -> int:
        """
        Store item names as keywords so future receipts classify better.
        """
        learned = 0
        for item in items:
            name = item.get("name")
            category = item.get("category")
            if not name or not category:
                continue
            await self.repo.upsert(language, category, _normalize(name), source="receipt", weight=1)
            learned += 1
        return learned
