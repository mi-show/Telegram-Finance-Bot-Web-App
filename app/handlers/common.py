import logging
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from ..cache import SimpleCache
from ..config import get_settings
from ..db import get_session
from ..models import UserSettings
from ..repositories.users import UserRepository
from ..schemas import BudgetPlanCreate, RecordCreate, RecordFilter
from ..services.aggregation_service import AggregationService, clear_stats_cache
from ..services.user_classifier import UserClassifier
from ..services.category_service import (
    get_categories_for_lang,
    get_subcategories_for_category,
    validate_category,
    find_closest_category,
    canonicalize_category,
    canonicalize_subcategory,
    localize_category,
    localize_subcategory,
)
from ..bot_budget_snapshot import _budget_snapshot
from ..services.ocr_service import OCRService, OCRConfigurationError
from ..services.ocr_quality_targets import (
    MIN_AMOUNT_CONFIDENCE_AUTO,
    MIN_ITEM_CONFIDENCE_AUTO,
    MIN_RECEIPT_OVERALL_CONFIDENCE_AUTO,
)
from ..services.receipt_parser import ReceiptParser
from ..services.record_service import RecordService
from .common_parts.constants import (
    ONBOARDING_INCOME_MARKER,
    QUICK_CATEGORY_PAGE_SIZE,
    SUPPORTED_CONVERSION_ORDER,
    SUPPORTED_LANGUAGES,
    SUPPORTED_ONBOARDING_CURRENCIES,
    TELEGRAM_SAFE_TEXT_LIMIT,
)
from .common_parts.currency import CurrencyService
from .common_parts.classifier_runtime import ClassifierRuntime
from .common_parts.i18n import (
    language_changed_text as _language_changed_text_impl,
    language_picker_kb as _language_picker_kb_impl,
    normalize_lang as _normalize_lang_impl,
    t as _t_impl,
    ui_variants as _ui_variants_impl,
)
from .common_parts.onboarding import OnboardingService
from .common_parts.ocr_utils import (
    group_recognized_items as _group_recognized_items_impl,
    is_item_confidently_recognized as _is_item_confidently_recognized_impl,
)
from .common_parts.quick_expense import (
    build_quick_category_candidates as build_quick_category_candidates_impl,
    dominant_category as dominant_category_impl,
    looks_like_gibberish as looks_like_gibberish_impl,
    parse_quick_expense as parse_quick_expense_impl,
    quick_category_keyboard as quick_category_keyboard_impl,
    quick_spelling_keyboard as quick_spelling_keyboard_impl,
    quick_subcategory_keyboard as quick_subcategory_keyboard_impl,
)
from .common_parts.telegram_utils import (
    answer_chunked as answer_chunked_impl,
    safe_edit_callback_message as safe_edit_callback_message_impl,
    split_message_chunks as split_message_chunks_impl,
)
from .route_context import ROUTE_CONTEXT_EXPORTS, build_route_context

logger = logging.getLogger(__name__)
settings = get_settings()

router = Router()

# OCR helpers (cached singletons)
receipts_dir = Path(__file__).parent.parent.parent / "data" / "receipts"
receipts_dir.mkdir(parents=True, exist_ok=True)
ocr_service = OCRService()
receipt_parser = ReceiptParser()
# Use DB-backed keyword dictionary for multilingual parsing and user learning.
user_classifier = UserClassifier()
# Store pending OCR results for confirmation (10 minutes TTL)
pending_receipts = SimpleCache(ttl_seconds=600)
# Store pending category selections for /add command (15 minutes TTL)
pending_add_records = SimpleCache(ttl_seconds=900)
# Store pending quick-expense manual confirmations (15 minutes TTL)
pending_quick_records = SimpleCache(ttl_seconds=900)
# Store pending /start onboarding state (currency -> income -> recurring) (1 hour TTL)
pending_start_onboarding = SimpleCache(ttl_seconds=3600)
currency_service = CurrencyService()
classifier_runtime = ClassifierRuntime(user_classifier)


def _normalize_lang(lang: str | None, fallback: str = "uk") -> str:
    return _normalize_lang_impl(lang, fallback)


def _t(lang: str | None, key: str, **kwargs) -> str:
    return _t_impl(lang, key, **kwargs)


def _ui_variants(key: str) -> list[str]:
    return _ui_variants_impl(key)


def _language_picker_kb(current_lang: str | None = None, origin: str = "set") -> InlineKeyboardMarkup:
    return _language_picker_kb_impl(current_lang, origin)


def _language_changed_text(lang: str) -> str:
    return _language_changed_text_impl(lang)


def _dominant_category(categories: list[str], fallback: str = "Other") -> str:
    return dominant_category_impl(categories, fallback)


def _fmt_amount(value: Decimal | None) -> str:
    return currency_service.fmt_amount(value)


def _parse_amount_input(raw_text: str) -> Decimal | None:
    return currency_service.parse_amount_input(raw_text)


def _normalize_currency_code(currency: str | None) -> str | None:
    return currency_service.normalize_currency_code(currency)


def _fallback_rates_by_usd() -> dict[str, Decimal]:
    return currency_service.fallback_rates_by_usd()


def _extract_live_rates(payload: dict) -> dict[str, Decimal] | None:
    return currency_service.extract_live_rates(payload)


async def _get_live_rates_by_usd() -> dict[str, Decimal]:
    return await currency_service.get_live_rates_by_usd()


def _convert_amount_with_rates(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    rates_by_usd: dict[str, Decimal],
) -> Decimal:
    return currency_service.convert_amount_with_rates(amount, from_currency, to_currency, rates_by_usd)


def _default_target_currency(source_currency: str) -> str:
    return currency_service.default_target_currency(source_currency)


def _onboarding_currency_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "onboarding_currency_uah"), callback_data="onbcur:UAH")
    kb.button(text=_t(lang, "onboarding_currency_usd"), callback_data="onbcur:USD")
    kb.button(text=_t(lang, "onboarding_currency_eur"), callback_data="onbcur:EUR")
    kb.adjust(1)
    return kb.as_markup()


async def _save_start_income_and_currency(
    session,
    telegram_id: int,
    lang: str,
    amount: Decimal,
    currency: str,
    *,
    create_recurring: bool = True,
) -> None:
    service = OnboardingService(session)
    await service.save_start_income_and_currency(
        telegram_id,
        lang,
        amount,
        currency,
        create_recurring=create_recurring,
    )


async def _save_start_currency(
    session,
    telegram_id: int,
    lang: str,
    currency: str,
) -> None:
    service = OnboardingService(session)
    await service.save_start_currency(
        telegram_id,
        lang,
        currency,
    )


def _is_item_confidently_recognized(
    item_name: str,
    category: str,
    source: str,
    confidence: float,
) -> bool:
    return _is_item_confidently_recognized_impl(item_name, category, source, confidence)


def _group_recognized_items(item_rows: list[dict]) -> dict[tuple[str, str], dict]:
    return _group_recognized_items_impl(item_rows)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, settings.date_format).date()


async def _prepare_classifier(session, telegram_id: int) -> str:
    return await classifier_runtime.prepare_classifier(session, telegram_id)


async def _get_user_language(telegram_id: int) -> str:
    return await classifier_runtime.get_user_language(telegram_id)


async def _resolve_user_currency(session, telegram_id: int) -> str:
    user_repo = UserRepository(session)
    user = await user_repo.get_or_create(telegram_id)
    result = await session.execute(select(UserSettings.currency).where(UserSettings.user_id == user.id))
    currency = result.scalar_one_or_none()
    normalized = _normalize_currency_code(currency) if isinstance(currency, str) else None
    return normalized or "UAH"


def _is_duplicate_record_error(exc: Exception) -> bool:
    return "Запись с такой датой, категорией и суммой уже существует" in str(exc)


async def format_limit_status(
    session,
    telegram_id: int,
    user_id: int,
    category: str,
    subcategory: str | None,
    lang: str,
    currency: str,
) -> str:
    """Return localized short suffix with limit status for a category/subcategory or empty string."""
    today = date.today()
    period_start = today.replace(day=1)
    if today.month == 12:
        period_end = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(today.year, today.month + 1, 1) - timedelta(days=1)

    snapshot = await _budget_snapshot(session, telegram_id, user_id, period_start, period_end, lang)
    limits = snapshot.get("category_limits", [])

    canonical = canonicalize_category(category) or category
    canonical_sub = None
    if subcategory:
        canonical_sub = canonicalize_subcategory(canonical, subcategory) or subcategory

    localized_cat = localize_category(canonical, lang) or canonical
    localized_sub = None
    if canonical_sub:
        localized_sub = localize_subcategory(canonical, canonical_sub, lang) or canonical_sub

    for item in limits:
        it_cat = item.get("category")
        it_sub = item.get("subcategory")
        if it_cat != localized_cat:
            continue
        # match subcategory presence/absence
        if localized_sub is None:
            if it_sub not in (None, ""):
                continue
        else:
            if it_sub != localized_sub:
                continue

        limit_val = item.get("limit")
        if limit_val is None:
            return ""
        spent_val = item.get("spent") or 0
        used_percent = item.get("used_percent") or 0
        remaining_val = None
        recommended_daily = None
        try:
            limit_dec = Decimal(str(limit_val))
        except Exception:
            limit_dec = Decimal("0")
        try:
            spent_dec = Decimal(str(spent_val))
        except Exception:
            spent_dec = Decimal("0")

        try:
            remaining_val = max(Decimal("0"), limit_dec - spent_dec)
        except Exception:
            remaining_val = Decimal("0")

        # recommended_daily_spend comes from snapshot per-limit payload
        try:
            recommended_daily = item.get("recommended_daily_spend")
        except Exception:
            recommended_daily = None

        return " " + _t(
            lang,
            "limit_suffix",
            limit=_fmt_amount(limit_dec),
            currency=currency,
            spent=_fmt_amount(spent_dec),
            used_percent=used_percent,
            remaining=_fmt_amount(remaining_val),
            recommended_daily=_fmt_amount(Decimal(str(recommended_daily))) if recommended_daily is not None else "-",
        )

    return ""



def _stash_duplicate_record_payload(owner_id: int, payload: RecordCreate) -> str:
    token = secrets.token_hex(8)
    pending_add_records.set(
        f"dupadd:{token}",
        {
            "owner_id": owner_id,
            "payload": payload,
        },
    )
    return token


def _get_stashed_duplicate_record_payload(token: str):
    return pending_add_records.get(f"dupadd:{token}")


def _delete_stashed_duplicate_record_payload(token: str) -> None:
    pending_add_records.delete(f"dupadd:{token}")


def _force_duplicate_add_kb(lang: str, token: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text={
            "uk": "➕ Все одно додати",
            "ru": "➕ Все равно добавить",
            "en": "➕ Add anyway",
        }.get(lang, "➕ Add anyway"),
        callback_data=f"dupadd:{token}",
    )
    kb.adjust(1)
    return kb.as_markup()


def _parse_filters(tokens: list[str]) -> RecordFilter:
    params: dict = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, raw = token.split("=", 1)
        key = key.lower()
        if key == "from":
            params["date_from"] = _parse_date(raw)
        elif key == "to":
            params["date_to"] = _parse_date(raw)
        elif key == "type":
            params["type"] = raw
        elif key in {"cat", "category"}:
            params["categories"] = [c.strip() for c in raw.split(",")]
        elif key == "min":
            params["min_amount"] = Decimal(raw)
        elif key == "max":
            params["max_amount"] = Decimal(raw)
        elif key == "q":
            params["description_query"] = raw
    return RecordFilter(**params) if params else RecordFilter()


def _parse_quick_expense(text: str) -> tuple[str, Decimal] | None:
    return parse_quick_expense_impl(text)


def _looks_like_gibberish(text: str) -> bool:
    return looks_like_gibberish_impl(text)


def _build_quick_category_candidates(
    description: str,
    telegram_id: int,
    language: str,
    predicted_category: str,
    limit: int = 64,
) -> list[str]:
    return build_quick_category_candidates_impl(
        user_classifier,
        description,
        telegram_id,
        language,
        predicted_category,
        limit,
    )


def _quick_category_keyboard(
    token: str,
    categories: list[str],
    page: int = 0,
    lang: str = "uk",
    page_size: int = QUICK_CATEGORY_PAGE_SIZE,
):
    return quick_category_keyboard_impl(token, categories, page=page, lang=lang, page_size=page_size)


def _quick_spelling_keyboard(token: str, lang: str = "uk"):
    return quick_spelling_keyboard_impl(token, lang=lang)


def _quick_subcategory_keyboard(token: str, subcategories: list[str], lang: str = "uk"):
    return quick_subcategory_keyboard_impl(token, subcategories, lang=lang)


def _split_message_chunks(text: str, chunk_size: int = TELEGRAM_SAFE_TEXT_LIMIT) -> list[str]:
    return split_message_chunks_impl(text, chunk_size=chunk_size)


async def _answer_chunked(message: Message, text: str, chunk_size: int = TELEGRAM_SAFE_TEXT_LIMIT) -> None:
    await answer_chunked_impl(message, text, chunk_size=chunk_size)


async def _safe_edit_callback_message(callback: CallbackQuery, text: str, reply_markup=None) -> bool:
    return await safe_edit_callback_message_impl(callback, text, reply_markup=reply_markup)


def _main_menu_kb(lang: str = "uk") -> ReplyKeyboardMarkup:
    webapp_button = (
        KeyboardButton(
            text=_t(lang, "menu_webapp"),
            web_app=WebAppInfo(url=settings.webapp_url),
        )
        if settings.webapp_url
        else KeyboardButton(text=_t(lang, "menu_webapp"))
    )

    kb = [
        [KeyboardButton(text=_t(lang, "menu_add_expense")), KeyboardButton(text=_t(lang, "menu_add_income"))],
        [KeyboardButton(text=_t(lang, "menu_list")), KeyboardButton(text=_t(lang, "menu_stats"))],
        [KeyboardButton(text=_t(lang, "menu_budget")), KeyboardButton(text=_t(lang, "menu_receipt"))],
        [webapp_button, KeyboardButton(text=_t(lang, "menu_language"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder=_t(lang, "menu_placeholder"),
    )


route_ctx = build_route_context(globals())

__all__ = (
    "router",
    "route_ctx",
    "ROUTE_CONTEXT_EXPORTS",
    "ONBOARDING_INCOME_MARKER",
    "_prepare_classifier",
    "_save_start_income_and_currency",
    "_split_message_chunks",
)



from . import routes_manual_add, routes_menu, routes_ocr, routes_quick_expense, routes_reports

router.include_router(routes_menu.router)
router.include_router(routes_quick_expense.router)
router.include_router(routes_manual_add.router)
router.include_router(routes_reports.router)
router.include_router(routes_ocr.router)
