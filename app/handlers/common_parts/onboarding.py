from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BudgetPlan, Record, RecordType, RecurringEntry, UserSettings
from ...repositories.users import UserRepository
from .constants import (
    ONBOARDING_INCOME_CATEGORY,
    ONBOARDING_INCOME_MARKER,
    ONBOARDING_INCOME_SUBCATEGORY,
    ONBOARDING_RECURRING_TITLES,
    ONBOARDING_RECURRING_TITLE_VARIANTS,
    SUPPORTED_ONBOARDING_CURRENCIES,
)


def month_bounds(base_day: date) -> tuple[date, date]:
    month_start = base_day.replace(day=1)
    next_month_start = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month_start - timedelta(days=1)
    return month_start, month_end


class OnboardingService:
    """Persists /start onboarding income setup into settings, budget, records and recurring entries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_start_currency(
        self,
        telegram_id: int,
        lang: str,
        currency: str,
    ) -> None:
        normalized_currency = currency.upper().strip()
        if normalized_currency not in SUPPORTED_ONBOARDING_CURRENCIES:
            raise ValueError("Unsupported onboarding currency")

        user_repo = UserRepository(self.session)
        user = await user_repo.get_or_create(
            telegram_id,
            language=lang,
            sync_existing_language=True,
        )

        settings_result = await self.session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        settings_row = settings_result.scalars().first()
        if settings_row is None:
            settings_row = UserSettings(
                user_id=user.id,
                currency=normalized_currency,
                interface_language=lang,
            )
            self.session.add(settings_row)
        else:
            settings_row.currency = normalized_currency
            settings_row.interface_language = lang

    async def save_start_income_and_currency(
        self,
        telegram_id: int,
        lang: str,
        amount: Decimal,
        currency: str,
        *,
        create_recurring: bool = True,
    ) -> None:
        normalized_currency = currency.upper().strip()
        if normalized_currency not in SUPPORTED_ONBOARDING_CURRENCIES:
            raise ValueError("Unsupported onboarding currency")

        await self.save_start_currency(telegram_id, lang, normalized_currency)

        user_repo = UserRepository(self.session)
        user = await user_repo.get_or_create(
            telegram_id,
            language=lang,
            sync_existing_language=True,
        )

        period_start, period_end = month_bounds(date.today())
        budget_result = await self.session.execute(
            select(BudgetPlan)
            .where(
                BudgetPlan.user_id == user.id,
                BudgetPlan.period_start == period_start,
                BudgetPlan.period_end == period_end,
            )
            .order_by(BudgetPlan.created_at.desc())
            .limit(1)
        )
        budget = budget_result.scalars().first()
        if budget is None:
            budget = BudgetPlan(
                user_id=user.id,
                period_start=period_start,
                period_end=period_end,
                planned_expense=Decimal("0"),
                planned_income=amount,
            )
            self.session.add(budget)
        else:
            budget.planned_income = amount

        title = ONBOARDING_RECURRING_TITLES.get(lang, ONBOARDING_RECURRING_TITLES["en"])
        description = f"{title} {ONBOARDING_INCOME_MARKER}"
        today = date.today()

        record_result = await self.session.execute(
            select(Record)
            .where(
                Record.user_id == user.id,
                Record.type == RecordType.INCOME,
                Record.happened_on >= period_start,
                Record.happened_on <= period_end,
                Record.description.like(f"%{ONBOARDING_INCOME_MARKER}%"),
            )
            .order_by(Record.id.desc())
            .limit(1)
        )
        income_record = record_result.scalars().first()
        if income_record is None:
            self.session.add(
                Record(
                    user_id=user.id,
                    type=RecordType.INCOME,
                    category=ONBOARDING_INCOME_CATEGORY,
                    subcategory=ONBOARDING_INCOME_SUBCATEGORY,
                    amount=amount,
                    currency=normalized_currency,
                    happened_on=today,
                    description=description,
                )
            )
        else:
            income_record.category = ONBOARDING_INCOME_CATEGORY
            income_record.subcategory = ONBOARDING_INCOME_SUBCATEGORY
            income_record.amount = amount
            income_record.currency = normalized_currency
            income_record.happened_on = today
            income_record.description = description

        if create_recurring:
            recurring_result = await self.session.execute(
                select(RecurringEntry)
                .where(
                    RecurringEntry.user_id == user.id,
                    RecurringEntry.type == RecordType.INCOME,
                    RecurringEntry.title.in_(ONBOARDING_RECURRING_TITLE_VARIANTS),
                )
                .order_by(RecurringEntry.id.desc())
                .limit(1)
            )
            recurring_income = recurring_result.scalars().first()
            if recurring_income is None:
                self.session.add(
                    RecurringEntry(
                        user_id=user.id,
                        title=title,
                        type=RecordType.INCOME,
                        category=ONBOARDING_INCOME_CATEGORY,
                        subcategory=ONBOARDING_INCOME_SUBCATEGORY,
                        amount=amount,
                        currency=normalized_currency,
                        day_of_month=today.day,
                        reminder_days_before=2,
                        is_active=True,
                        last_confirmed_period=period_start,
                        last_confirmed_at=datetime.utcnow(),
                    )
                )
            else:
                recurring_income.title = title
                recurring_income.category = ONBOARDING_INCOME_CATEGORY
                recurring_income.subcategory = ONBOARDING_INCOME_SUBCATEGORY
                recurring_income.amount = amount
                recurring_income.currency = normalized_currency
                recurring_income.is_active = True
                recurring_income.last_confirmed_period = period_start
                recurring_income.last_confirmed_at = datetime.utcnow()
