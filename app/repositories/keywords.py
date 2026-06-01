import logging
from typing import Iterable, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CategoryKeyword

logger = logging.getLogger(__name__)


class KeywordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(CategoryKeyword))
        return result.scalar_one() or 0

    async def bulk_insert(self, rows: Iterable[CategoryKeyword]) -> None:
        self.session.add_all(list(rows))

    async def upsert(
        self,
        language: str,
        category: str,
        phrase: str,
        subcategory: str | None = None,
        source: str = "manual",
        weight: int = 1,
    ):
        phrase_norm = phrase.strip().lower()
        if not phrase_norm:
            return
        existing = await self.session.scalar(
            select(CategoryKeyword).where(
                CategoryKeyword.language == language,
                CategoryKeyword.phrase == phrase_norm,
            )
        )
        if existing:
            existing.category = category
            existing.subcategory = subcategory
            existing.source = source
            existing.weight = max(existing.weight or 0, weight)
        else:
            kw = CategoryKeyword(
                language=language,
                category=category,
                subcategory=subcategory,
                phrase=phrase_norm,
                source=source,
                weight=weight,
            )
            self.session.add(kw)

        await self.session.flush()

    async def keywords_for_languages(self, languages: Sequence[str]) -> dict[str, tuple[str, str]]:
        """
        Returns dict: phrase -> (category, subcategory)
        Priority follows the languages order passed by caller.
        """
        if not languages:
            return {}

        ordered_languages: list[str] = []
        for language in languages:
            normalized = (language or "").lower().strip()
            if normalized and normalized not in ordered_languages:
                ordered_languages.append(normalized)
        if not ordered_languages:
            return {}

        result = await self.session.execute(
            select(
                CategoryKeyword.language,
                CategoryKeyword.phrase,
                CategoryKeyword.category,
                CategoryKeyword.subcategory,
            ).where(
                CategoryKeyword.language.in_(ordered_languages)
            )
        )

        rows_by_language: dict[str, list[tuple[str, str, str | None]]] = {
            language: [] for language in ordered_languages
        }
        for language, phrase, category, subcategory in result:
            rows_by_language.setdefault(language, []).append((phrase, category, subcategory))

        data: dict[str, tuple[str, str]] = {}
        for language in ordered_languages:
            for phrase, category, subcategory in rows_by_language.get(language, []):
                if phrase in data:
                    continue
                data[phrase] = (category, subcategory or "")
        return data
