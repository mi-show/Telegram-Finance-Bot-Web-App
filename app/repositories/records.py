import logging
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BudgetPlan, Record, RecordType, User
from ..schemas import RecordCreate, RecordFilter

logger = logging.getLogger(__name__)


class RecordRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_or_create_user(self, telegram_id: int) -> User:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalars().first()
        if not user:
            logger.info(f"Creating new user with telegram_id={telegram_id}")
            user = User(telegram_id=telegram_id)
            self.session.add(user)
            await self.session.flush()
        return user

    def _apply_filters(self, query: Select, filters: RecordFilter | None) -> Select:
        if not filters:
            return query
        if filters.date_from:
            query = query.where(Record.happened_on >= filters.date_from)
        if filters.date_to:
            query = query.where(Record.happened_on <= filters.date_to)
        if filters.categories:
            query = query.where(Record.category.in_(filters.categories))
        if filters.type:
            query = query.where(Record.type == RecordType(filters.type))
        if filters.min_amount:
            query = query.where(Record.amount >= filters.min_amount)
        if filters.max_amount:
            query = query.where(Record.amount <= filters.max_amount)
        if filters.description_query:
            like = f"%{filters.description_query.lower()}%"
            query = query.where(
                func.lower(func.coalesce(Record.description, "")).like(like)
            )
        return query

    async def add_record(self, telegram_id: int, data: RecordCreate) -> Record:
        user = await self._get_or_create_user(telegram_id)

        # Duplicate check: same date + category + amount (ignoring subcategory for flexibility)
        existing = await self.session.execute(
            select(Record).where(
                Record.user_id == user.id,
                Record.happened_on == data.happened_on,
                Record.category == data.category,
                Record.amount == data.amount,
                Record.type == RecordType(data.type),
            )
        )
        if existing.scalars().first():
            logger.warning(
                f"Duplicate record detected for user_id={user.id}: "
                f"{data.type} {data.category}/{data.subcategory} {data.amount} on {data.happened_on}"
            )
            raise ValueError(
                "Запись с такой датой, категорией и суммой уже существует 🔁"
            )

        record = Record(
            user_id=user.id,
            type=RecordType(data.type),
            category=data.category,
            subcategory=data.subcategory,
            amount=data.amount,
            currency=data.currency,
            happened_on=data.happened_on,
            description=data.description,
        )
        logger.info(
            f"Adding record for user_id={user.id}: "
            f"{record.type.value} {record.category} {record.amount}"
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_records(
        self,
        telegram_id: int,
        filters: RecordFilter | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Record]:
        base = (
            select(Record)
            .join(User)
            .where(User.telegram_id == telegram_id)
            .order_by(Record.happened_on.desc(), Record.id.desc())
            .offset(offset)
            .limit(limit)
        )
        query = self._apply_filters(base, filters)
        logger.debug(f"Fetching records for user_id={telegram_id} with limit={limit}")
        result = await self.session.execute(query)
        records = result.scalars().all()
        logger.info(f"Fetched {len(records)} records for telegram_id={telegram_id}")
        return records

    async def count_records(self, telegram_id: int, filters: RecordFilter | None = None) -> int:
        base = (
            select(func.count(Record.id))
            .join(User)
            .where(User.telegram_id == telegram_id)
        )
        query = self._apply_filters(base, filters)
        result = await self.session.execute(query)
        return int(result.scalar_one() or 0)

    async def get_record(self, telegram_id: int, record_id: int) -> Record | None:
        result = await self.session.execute(
            select(Record)
            .join(User)
            .where(User.telegram_id == telegram_id, Record.id == record_id)
        )
        return result.scalars().first()

    async def update_record(self, telegram_id: int, record_id: int, data: RecordCreate) -> Record | None:
        record = await self.get_record(telegram_id, record_id)
        if not record:
            return None

        record.type = RecordType(data.type)
        record.category = data.category
        record.subcategory = data.subcategory
        record.amount = data.amount
        record.currency = data.currency
        record.happened_on = data.happened_on
        record.description = data.description

        await self.session.flush()
        return record

    async def delete_record(self, telegram_id: int, record_id: int) -> bool:
        stmt = (
            delete(Record)
            .where(
                Record.id == record_id,
                Record.user_id == select(User.id).where(User.telegram_id == telegram_id).scalar_subquery(),
            )
        )
        result = await self.session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def aggregate_by_label(
        self,
        telegram_id: int,
        label_sql,
        filters: RecordFilter | None = None,
        only_expense: bool | None = None,
    ) -> Iterable[tuple[str, Decimal]]:
        base = (
            select(label_sql.label("label"), func.sum(Record.amount).label("total"))
            .join(User)
            .where(User.telegram_id == telegram_id)
            .group_by(label_sql)
            .order_by(label_sql.desc())
        )
        if only_expense is True:
            base = base.where(Record.type == RecordType.EXPENSE)
        if only_expense is False:
            base = base.where(Record.type == RecordType.INCOME)
        query = self._apply_filters(base, filters)
        rows = await self.session.execute(query)
        return [(row.label, row.total) for row in rows]

    async def avg_expense(
        self, telegram_id: int, filters: RecordFilter | None = None
    ) -> Decimal | None:
        base = (
            select(func.avg(Record.amount))
            .join(User)
            .where(User.telegram_id == telegram_id)
            .where(Record.type == RecordType.EXPENSE)
        )
        query = self._apply_filters(base, filters)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def max_expense(
        self, telegram_id: int, filters: RecordFilter | None = None
    ) -> Decimal | None:
        base = (
            select(func.max(Record.amount))
            .join(User)
            .where(User.telegram_id == telegram_id)
            .where(Record.type == RecordType.EXPENSE)
        )
        query = self._apply_filters(base, filters)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def total_by_type(
        self, telegram_id: int, record_type: RecordType, filters: RecordFilter | None = None
    ) -> Decimal:
        base = (
            select(func.coalesce(func.sum(Record.amount), 0))
            .join(User)
            .where(User.telegram_id == telegram_id)
            .where(Record.type == record_type)
        )
        query = self._apply_filters(base, filters)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def save_budget(self, telegram_id: int, plan) -> BudgetPlan:
        user = await self._get_or_create_user(telegram_id)
        budget = BudgetPlan(
            user_id=user.id,
            period_start=plan.period_start,
            period_end=plan.period_end,
            planned_expense=plan.planned_expense,
            planned_income=plan.planned_income,
        )
        logger.info(
            f"Saving budget for user_id={user.id}: "
            f"expense={budget.planned_expense}, income={budget.planned_income}"
        )
        self.session.add(budget)
        await self.session.flush()
        return budget

    async def get_last_budget(self, telegram_id: int) -> BudgetPlan | None:
        query = (
            select(BudgetPlan)
            .join(User)
            .where(User.telegram_id == telegram_id)
            .order_by(BudgetPlan.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        budget = result.scalars().first()
        if budget:
            logger.debug(f"Found last budget for telegram_id={telegram_id}")
        return budget
