import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class RecordType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    language: Mapped[str] = mapped_column(String(4), default="uk")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    records: Mapped[list["Record"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    budgets: Mapped[list["BudgetPlan"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    learned_keywords: Mapped[list["UserKeyword"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    settings: Mapped["UserSettings | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    category_limits: Mapped[list["CategoryBudgetLimit"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    recurring_entries: Mapped[list["RecurringEntry"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[RecordType] = mapped_column(Enum(RecordType))
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(String(8), default="UAH")
    happened_on: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="records")


class BudgetPlan(Base):
    __tablename__ = "budget_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    planned_expense: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True))
    planned_income: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="budgets")


class CategoryKeyword(Base):
    __tablename__ = "category_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    language: Mapped[str] = mapped_column(String(4), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phrase: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16), default="seed")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("language", "phrase", name="uq_keyword_lang_phrase"),
    )


class UserKeyword(Base):
    __tablename__ = "user_keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    phrase: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="learned_keywords")

    __table_args__ = (
        UniqueConstraint("user_id", "phrase", name="uq_user_keyword_phrase"),
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    theme: Mapped[str] = mapped_column(String(16), default="dark")
    currency: Mapped[str] = mapped_column(String(8), default="UAH")
    interface_language: Mapped[str] = mapped_column(String(4), default="uk")
    week_starts_on: Mapped[str] = mapped_column(String(16), default="monday")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_alert_mode: Mapped[str] = mapped_column(String(32), default="threshold_70")
    hidden_blocks: Mapped[str] = mapped_column(Text, default="[]")
    pinned_filters: Mapped[str] = mapped_column(Text, default="[]")
    favorite_categories: Mapped[str] = mapped_column(Text, default="[]")
    desktop_window_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desktop_window_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desktop_fullscreen_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_warning_percent: Mapped[int] = mapped_column(Integer, default=80)
    budget_danger_percent: Mapped[int] = mapped_column(Integer, default=100)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="settings")


class CategoryBudgetLimit(Base):
    __tablename__ = "category_budget_limits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="category_limits")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            "subcategory",
            "period_start",
            "period_end",
            name="uq_user_category_subcategory_limit_period",
        ),
    )


class RecurringEntry(Base):
    __tablename__ = "recurring_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    type: Mapped[RecordType] = mapped_column(Enum(RecordType))
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True))
    currency: Mapped[str] = mapped_column(String(8), default="UAH")
    day_of_month: Mapped[int] = mapped_column(Integer)
    reminder_days_before: Mapped[int] = mapped_column(Integer, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_confirmed_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminded_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="recurring_entries")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    user: Mapped["User"] = relationship(back_populates="audit_logs")
