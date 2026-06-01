import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from aiogram import Bot, Dispatcher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .db import Base, engine, ensure_schema
from .handlers import common

logger = logging.getLogger(__name__)


def _next_month_start(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _format_money(amount: Decimal) -> str:
    value = Decimal(amount).quantize(Decimal("0.01"))
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


async def _run_recurring_autopost_once(*, today: date | None = None) -> int:
    from .models import User, UserSettings
    from .web.core.budget import _auto_apply_recurring_for_current_month

    total_created = 0
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        users_rows = await session.execute(
            select(User.id, User.telegram_id, UserSettings.currency)
            .outerjoin(UserSettings, UserSettings.user_id == User.id)
            .order_by(User.id.asc())
        )
        for user_id, telegram_id, currency in users_rows.all():
            if telegram_id is None:
                continue
            try:
                created = await _auto_apply_recurring_for_current_month(
                    session,
                    telegram_id=int(telegram_id),
                    user_id=int(user_id),
                    default_currency=(currency or "UAH"),
                    today=today,
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Recurring auto-post failed for user_id=%s telegram_id=%s",
                    user_id,
                    telegram_id,
                )
                continue
            total_created += int(created or 0)

    return total_created


async def _run_recurring_autopost_loop(*, stop_event: asyncio.Event, interval_seconds: int) -> None:
    logger.info("Recurring auto-post loop started (interval=%ss)", interval_seconds)
    while not stop_event.is_set():
        try:
            created = await _run_recurring_autopost_once()
            if created:
                logger.info("Recurring auto-post created %s record(s)", created)
        except Exception:
            logger.exception("Recurring auto-post cycle failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
    logger.info("Recurring auto-post loop stopped")


async def _run_recurring_reminders_once(bot: Bot, *, today: date | None = None) -> int:
    from .handlers.common_parts.i18n import normalize_lang, t
    from .models import RecurringEntry, RecordType, User, UserSettings
    from .web.core.budget import _due_date_for_period

    now_day = today or date.today()
    current_month_start = now_day.replace(day=1)
    next_month_start = _next_month_start(current_month_start)
    months_to_check = (current_month_start, next_month_start)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        rows = await session.execute(
            select(
                RecurringEntry,
                User.telegram_id,
                User.language,
                UserSettings.interface_language,
                UserSettings.notifications_enabled,
            )
            .join(User, RecurringEntry.user_id == User.id)
            .outerjoin(UserSettings, UserSettings.user_id == User.id)
            .where(
                User.telegram_id.is_not(None),
                RecurringEntry.is_active.is_(True),
                RecurringEntry.type == RecordType.EXPENSE,
                RecurringEntry.reminder_days_before > 0,
            )
            .order_by(User.id.asc(), RecurringEntry.id.asc())
        )

        sent = 0
        for entry, telegram_id, user_lang, settings_lang, notifications_enabled in rows.all():
            if telegram_id is None:
                continue
            if notifications_enabled is False:
                continue

            lang = normalize_lang(settings_lang or user_lang or "uk")

            for month_start in months_to_check:
                if entry.last_confirmed_period == month_start:
                    continue
                if entry.last_reminded_period == month_start:
                    continue

                due_date = _due_date_for_period(month_start, entry.day_of_month)
                reminder_days = max(int(entry.reminder_days_before or 0), 0)
                if reminder_days <= 0:
                    continue

                reminder_date = due_date - timedelta(days=reminder_days)
                if now_day < reminder_date:
                    continue
                if now_day > due_date:
                    continue

                amount_text = _format_money(Decimal(entry.amount))
                message = t(
                    lang,
                    "recurring_reminder",
                    title=(entry.title or "").strip() or "-",
                    amount=amount_text,
                    currency=(entry.currency or "UAH").upper(),
                    due_date=due_date.isoformat(),
                )

                try:
                    await bot.send_message(int(telegram_id), message)
                except Exception:
                    logger.exception(
                        "Failed to send recurring reminder (recurring_id=%s) to telegram_id=%s",
                        entry.id,
                        telegram_id,
                    )
                    continue

                entry.last_reminded_period = month_start
                entry.last_reminded_at = datetime.utcnow()
                await session.commit()
                sent += 1

                break

        return sent


async def _run_recurring_reminders_loop(
    bot: Bot,
    *,
    stop_event: asyncio.Event,
    interval_seconds: int,
) -> None:
    logger.info("Recurring reminders loop started (interval=%ss)", interval_seconds)
    while not stop_event.is_set():
        try:
            sent = await _run_recurring_reminders_once(bot)
            if sent:
                logger.info("Recurring reminders sent: %s", sent)
        except Exception:
            logger.exception("Recurring reminders cycle failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
    logger.info("Recurring reminders loop stopped")


async def on_startup():
    logging.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # lightweight migrations for schema drift
    await ensure_schema()
    logging.info("Database tables created.")

    from .scripts.sanity_check_seed_keywords import run_seed_sanity_check

    errors, warnings = run_seed_sanity_check()
    for warning in warnings[:20]:
        logging.warning("Keyword sanity warning: %s", warning)
    if errors:
        for error in errors[:20]:
            logging.error("Keyword sanity error: %s", error)
        raise RuntimeError(f"Seed keyword sanity check failed with {len(errors)} errors")
    
    # Bootstrap seed keywords from repository JSON.
    from .scripts.load_custom import ensure_custom_keywords
    try:
        await ensure_custom_keywords()
    except Exception as e:
        logging.error(f"Failed to load custom keywords on startup: {e}")

    try:
        await common.classifier_runtime.warmup()
    except Exception as e:
        logging.warning(f"Classifier warmup skipped: {e}")


async def on_shutdown():
    logging.info("Shutting down gracefully...")
    await engine.dispose()
    logging.info("Database connections closed.")


async def main():
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logging.info("Starting bot...")
    
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.include_router(common.router)

    await on_startup()

    stop_event = asyncio.Event()
    background_tasks: list[asyncio.Task] = []
    if settings.recurring_autopost_enabled:
        interval_seconds = max(60, int(settings.recurring_autopost_interval_seconds))
        background_tasks.append(
            asyncio.create_task(
                _run_recurring_autopost_loop(stop_event=stop_event, interval_seconds=interval_seconds),
                name="recurring-autopost-loop",
            )
        )

    # Reminders are controlled by per-user notifications_enabled.
    reminder_interval = max(300, int(settings.recurring_autopost_interval_seconds))
    background_tasks.append(
        asyncio.create_task(
            _run_recurring_reminders_loop(bot, stop_event=stop_event, interval_seconds=reminder_interval),
            name="recurring-reminders-loop",
        )
    )
    
    try:
        logging.info("Clearing webhook and pending updates before polling...")
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logging.warning("Failed to delete webhook before polling: %s", e)

        logging.info("Bot polling started")
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        for task in background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
