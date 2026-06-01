from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.models import AuditLog, BudgetPlan, CategoryBudgetLimit, Record, RecordType, User, UserSettings


DATABASE_URL = os.getenv("E2E_DATABASE_URL", "sqlite+aiosqlite:///./data/e2e_webapp.db")
TELEGRAM_ID = int(os.getenv("E2E_TELEGRAM_ID", "915551234"))


async def prepare_data() -> None:
    engine = create_async_engine(DATABASE_URL, future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure lightweight schema changes (add columns added after initial schema)
    async with engine.begin() as conn:
        # sqlite: check pragma for user_settings and add missing columns introduced later
        res = await conn.execute(text("PRAGMA table_info(user_settings)"))
        cols = [row[1] for row in res]

        if "desktop_window_width" not in cols:
            await conn.execute(text("ALTER TABLE user_settings ADD COLUMN desktop_window_width INTEGER"))

        if "desktop_window_height" not in cols:
            await conn.execute(text("ALTER TABLE user_settings ADD COLUMN desktop_window_height INTEGER"))

        if "desktop_fullscreen_enabled" not in cols:
            await conn.execute(text("ALTER TABLE user_settings ADD COLUMN desktop_fullscreen_enabled BOOLEAN DEFAULT 0"))
            await conn.execute(text("UPDATE user_settings SET desktop_fullscreen_enabled=0 WHERE desktop_fullscreen_enabled IS NULL"))

        if "limit_alert_mode" not in cols:
            await conn.execute(
                text("ALTER TABLE user_settings ADD COLUMN limit_alert_mode VARCHAR(32) DEFAULT 'threshold_70'")
            )
        await conn.execute(
            text("UPDATE user_settings SET limit_alert_mode='threshold_70' WHERE limit_alert_mode IS NULL OR limit_alert_mode=''")
        )

        if "budget_warning_percent" not in cols:
            await conn.execute(
                text("ALTER TABLE user_settings ADD COLUMN budget_warning_percent INTEGER DEFAULT 80")
            )
        if "budget_danger_percent" not in cols:
            await conn.execute(
                text("ALTER TABLE user_settings ADD COLUMN budget_danger_percent INTEGER DEFAULT 100")
            )

        # Ensure category_budget_limits has subcategory column (older DBs may lack it)
        res2 = await conn.execute(text("PRAGMA table_info(category_budget_limits)"))
        cols2 = [row[1] for row in res2]
        if "subcategory" not in cols2:
            await conn.execute(text("ALTER TABLE category_budget_limits ADD COLUMN subcategory VARCHAR(64)"))

    today = date.today()
    month_start = today.replace(day=1)
    next_month_start = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month_start - timedelta(days=1)

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == TELEGRAM_ID))
        if user is None:
            user = User(telegram_id=TELEGRAM_ID, language="uk")
            session.add(user)
            await session.flush()

        await session.execute(delete(AuditLog).where(AuditLog.user_id == user.id))
        await session.execute(delete(Record).where(Record.user_id == user.id))
        await session.execute(delete(BudgetPlan).where(BudgetPlan.user_id == user.id))
        await session.execute(delete(CategoryBudgetLimit).where(CategoryBudgetLimit.user_id == user.id))

        settings_row = await session.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
        if settings_row is None:
            settings_row = UserSettings(user_id=user.id)
            session.add(settings_row)

        settings_row.theme = "dark"
        settings_row.currency = "UAH"
        settings_row.interface_language = "en"
        settings_row.week_starts_on = "monday"
        settings_row.notifications_enabled = True
        settings_row.budget_warning_percent = 80
        settings_row.budget_danger_percent = 100

        session.add_all(
            [
                Record(
                    user_id=user.id,
                    type=RecordType.EXPENSE,
                    category="Food & Drinks",
                    subcategory="Groceries",
                    amount=Decimal("250.00"),
                    currency="UAH",
                    happened_on=today,
                    description="Weekly basket",
                ),
                Record(
                    user_id=user.id,
                    type=RecordType.EXPENSE,
                    category="Transport",
                    subcategory="Taxi",
                    amount=Decimal("120.50"),
                    currency="UAH",
                    happened_on=today - timedelta(days=1),
                    description="Airport ride",
                ),
                Record(
                    user_id=user.id,
                    type=RecordType.INCOME,
                    category="Salary",
                    subcategory="Main",
                    amount=Decimal("5000.00"),
                    currency="UAH",
                    happened_on=today - timedelta(days=2),
                    description="Monthly salary",
                ),
                BudgetPlan(
                    user_id=user.id,
                    period_start=month_start,
                    period_end=month_end,
                    planned_expense=Decimal("2200.00"),
                    planned_income=Decimal("6000.00"),
                ),
                CategoryBudgetLimit(
                    user_id=user.id,
                    category="Food & Drinks",
                    period_start=month_start,
                    period_end=month_end,
                    limit_amount=Decimal("900.00"),
                ),
                CategoryBudgetLimit(
                    user_id=user.id,
                    category="Transport",
                    period_start=month_start,
                    period_end=month_end,
                    limit_amount=Decimal("450.00"),
                ),
            ]
        )

        await session.commit()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare_data())
