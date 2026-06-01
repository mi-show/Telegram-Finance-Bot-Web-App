import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import SimpleCache
from ..config import get_settings
from ..models import Record, RecordType, User
from ..repositories.records import RecordRepository
from ..schemas import AggregatedAmount, BudgetPlanCreate, RecordFilter
from .category_service import canonicalize_category, canonicalize_subcategory, expand_category_aliases

logger = logging.getLogger(__name__)
settings = get_settings()
cache = SimpleCache(ttl_seconds=settings.cache_ttl_seconds)


def clear_stats_cache() -> None:
    """Invalidate cached aggregation results (used after mutations)."""
    cache.clear()


class AggregationService:
    """
    Encapsulates filtering and aggregation logic so handlers stay thin.
    """

    def __init__(self, session: AsyncSession, telegram_id: int):
        self.repo = RecordRepository(session)
        self.telegram_id = telegram_id

    async def _records_revision(self) -> str:
        """Return a lightweight DB revision token for this user's records."""
        stmt = (
            select(
                func.max(Record.updated_at).label("updated_at"),
                func.max(Record.id).label("max_id"),
            )
            .join(User, Record.user_id == User.id)
            .where(User.telegram_id == self.telegram_id)
        )
        row = (await self.repo.session.execute(stmt)).first()
        if not row:
            return "empty"

        updated_at = row.updated_at
        max_id = row.max_id
        if not updated_at and not max_id:
            return "empty"

        ts = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at or "none")
        return f"{int(max_id or 0)}:{ts}"

    def _label_sql(self, period: str):
        """Return SQL expression for grouping dates across dialects."""
        bind = self.repo.session.get_bind()
        dialect = bind.dialect.name if bind is not None else "sqlite"
        period = period.lower()

        if dialect.startswith("postgres"):
            trunc_map = {"day": "day", "week": "week", "month": "month"}
            if period not in trunc_map:
                raise ValueError("period must be one of: day, week, month")
            truncated = func.date_trunc(trunc_map[period], Record.happened_on)
            formats = {"day": "YYYY-MM-DD", "week": "IYYY-IW", "month": "YYYY-MM"}
            return func.to_char(truncated, formats[period])

        # default sqlite / others
        label_map = {
            "day": func.strftime("%Y-%m-%d", Record.happened_on),
            "week": func.strftime("%Y-W%W", Record.happened_on),
            "month": func.strftime("%Y-%m", Record.happened_on),
        }
        if period not in label_map:
            raise ValueError("period must be one of: day, week, month")
        return label_map[period]

    async def sum_by_period(
        self, period: str, filters: RecordFilter | None = None
    ) -> list[AggregatedAmount]:
        label_sql = self._label_sql(period)
        rows = await self.repo.aggregate_by_label(
            telegram_id=self.telegram_id,
            label_sql=label_sql,
            filters=filters,
            only_expense=True,
        )
        return [AggregatedAmount(label=label, amount=amount) for label, amount in rows]

    async def sum_by_category(
        self, filters: RecordFilter | None = None
    ) -> list[AggregatedAmount]:
        rows = await self.repo.aggregate_by_label(
            telegram_id=self.telegram_id,
            label_sql=Record.category,
            filters=filters,
            only_expense=True,
        )
        return [AggregatedAmount(label=label, amount=amount) for label, amount in rows]

    async def sum_by_subcategory(
        self, category: str | None = None, filters: RecordFilter | None = None
    ) -> list[dict]:
        """Get expenses grouped by subcategory (optionally filtered by main category)."""
        stmt = (
            select(
                Record.category,
                Record.subcategory,
                func.sum(Record.amount).label("total"),
            )
            .join(User, Record.user_id == User.id)
            .where(
                User.telegram_id == self.telegram_id,
                Record.type == RecordType.EXPENSE,
            )
        )

        if category:
            aliases = expand_category_aliases([category]) or [category]
            stmt = stmt.where(Record.category.in_(aliases))

        if filters:
            if filters.date_from:
                stmt = stmt.where(Record.happened_on >= filters.date_from)
            if filters.date_to:
                stmt = stmt.where(Record.happened_on <= filters.date_to)

        stmt = stmt.group_by(Record.category, Record.subcategory).order_by(func.sum(Record.amount).desc())

        rows = await self.repo.session.execute(stmt)
        grouped: dict[tuple[str, str | None], Decimal] = {}
        for cat, subcat, total in rows.all():
            canonical_category = canonicalize_category(cat) or cat
            normalized_subcategory = (subcat or "").strip() or None
            canonical_subcategory = (
                canonicalize_subcategory(canonical_category, normalized_subcategory)
                if normalized_subcategory
                else None
            )

            key = (canonical_category, canonical_subcategory)
            grouped[key] = grouped.get(key, Decimal("0")) + Decimal(total or 0)

        result = []
        for (cat, subcat), total in sorted(grouped.items(), key=lambda item: item[1], reverse=True):
            if subcat:
                label = f"{cat}({subcat})"
            else:
                label = cat
            result.append({"category": cat, "subcategory": subcat, "label": label, "amount": total or Decimal("0")})
        return result

    async def detailed_stats(self, filters: RecordFilter | None = None) -> dict:
        """Get detailed breakdown of expenses by category and subcategory."""
        revision = await self._records_revision()
        cache_key = f"detailed_stats_v2_{self.telegram_id}_{str(filters)}_{revision}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for {cache_key}")
            return cached
        
        by_subcategory = await self.sum_by_subcategory(filters=filters)
        
        # Group by main category
        by_category = {}
        for item in by_subcategory:
            cat = item["category"]
            if cat not in by_category:
                by_category[cat] = {"total": Decimal("0"), "items": []}
            by_category[cat]["total"] += item["amount"]
            if item["subcategory"]:
                by_category[cat]["items"].append(item)
        
        result = {"by_category": by_category, "items": by_subcategory}
        cache.set(cache_key, result)
        return result

    async def totals(self, filters: RecordFilter | None = None) -> dict[str, Decimal]:
        # Include DB revision so cache remains valid across bot/web processes.
        revision = await self._records_revision()
        cache_key = f"totals_{self.telegram_id}_{str(filters)}_{revision}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for {cache_key}")
            # Return a copy so callers can adjust totals without mutating cache entries.
            return dict(cached)
        
        logger.debug(f"Computing totals for telegram_id={self.telegram_id}")
        expenses = await self.repo.total_by_type(
            telegram_id=self.telegram_id, record_type=RecordType.EXPENSE, filters=filters
        )
        incomes = await self.repo.total_by_type(
            telegram_id=self.telegram_id, record_type=RecordType.INCOME, filters=filters
        )
        result = {
            "expenses": Decimal(expenses),
            "incomes": Decimal(incomes),
            "balance": Decimal(incomes) - Decimal(expenses),
        }
        logger.info(f"Totals: expenses={expenses}, incomes={incomes}")
        cache.set(cache_key, result)  # Cache the result
        return dict(result)

    async def averages(self, filters: RecordFilter | None = None) -> Decimal | None:
        logger.debug(f"Computing averages for telegram_id={self.telegram_id}")
        avg = await self.repo.avg_expense(self.telegram_id, filters)
        logger.debug(f"Average expense: {avg}")
        return avg

    async def max_expense(self, filters: RecordFilter | None = None) -> Decimal | None:
        logger.debug(f"Computing max expense for telegram_id={self.telegram_id}")
        max_exp = await self.repo.max_expense(self.telegram_id, filters)
        logger.debug(f"Max expense: {max_exp}")
        return max_exp

    async def save_budget(self, plan: BudgetPlanCreate):
        return await self.repo.save_budget(self.telegram_id, plan)

    async def last_budget(self):
        return await self.repo.get_last_budget(self.telegram_id)

    async def budget_status(
        self, plan: BudgetPlanCreate
    ) -> dict[str, Decimal | float | int]:
        filters = RecordFilter(
            date_from=plan.period_start,
            date_to=plan.period_end,
            type="expense",
        )
        spent = await self.repo.total_by_type(
            telegram_id=self.telegram_id, record_type=RecordType.EXPENSE, filters=filters
        )
        remaining = Decimal(plan.planned_expense) - Decimal(spent)
        percent = float(spent / plan.planned_expense * 100) if plan.planned_expense else 0
        return {
            "planned": Decimal(plan.planned_expense),
            "spent": Decimal(spent),
            "remaining": remaining,
            "used_percent": round(percent, 2),
        }

    async def simple_budget_suggestion(self) -> BudgetPlanCreate:
        today = date.today()
        start = today.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        end = next_month - timedelta(days=1)

        filters = RecordFilter(date_from=start, date_to=today)
        avg = await self.repo.avg_expense(self.telegram_id, filters)
        planned_expense = (avg or Decimal("0")) * Decimal(30)
        incomes = await self.repo.total_by_type(
            telegram_id=self.telegram_id, record_type=RecordType.INCOME, filters=filters
        )
        planned_income = Decimal(incomes) or Decimal("0")
        return BudgetPlanCreate(
            period_start=start,
            period_end=end,
            planned_expense=planned_expense,
            planned_income=planned_income,
        )
