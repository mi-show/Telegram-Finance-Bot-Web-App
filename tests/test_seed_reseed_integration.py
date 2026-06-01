from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import CategoryKeyword
from app.scripts import load_custom


@pytest.mark.asyncio
async def test_ensure_custom_keywords_reseeds_seed_rows_and_keeps_manual(monkeypatch, tmp_path):
    db_file = tmp_path / "seed_reseed.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def test_get_session():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(load_custom, "get_session", test_get_session)

    entries_v1 = [
        {
            "language": "en",
            "category": "Housing",
            "subcategory": "Rent",
            "phrase": "rent",
            "weight": 2,
        },
        {
            "language": "en",
            "category": "Transport",
            "subcategory": "Taxi",
            "phrase": "cab",
            "weight": 2,
        },
    ]
    entries_v2 = [
        {
            "language": "en",
            "category": "Housing",
            "subcategory": "Utilities",
            "phrase": "rent",
            "weight": 3,
        },
        {
            "language": "uk",
            "category": "📱 Зв'язок",
            "subcategory": "Мобільний зв'язок",
            "phrase": "мобільний",
            "weight": 2,
        },
    ]

    async with session_factory() as session:
        session.add_all(
            [
                CategoryKeyword(
                    language="en",
                    category="Other",
                    subcategory="Misc",
                    phrase="old-seed",
                    source="seed",
                    weight=1,
                ),
                CategoryKeyword(
                    language="en",
                    category="Manual",
                    subcategory="Custom",
                    phrase="manual-phrase",
                    source="manual",
                    weight=5,
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(load_custom, "load_seed_keyword_entries", lambda: entries_v1)
    await load_custom.ensure_custom_keywords()

    async with session_factory() as session:
        seed_rows = (
            await session.execute(
                select(CategoryKeyword).where(CategoryKeyword.source == "seed")
            )
        ).scalars().all()
        manual_rows = (
            await session.execute(
                select(CategoryKeyword).where(CategoryKeyword.source != "seed")
            )
        ).scalars().all()

    assert len(seed_rows) == 2
    assert {row.phrase for row in seed_rows} == {"rent", "cab"}
    assert len(manual_rows) == 1
    assert manual_rows[0].phrase == "manual-phrase"

    monkeypatch.setattr(load_custom, "load_seed_keyword_entries", lambda: entries_v2)
    await load_custom.ensure_custom_keywords()

    async with session_factory() as session:
        seed_rows = (
            await session.execute(
                select(CategoryKeyword).where(CategoryKeyword.source == "seed")
            )
        ).scalars().all()
        manual_rows = (
            await session.execute(
                select(CategoryKeyword).where(CategoryKeyword.source != "seed")
            )
        ).scalars().all()

    assert len(seed_rows) == 2
    seed_map = {(row.language, row.phrase): row for row in seed_rows}
    assert set(seed_map.keys()) == {("en", "rent"), ("uk", "мобільний")}
    assert seed_map[("en", "rent")].subcategory == "Utilities"
    assert seed_map[("en", "rent")].weight == 3

    assert len(manual_rows) == 1
    assert manual_rows[0].phrase == "manual-phrase"
    assert manual_rows[0].source == "manual"

    await engine.dispose()
