from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..db import Base, engine, ensure_schema
from ..models import User, UserSettings
from .core import _auto_apply_recurring_for_current_month
from .dependencies import _db_session, _get_auth_user
from .routes.api import router as api_router
from .routes.public import router as public_router

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSET_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
settings = get_settings()
logger = logging.getLogger(__name__)


async def _run_recurring_autopost_once(*, today: date | None = None) -> int:
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


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema()

    stop_event = asyncio.Event()
    recurring_task = None
    if settings.recurring_autopost_enabled:
        interval_seconds = max(60, int(settings.recurring_autopost_interval_seconds))
        recurring_task = asyncio.create_task(
            _run_recurring_autopost_loop(
                stop_event=stop_event,
                interval_seconds=interval_seconds,
            ),
            name="recurring-autopost-loop",
        )

    yield

    stop_event.set()
    if recurring_task is not None:
        try:
            await recurring_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Telegram Finance Web App",
    version="1.0.0",
    lifespan=_lifespan,
)
app.mount("/webapp/assets", StaticFiles(directory=STATIC_DIR), name="webapp-assets")
app.include_router(public_router)
app.include_router(api_router)


def _no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@app.middleware("http")
async def _webapp_no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in {"/webapp", "/webapp/"}:
        for key, value in _no_cache_headers().items():
            response.headers[key] = value
    elif path.startswith("/webapp/assets/"):
        for key, value in ASSET_CACHE_HEADERS.items():
            response.headers[key] = value
    return response
