from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.handlers.common import ONBOARDING_INCOME_MARKER, _save_start_income_and_currency
from app.models import BudgetPlan, Record, RecordType, RecurringEntry, User, UserSettings
from app.web.core.budget import _auto_apply_recurring_for_current_month


@pytest.mark.asyncio
async def test_start_onboarding_income_creates_record_and_recurring(tmp_path):
    db_file = tmp_path / "onboarding_income.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await _save_start_income_and_currency(
            session,
            telegram_id=123456789,
            lang="ru",
            amount=Decimal("27000"),
            currency="UAH",
        )
        await session.commit()

        user = (await session.execute(select(User).where(User.telegram_id == 123456789))).scalars().one()

        settings_row = (await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))).scalars().one()
        assert settings_row.currency == "UAH"

        budget = (await session.execute(select(BudgetPlan).where(BudgetPlan.user_id == user.id))).scalars().first()
        assert budget is not None
        assert Decimal(budget.planned_income) == Decimal("27000")

        record = (
            await session.execute(
                select(Record).where(
                    Record.user_id == user.id,
                    Record.type == RecordType.INCOME,
                    Record.description.like(f"%{ONBOARDING_INCOME_MARKER}%"),
                )
            )
        ).scalars().first()
        assert record is not None
        assert Decimal(record.amount) == Decimal("27000")
        assert record.currency == "UAH"

        recurring = (
            await session.execute(
                select(RecurringEntry).where(
                    RecurringEntry.user_id == user.id,
                    RecurringEntry.type == RecordType.INCOME,
                )
            )
        ).scalars().first()
        assert recurring is not None
        assert Decimal(recurring.amount) == Decimal("27000")
        assert recurring.currency == "UAH"
        assert recurring.is_active is True
        assert recurring.last_confirmed_period == date.today().replace(day=1)
        assert recurring.last_confirmed_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_start_onboarding_income_can_skip_recurring_creation(tmp_path):
    db_file = tmp_path / "onboarding_income_skip.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await _save_start_income_and_currency(
            session,
            telegram_id=22334455,
            lang="ru",
            amount=Decimal("18000"),
            currency="UAH",
            create_recurring=False,
        )
        await session.commit()

        user = (await session.execute(select(User).where(User.telegram_id == 22334455))).scalars().one()

        record = (
            await session.execute(
                select(Record).where(
                    Record.user_id == user.id,
                    Record.type == RecordType.INCOME,
                    Record.description.like(f"%{ONBOARDING_INCOME_MARKER}%"),
                )
            )
        ).scalars().first()
        assert record is not None
        assert Decimal(record.amount) == Decimal("18000")

        recurring = (
            await session.execute(
                select(RecurringEntry).where(
                    RecurringEntry.user_id == user.id,
                    RecurringEntry.type == RecordType.INCOME,
                )
            )
        ).scalars().first()
        assert recurring is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_auto_apply_backfills_legacy_onboarding_recurring_confirmation(tmp_path):
    db_file = tmp_path / "onboarding_income_legacy_sync.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(telegram_id=99887766, language="ru")
        session.add(user)
        await session.flush()

        session.add(
            Record(
                user_id=user.id,
                type=RecordType.INCOME,
                category="Salary",
                subcategory="Main",
                amount=Decimal("27000"),
                currency="UAH",
                happened_on=date(2026, 4, 20),
                description=f"Ежемесячный доход {ONBOARDING_INCOME_MARKER}",
            )
        )
        session.add(
            RecurringEntry(
                user_id=user.id,
                title="Ежемесячный доход",
                type=RecordType.INCOME,
                category="Salary",
                subcategory="Main",
                amount=Decimal("27000"),
                currency="UAH",
                day_of_month=20,
                reminder_days_before=2,
                is_active=True,
                last_confirmed_period=None,
                last_confirmed_at=None,
            )
        )
        await session.commit()

        created = await _auto_apply_recurring_for_current_month(
            session,
            telegram_id=user.telegram_id,
            user_id=user.id,
            default_currency="UAH",
            today=date(2026, 5, 12),
        )
        assert created == 0

        recurring = (
            await session.execute(
                select(RecurringEntry).where(RecurringEntry.user_id == user.id)
            )
        ).scalars().one()
        assert recurring.last_confirmed_period == date(2026, 4, 1)
        assert recurring.last_confirmed_at is not None

        income_records = (
            await session.execute(
                select(Record).where(
                    Record.user_id == user.id,
                    Record.type == RecordType.INCOME,
                )
            )
        ).scalars().all()
        assert len(income_records) == 1

    await engine.dispose()
