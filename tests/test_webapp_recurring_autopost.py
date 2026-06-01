from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Record, RecordType, RecurringEntry, User, UserSettings

webapp_module = importlib.import_module("app.web.app")


@pytest.mark.asyncio
async def test_recurring_autopost_once_is_idempotent_and_respects_due_date(tmp_path, monkeypatch):
    db_file = tmp_path / "recurring_autopost.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(telegram_id=700000001, language="ru")
        session.add(user)
        await session.flush()

        session.add(
            UserSettings(
                user_id=user.id,
                currency="UAH",
                interface_language="ru",
            )
        )

        session.add_all(
            [
                RecurringEntry(
                    user_id=user.id,
                    title="Auto Salary",
                    type=RecordType.INCOME,
                    category="Salary",
                    subcategory="Main",
                    amount=Decimal("1000.00"),
                    currency="UAH",
                    day_of_month=1,
                    reminder_days_before=2,
                    is_active=True,
                ),
                RecurringEntry(
                    user_id=user.id,
                    title="Late Fee",
                    type=RecordType.EXPENSE,
                    category="Other",
                    subcategory=None,
                    amount=Decimal("300.00"),
                    currency="UAH",
                    day_of_month=28,
                    reminder_days_before=2,
                    is_active=True,
                ),
            ]
        )
        await session.commit()

        original_engine = getattr(webapp_module, "engine")
        monkeypatch.setattr(webapp_module, "engine", engine)

    test_day = date.today().replace(day=15)

    created_first = await webapp_module._run_recurring_autopost_once(today=test_day)
    assert created_first == 1

    created_second = await webapp_module._run_recurring_autopost_once(today=test_day)
    assert created_second == 0

    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.telegram_id == 700000001))).scalars().one()

        created_records = (
            await session.execute(
                select(Record).where(
                    Record.user_id == user.id,
                    Record.description == "Auto Salary",
                )
            )
        ).scalars().all()
        assert len(created_records) == 1
        assert created_records[0].happened_on == test_day.replace(day=1)

        recurring_rows = (
            await session.execute(
                select(RecurringEntry)
                .where(RecurringEntry.user_id == user.id)
                .order_by(RecurringEntry.id.asc())
            )
        ).scalars().all()

        assert recurring_rows[0].last_confirmed_period == test_day.replace(day=1)
        assert recurring_rows[0].last_confirmed_at is not None
        assert recurring_rows[1].last_confirmed_period is None

        monkeypatch.setattr(webapp_module, "engine", original_engine)
    await engine.dispose()