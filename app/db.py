from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def ensure_schema():
    """
    Lightweight, code-first migration helper.
    Adds missing columns that were introduced after initial deployments.
    """
    async with engine.begin() as conn:
        dialect = engine.dialect.name

        async def _has_column(table: str, column: str) -> bool:
            if dialect == "sqlite":
                res = await conn.execute(text(f"PRAGMA table_info({table})"))
                cols = [row[1] for row in res]
                return column in cols
            if dialect in {"postgresql", "postgres"}:
                res = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name=:table AND column_name=:column"
                    ),
                    {"table": table, "column": column},
                )
                return res.scalar() is not None
            return True  # assume OK for other dialects

        async def _sqlite_table_columns(table: str) -> list[str]:
            if dialect != "sqlite":
                return []
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return [row[1] for row in res]

        async def _sqlite_has_expected_category_limit_unique() -> bool:
            if dialect != "sqlite":
                return True

            expected = ("user_id", "category", "subcategory", "period_start", "period_end")
            res = await conn.execute(text("PRAGMA index_list(category_budget_limits)"))
            for row in res:
                index_name = row[1]
                is_unique = bool(row[2])
                if not is_unique:
                    continue
                index_info = await conn.execute(text(f'PRAGMA index_info("{index_name}")'))
                cols = tuple(col_row[2] for col_row in index_info)
                if cols == expected:
                    return True
            return False

        async def _rebuild_category_budget_limits_sqlite() -> None:
            columns = await _sqlite_table_columns("category_budget_limits")
            has_subcategory = "subcategory" in columns
            has_created_at = "created_at" in columns
            has_updated_at = "updated_at" in columns

            await conn.execute(text("ALTER TABLE category_budget_limits RENAME TO category_budget_limits_old"))
            await conn.execute(
                text(
                    "CREATE TABLE category_budget_limits ("
                    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                    "user_id INTEGER NOT NULL, "
                    "category VARCHAR(64) NOT NULL, "
                    "subcategory VARCHAR(64), "
                    "period_start DATE NOT NULL, "
                    "period_end DATE NOT NULL, "
                    "limit_amount NUMERIC(12, 2) NOT NULL, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE, "
                    "UNIQUE(user_id, category, subcategory, period_start, period_end)"
                    ")"
                )
            )

            subcategory_expr = "subcategory" if has_subcategory else "NULL"
            created_at_expr = "created_at" if has_created_at else "CURRENT_TIMESTAMP"
            updated_at_expr = "updated_at" if has_updated_at else "CURRENT_TIMESTAMP"
            await conn.execute(
                text(
                    "INSERT INTO category_budget_limits"
                    " (id, user_id, category, subcategory, period_start, period_end, limit_amount, created_at, updated_at) "
                    "SELECT id, user_id, category, "
                    f"{subcategory_expr} AS subcategory, "
                    "period_start, period_end, limit_amount, "
                    f"{created_at_expr} AS created_at, "
                    f"{updated_at_expr} AS updated_at "
                    "FROM category_budget_limits_old"
                )
            )
            await conn.execute(text("DROP TABLE category_budget_limits_old"))

            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_budget_limits_user_id "
                    "ON category_budget_limits (user_id)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_budget_limits_category "
                    "ON category_budget_limits (category)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_budget_limits_subcategory "
                    "ON category_budget_limits (subcategory)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_budget_limits_period_start "
                    "ON category_budget_limits (period_start)"
                )
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_category_budget_limits_period_end "
                    "ON category_budget_limits (period_end)"
                )
            )

        # records.updated_at was added later; add it if missing
        if not await _has_column("records", "updated_at"):
            if dialect == "sqlite":
                await conn.execute(
                    text(
                        "ALTER TABLE records "
                        "ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    )
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text(
                        "ALTER TABLE records "
                        "ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now()"
                    )
                )

        # users.language was added for multilingual classification
        if not await _has_column("users", "language"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN language VARCHAR(4) DEFAULT 'uk'")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN language VARCHAR(4) DEFAULT 'uk'")
                )
        else:
            # ensure existing rows set to uk if empty
            if dialect == "sqlite":
                await conn.execute(text("UPDATE users SET language='uk' WHERE language IS NULL OR language=''"))
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("UPDATE users SET language='uk' WHERE language IS NULL OR language=''")
                )

        # user_settings.desktop_window_* for persistent desktop webapp window size
        if not await _has_column("user_settings", "desktop_window_width"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_window_width INTEGER")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_window_width INTEGER")
                )

        if not await _has_column("user_settings", "desktop_window_height"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_window_height INTEGER")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_window_height INTEGER")
                )

        if not await _has_column("user_settings", "desktop_fullscreen_enabled"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_fullscreen_enabled BOOLEAN DEFAULT 0")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN desktop_fullscreen_enabled BOOLEAN DEFAULT FALSE")
                )

        if not await _has_column("user_settings", "budget_warning_percent"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN budget_warning_percent INTEGER DEFAULT 80")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN budget_warning_percent INTEGER DEFAULT 80")
                )

        if not await _has_column("user_settings", "budget_danger_percent"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN budget_danger_percent INTEGER DEFAULT 100")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN budget_danger_percent INTEGER DEFAULT 100")
                )
        else:
            if dialect == "sqlite":
                await conn.execute(
                    text("UPDATE user_settings SET desktop_fullscreen_enabled=0 WHERE desktop_fullscreen_enabled IS NULL")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("UPDATE user_settings SET desktop_fullscreen_enabled=FALSE WHERE desktop_fullscreen_enabled IS NULL")
                )

        if not await _has_column("user_settings", "limit_alert_mode"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN limit_alert_mode VARCHAR(32) DEFAULT 'threshold_70'")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE user_settings ADD COLUMN limit_alert_mode VARCHAR(32) DEFAULT 'threshold_70'")
                )
        if dialect == "sqlite":
            await conn.execute(
                text(
                    "UPDATE user_settings "
                    "SET limit_alert_mode='threshold_70' "
                    "WHERE limit_alert_mode IS NULL OR limit_alert_mode=''"
                )
            )
        elif dialect in {"postgresql", "postgres"}:
            await conn.execute(
                text(
                    "UPDATE user_settings "
                    "SET limit_alert_mode='threshold_70' "
                    "WHERE limit_alert_mode IS NULL OR limit_alert_mode=''"
                )
            )

        if dialect == "sqlite":
            has_subcategory = await _has_column("category_budget_limits", "subcategory")
            has_expected_unique = await _sqlite_has_expected_category_limit_unique()
            if (not has_subcategory) or (not has_expected_unique):
                await _rebuild_category_budget_limits_sqlite()
        elif dialect in {"postgresql", "postgres"}:
            if not await _has_column("category_budget_limits", "subcategory"):
                await conn.execute(
                    text("ALTER TABLE category_budget_limits ADD COLUMN subcategory VARCHAR(64)")
                )

            await conn.execute(
                text("ALTER TABLE category_budget_limits DROP CONSTRAINT IF EXISTS uq_user_category_limit_period")
            )

            constraint_exists_res = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE table_name='category_budget_limits' "
                    "AND constraint_name='uq_user_category_subcategory_limit_period'"
                )
            )
            if constraint_exists_res.scalar() is None:
                await conn.execute(
                    text(
                        "ALTER TABLE category_budget_limits "
                        "ADD CONSTRAINT uq_user_category_subcategory_limit_period "
                        "UNIQUE (user_id, category, subcategory, period_start, period_end)"
                    )
                )

        # recurring_entries reminder tracking (avoid duplicate reminders)
        if not await _has_column("recurring_entries", "last_reminded_period"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE recurring_entries ADD COLUMN last_reminded_period DATE")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE recurring_entries ADD COLUMN last_reminded_period DATE")
                )

        if not await _has_column("recurring_entries", "last_reminded_at"):
            if dialect == "sqlite":
                await conn.execute(
                    text("ALTER TABLE recurring_entries ADD COLUMN last_reminded_at DATETIME")
                )
            elif dialect in {"postgresql", "postgres"}:
                await conn.execute(
                    text("ALTER TABLE recurring_entries ADD COLUMN last_reminded_at TIMESTAMPTZ")
                )
