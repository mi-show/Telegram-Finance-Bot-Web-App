import logging
import secrets
import tempfile
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections import Counter

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from ..cache import SimpleCache
from ..config import get_settings
from ..db import get_session
from ..repositories.users import UserRepository
from ..schemas import BudgetPlanCreate, RecordCreate, RecordFilter
from ..services.aggregation_service import AggregationService, clear_stats_cache
from ..services.category_classifier import CategoryClassifier
from ..services.user_classifier import UserClassifier
from ..services.category_service import (
    get_categories_for_lang,
    get_subcategories_for_category,
    validate_category,
    find_closest_category,
)
from ..scripts.load_custom import ensure_custom_keywords
from ..services.ocr_service import OCRService, OCRConfigurationError
from ..services.receipt_parser import ReceiptParser
from ..services.record_service import RecordService
from ..services.vocabulary_service import VocabularyService

logger = logging.getLogger(__name__)
settings = get_settings()

router = Router()

# OCR helpers (cached singletons)
receipts_dir = Path(__file__).parent.parent.parent / "data" / "receipts"
receipts_dir.mkdir(parents=True, exist_ok=True)
ocr_service = OCRService()
receipt_parser = ReceiptParser()
# Use UserClassifier for learning from user history - USE KEYWORD FILES FOR PROPER RECOGNITION
user_classifier = UserClassifier(use_keyword_files=True)
# Store pending OCR results for confirmation (10 minutes TTL)
pending_receipts = SimpleCache(ttl_seconds=600)
# Store pending category selections for /add command (15 minutes TTL)
pending_add_records = SimpleCache(ttl_seconds=900)
# Store pending quick-expense manual confirmations (15 minutes TTL)
pending_quick_records = SimpleCache(ttl_seconds=900)
_keywords_bootstrapped = False
_classifier_initialized = False
_user_history_loaded: set[int] = set()
_classifier_active_lang: str | None = None
QUICK_CATEGORY_PAGE_SIZE = 10
SUPPORTED_LANGUAGES = {"uk", "ru", "en"}

UI_TEXTS = {
    "ru": {
        "menu_add_expense": "➕ Добавить расход",
        "menu_add_income": "➕ Добавить доход",
        "menu_list": "📋 Список",
        "menu_stats": "📈 Статистика",
        "menu_budget": "📑 Бюджет",
        "menu_receipt": "🖼 Чек (отправь фото)",
        "menu_webapp": "📱 Финансы Web App",
        "menu_language": "🌐 Язык",
        "menu_placeholder": "Нажми кнопку или пришли фото чека",
        "pick_language_intro": "Сначала выбери язык бота. От выбора зависит, какие словари категорий и ключевых слов используются.",
        "start_help": (
            "Привет! Я помогу вести личные финансы.\n\n"
            "Команды:\n"
            "/add <income|expense> <category> <amount> <YYYY-MM-DD> [note]\n"
            "/list [from=YYYY-MM-DD to=YYYY-MM-DD type=expense cat=Food,Taxi min=10 max=200 q=coffee]\n"
            "/stats — быстрые статистики\n"
            "/language — сменить язык\n"
            "/budget set <plan_expense> <plan_income> <start> <end> — сохранить план\n"
            "Или просто пришли фото чека или напиши 'кофе 100'"
        ),
        "language_pick_prompt": "Выбери язык:",
        "language_saved_toast": "Язык сохранен",
        "language_changed": "✅ Язык переключен на Русский.",
        "language_menu_updated": "Кнопки меню обновлены.",
        "error_data": "Ошибка данных.",
        "error_unsupported_lang": "Неподдерживаемый язык.",
        "error_save_lang": "Не удалось сохранить язык.",
        "hint_send_receipt": "Пришли фото чека — я распознаю сумму и предложу категорию.",
        "hint_open_webapp": "Открой Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL не настроен. Добавь переменную окружения WEBAPP_URL.",
        "hint_add_expense_example": "Пример:\n/add expense Coffee 10.00 {today} [описание]",
        "hint_add_income_example": "Пример:\n/add income Salary 1000 {today} [описание]",
        "nav_prev": "⬅️ Назад",
        "nav_next": "➡️ Далее",
        "btn_spelling_yes": "✅ Да, написано правильно",
        "btn_spelling_no": "❌ Слово было написано неправильно",
        "btn_spelling_back": "↩️ Выбрать другую категорию",
        "btn_subcat_none": "Без подкатегории",
        "btn_subcat_back": "↩️ К категориям",
    },
    "uk": {
        "menu_add_expense": "➕ Додати витрату",
        "menu_add_income": "➕ Додати дохід",
        "menu_list": "📋 Список",
        "menu_stats": "📈 Статистика",
        "menu_budget": "📑 Бюджет",
        "menu_receipt": "🖼 Чек (надішли фото)",
        "menu_webapp": "📱 Фінанси Web App",
        "menu_language": "🌐 Мова",
        "menu_placeholder": "Натисни кнопку або надішли фото чека",
        "pick_language_intro": "Спочатку обери мову бота. Від цього залежить, які словники категорій і ключових слів використовуються.",
        "start_help": (
            "Привіт! Я допоможу вести особисті фінанси.\n\n"
            "Команди:\n"
            "/add <income|expense> <category> <amount> <YYYY-MM-DD> [note]\n"
            "/list [from=YYYY-MM-DD to=YYYY-MM-DD type=expense cat=Food,Taxi min=10 max=200 q=coffee]\n"
            "/stats — швидка статистика\n"
            "/language — змінити мову\n"
            "/budget set <plan_expense> <plan_income> <start> <end> — зберегти план\n"
            "Або просто надішли фото чека чи напиши 'кава 100'"
        ),
        "language_pick_prompt": "Обери мову:",
        "language_saved_toast": "Мову збережено",
        "language_changed": "✅ Мову змінено на Українську.",
        "language_menu_updated": "Кнопки меню оновлено.",
        "error_data": "Помилка даних.",
        "error_unsupported_lang": "Непідтримувана мова.",
        "error_save_lang": "Не вдалося зберегти мову.",
        "hint_send_receipt": "Надішли фото чека — я розпізнаю суму та запропоную категорію.",
        "hint_open_webapp": "Відкрий Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL не налаштовано. Додай змінну оточення WEBAPP_URL.",
        "hint_add_expense_example": "Приклад:\n/add expense Coffee 10.00 {today} [опис]",
        "hint_add_income_example": "Приклад:\n/add income Salary 1000 {today} [опис]",
        "nav_prev": "⬅️ Назад",
        "nav_next": "➡️ Далі",
        "btn_spelling_yes": "✅ Так, написано правильно",
        "btn_spelling_no": "❌ Слово написано неправильно",
        "btn_spelling_back": "↩️ Обрати іншу категорію",
        "btn_subcat_none": "Без підкатегорії",
        "btn_subcat_back": "↩️ До категорій",
    },
    "en": {
        "menu_add_expense": "➕ Add Expense",
        "menu_add_income": "➕ Add Income",
        "menu_list": "📋 List",
        "menu_stats": "📈 Stats",
        "menu_budget": "📑 Budget",
        "menu_receipt": "🖼 Receipt (send photo)",
        "menu_webapp": "📱 Finance Web App",
        "menu_language": "🌐 Language",
        "menu_placeholder": "Tap a button or send a receipt photo",
        "pick_language_intro": "First choose the bot language. It affects which category and keyword dictionaries are used.",
        "start_help": (
            "Hi! I will help you manage personal finances.\n\n"
            "Commands:\n"
            "/add <income|expense> <category> <amount> <YYYY-MM-DD> [note]\n"
            "/list [from=YYYY-MM-DD to=YYYY-MM-DD type=expense cat=Food,Taxi min=10 max=200 q=coffee]\n"
            "/stats — quick stats\n"
            "/language — change language\n"
            "/budget set <plan_expense> <plan_income> <start> <end> — save plan\n"
            "Or just send a receipt photo or type 'coffee 100'"
        ),
        "language_pick_prompt": "Choose a language:",
        "language_saved_toast": "Language saved",
        "language_changed": "✅ Language switched to English.",
        "language_menu_updated": "Menu buttons have been updated.",
        "error_data": "Invalid data.",
        "error_unsupported_lang": "Unsupported language.",
        "error_save_lang": "Failed to save language.",
        "hint_send_receipt": "Send a receipt photo and I will detect amount and category.",
        "hint_open_webapp": "Open Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL is not configured. Set WEBAPP_URL in environment.",
        "hint_add_expense_example": "Example:\n/add expense Coffee 10.00 {today} [note]",
        "hint_add_income_example": "Example:\n/add income Salary 1000 {today} [note]",
        "nav_prev": "⬅️ Back",
        "nav_next": "➡️ Next",
        "btn_spelling_yes": "✅ Yes, this spelling is correct",
        "btn_spelling_no": "❌ The word was misspelled",
        "btn_spelling_back": "↩️ Choose another category",
        "btn_subcat_none": "No subcategory",
        "btn_subcat_back": "↩️ Back to categories",
    },
}


def _normalize_lang(lang: str | None, fallback: str = "uk") -> str:
    value = (lang or fallback).lower()
    return value if value in SUPPORTED_LANGUAGES else fallback


def _t(lang: str | None, key: str, **kwargs) -> str:
    language = _normalize_lang(lang)
    template = UI_TEXTS.get(language, UI_TEXTS["ru"]).get(key) or UI_TEXTS["ru"].get(key, key)
    return template.format(**kwargs)


def _ui_variants(key: str) -> list[str]:
    return [UI_TEXTS[code][key] for code in ("uk", "ru", "en") if key in UI_TEXTS[code]]


def _language_picker_kb(current_lang: str | None = None, origin: str = "set") -> InlineKeyboardMarkup:
    current = _normalize_lang(current_lang)
    callback_origin = origin if origin in {"set", "start"} else "set"
    labels = {
        "uk": "Українська",
        "ru": "Русский",
        "en": "English",
    }
    flags = {
        "uk": "🇺🇦",
        "ru": "🇷🇺",
        "en": "🇬🇧",
    }
    kb = InlineKeyboardBuilder()
    for code in ("uk", "ru", "en"):
        prefix = "✅ " if code == current else ""
        kb.button(text=f"{prefix}{flags[code]} {labels[code]}", callback_data=f"lang:{callback_origin}:{code}")
    kb.adjust(1)
    return kb.as_markup()


def _language_changed_text(lang: str) -> str:
    return _t(lang, "language_changed")


def _dominant_category(categories: list[str], fallback: str = "Other") -> str:
    if not categories:
        return fallback
    counts = Counter(categories)
    return counts.most_common(1)[0][0]


def _fmt_amount(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else "?"


def _is_item_confidently_recognized(
    item_name: str,
    category: str,
    source: str,
    confidence: float,
) -> bool:
    trusted_sources = {"user_exact", "user_fuzzy", "override", "dictionary"}
    if source in trusted_sources:
        return True

    if (
        source == "ml"
        and confidence >= 0.8
        and category not in {"Other", "❗ Інше", "❗ Другое"}
        and not _looks_like_gibberish(item_name)
    ):
        return True

    return False


def _group_recognized_items(item_rows: list[dict]) -> dict[tuple[str, str], dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for row in item_rows:
        if not row.get("recognized"):
            continue
        price = row.get("price")
        if price is None:
            continue

        category = row.get("category") or "Other"
        subcategory = row.get("subcategory") or ""
        key = (category, subcategory)
        if key not in grouped:
            grouped[key] = {
                "total": Decimal("0"),
                "count": 0,
                "examples": [],
            }

        grouped[key]["total"] += price
        grouped[key]["count"] += 1
        if len(grouped[key]["examples"]) < 3:
            grouped[key]["examples"].append(row.get("name") or "")

    return grouped


def _parse_date(value: str) -> date:
    return datetime.strptime(value, settings.date_format).date()


async def _prepare_classifier(session, telegram_id: int) -> str:
    """Load user language and prepare classifier with minimal per-message overhead."""
    user_repo = UserRepository(session)
    vocab = VocabularyService(session)

    raw_lang = await user_repo.get_language(telegram_id)
    lang = _normalize_lang(raw_lang)
    if raw_lang != lang:
        await user_repo.set_language(telegram_id, lang)
        await session.commit()

    # Load user-specific history once per process; updates are kept in-memory by remember_user_phrase.
    global _user_history_loaded
    if telegram_id not in _user_history_loaded:
        try:
            await user_classifier.load_user_history(session, telegram_id)
            _user_history_loaded.add(telegram_id)
        except Exception as e:
            logger.warning(f"Failed to load user classifier history: {e}")

    # One-time bootstrap: fill DB keywords from our single custom source if empty
    global _keywords_bootstrapped
    if not _keywords_bootstrapped:
        try:
            await ensure_custom_keywords()
        except Exception as exc:
            logger.warning("Custom keyword bootstrap skipped: %s", exc)
        _keywords_bootstrapped = True
    # Expensive step (keyword loading + ML retrain) runs only when user language changes.
    # This makes classifier read keyword files for the selected bot language.
    global _classifier_initialized, _classifier_active_lang
    if not _classifier_initialized or _classifier_active_lang != lang:
        langs = [lang]
        try:
            extra_keywords = await vocab.keywords_for_languages(langs)
        except Exception as exc:  # table may be missing on first run
            logger.warning("Keyword lookup failed, using built-in dictionary only: %s", exc)
            extra_keywords = {}
        user_classifier.set_languages(langs, translate_to=lang, extra_keywords=extra_keywords)
        _classifier_initialized = True
        _classifier_active_lang = lang
    else:
        user_classifier.translate_to = lang

    return lang


async def _get_user_language(telegram_id: int) -> str:
    """Get user's language setting without loading full classifier."""
    try:
        async with get_session() as session:
            user_repo = UserRepository(session)
            return _normalize_lang(await user_repo.get_language(telegram_id))
    except Exception:
        return "uk"  # Fallback


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
    tokens = text.strip().replace(",", ".").split()
    if len(tokens) < 2:
        return None
    try:
        amount = Decimal(tokens[-1])
    except (InvalidOperation, ValueError):
        return None
    description = " ".join(tokens[:-1])
    if not description:
        return None
    return description, amount


def _looks_like_gibberish(text: str) -> bool:
    """Heuristic filter for random text/typos that should require manual category choice."""
    normalized = re.sub(r"[^a-zа-яёіїєґ]", "", text.lower())
    if len(normalized) < 3:
        return True

    vowels = set("aeiouyауоыиэяюёіїє")
    vowel_ratio = sum(1 for ch in normalized if ch in vowels) / len(normalized)
    unique_ratio = len(set(normalized)) / len(normalized)
    has_long_consonant_chain = bool(
        re.search(r"[bcdfghjklmnpqrstvwxyz]{5,}|[бвгджзйклмнпрстфхцчшщ]{5,}", normalized)
    )
    return vowel_ratio < 0.2 or unique_ratio < 0.3 or has_long_consonant_chain


def _build_quick_category_candidates(
    description: str,
    telegram_id: int,
    language: str,
    predicted_category: str,
    limit: int = 64,
) -> list[str]:
    """Build compact category suggestions from prediction + user history + ML candidates."""
    available = get_categories_for_lang(language)
    seen: set[str] = set()
    result: list[str] = []

    def add_candidate(cat: str | None) -> None:
        if not cat:
            return
        if cat in seen:
            return
        if available and cat not in available:
            return
        seen.add(cat)
        result.append(cat)

    add_candidate(predicted_category)

    for cat, _count in user_classifier.get_user_top_categories(telegram_id, limit=3):
        add_candidate(cat)

    for cat, _prob in user_classifier.get_ml_category_candidates(description, limit=4, language=language):
        add_candidate(cat)

    for cat in available:
        add_candidate(cat)
        if len(result) >= limit:
            break

    if "❗ Інше" in available:
        add_candidate("❗ Інше")
    elif "❗ Другое" in available:
        add_candidate("❗ Другое")

    return result[:limit]


def _quick_category_keyboard(
    token: str,
    categories: list[str],
    page: int = 0,
    lang: str = "uk",
    page_size: int = QUICK_CATEGORY_PAGE_SIZE,
):
    total = len(categories)
    if total == 0:
        page = 0
    else:
        max_page = (total - 1) // page_size
        page = max(0, min(page, max_page))

    start = page * page_size
    end = min(start + page_size, total)

    kb = InlineKeyboardBuilder()
    for idx in range(start, end):
        kb.button(text=categories[idx], callback_data=f"qcat:{token}:c:{idx}")

    if total > page_size:
        if page > 0:
            kb.button(text=_t(lang, "nav_prev"), callback_data=f"qcat:{token}:p:{page - 1}")
        if end < total:
            kb.button(text=_t(lang, "nav_next"), callback_data=f"qcat:{token}:p:{page + 1}")

    kb.adjust(2)
    return kb.as_markup()


def _quick_spelling_keyboard(token: str, lang: str = "uk"):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_spelling_yes"), callback_data=f"qspell:{token}:yes")
    kb.button(text=_t(lang, "btn_spelling_no"), callback_data=f"qspell:{token}:no")
    kb.button(text=_t(lang, "btn_spelling_back"), callback_data=f"qspell:{token}:back")
    kb.adjust(1)
    return kb.as_markup()


def _quick_subcategory_keyboard(token: str, subcategories: list[str], lang: str = "uk"):
    kb = InlineKeyboardBuilder()
    kb.button(text=_t(lang, "btn_subcat_none"), callback_data=f"qsub:{token}:none")
    for idx, subcategory in enumerate(subcategories):
        kb.button(text=subcategory, callback_data=f"qsub:{token}:{idx}")
    kb.button(text=_t(lang, "btn_subcat_back"), callback_data=f"qsub:{token}:back")
    kb.adjust(1, 2)
    return kb.as_markup()


async def _safe_edit_callback_message(callback: CallbackQuery, text: str, reply_markup=None) -> bool:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)  # type: ignore
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return False
        raise


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


@router.message(F.text.in_(_ui_variants("menu_list")))
async def btn_list(message: Message):
    await cmd_list(message)


@router.message(F.text.in_(_ui_variants("menu_stats")))
async def btn_stats(message: Message):
    await cmd_stats(message)


@router.message(F.text.in_(_ui_variants("menu_budget")))
async def btn_budget(message: Message):
    await cmd_budget(message)


@router.message(F.text.in_(_ui_variants("menu_receipt")))
async def btn_receipt(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    await message.answer(_t(lang, "hint_send_receipt"))


@router.message(F.text.in_(_ui_variants("menu_webapp")))
async def btn_webapp(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    if settings.webapp_url:
        await message.answer(_t(lang, "hint_open_webapp", url=settings.webapp_url))
        return
    await message.answer(_t(lang, "hint_webapp_unavailable"))


@router.message(F.text.in_(_ui_variants("menu_add_expense")))
async def btn_add_expense_hint(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    today = date.today().strftime(settings.date_format)
    await message.answer(_t(lang, "hint_add_expense_example", today=today))


@router.message(F.text.in_(_ui_variants("menu_add_income")))
async def btn_add_income_hint(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    today = date.today().strftime(settings.date_format)
    await message.answer(_t(lang, "hint_add_income_example", today=today))


@router.message(Command("start"))
async def cmd_start(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    await message.answer(
        _t(lang, "pick_language_intro"),
        reply_markup=_language_picker_kb(lang, origin="start"),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    await message.answer(
        _t(lang, "start_help"),
        reply_markup=_main_menu_kb(lang),
    )


@router.message(Command("language"))
async def cmd_language(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    await message.answer(_t(lang, "language_pick_prompt"), reply_markup=_language_picker_kb(lang, origin="set"))


@router.message(F.text.in_(_ui_variants("menu_language")))
async def btn_language(message: Message):
    await cmd_language(message)


@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery):
    current_lang = _normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(_t(current_lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer(_t(current_lang, "error_data"), show_alert=True)
        return

    flow_origin = parts[1] if parts[1] in {"set", "start"} else "set"
    new_lang = parts[2].lower()
    if new_lang not in SUPPORTED_LANGUAGES:
        await callback.answer(_t(current_lang, "error_unsupported_lang"), show_alert=True)
        return

    try:
        async with get_session() as session:
            user_repo = UserRepository(session)
            await user_repo.set_language(callback.from_user.id, new_lang)  # type: ignore
            await session.commit()
        if callback.message:
            await _safe_edit_callback_message(
                callback,
                _language_changed_text(new_lang),
                reply_markup=_language_picker_kb(new_lang, origin=flow_origin),
            )
            if flow_origin == "start":
                await callback.message.answer(  # type: ignore
                    _t(new_lang, "start_help"),
                    reply_markup=_main_menu_kb(new_lang),
                )
            else:
                await callback.message.answer(  # type: ignore
                    _t(new_lang, "language_menu_updated"),
                    reply_markup=_main_menu_kb(new_lang),
                )
        await callback.answer(_t(new_lang, "language_saved_toast"))
    except Exception as exc:
        logger.exception("Failed to save language: %s", exc)
        await callback.answer(_t(current_lang, "error_save_lang"), show_alert=True)


@router.message(F.text.regexp(r"(?i).+\s+\d+[\.,]?\d*$"))
async def quick_expense_freeform(message: Message):
    if not message.text:
        return
    try:
        async with get_session() as session:
            lang = await _prepare_classifier(session, message.from_user.id)  # type: ignore
            parsed = _parse_quick_expense(message.text)
            if not parsed:
                return

            description, amount = parsed
            logger.info(f"Quick expense: text='{message.text}' -> description='{description}', amount={amount}")

            category, subcategory, confidence, source = user_classifier.predict_with_user_context_confidence(
                description,
                message.from_user.id,  # type: ignore
                language=lang,
            )

            gibberish = _looks_like_gibberish(description)
            trusted_sources = {"user_exact", "user_fuzzy", "override", "dictionary"}
            needs_confirmation = (
                source not in trusted_sources
                or confidence < 0.8
                or (gibberish and source not in {"user_exact", "user_fuzzy"})
            )
            logger.info(
                "Quick classification: category='%s', subcategory='%s', source=%s, confidence=%.3f, gibberish=%s",
                category,
                subcategory,
                source,
                confidence,
                gibberish,
            )

            if needs_confirmation:
                categories = _build_quick_category_candidates(
                    description,
                    message.from_user.id,  # type: ignore
                    lang,
                    category,
                )
                if not categories:
                    categories = get_categories_for_lang(lang)[:6]

                token = secrets.token_hex(8)
                pending_quick_records.set(
                    token,
                    {
                        "description": description,
                        "amount": amount,
                        "happened_on": date.today(),
                        "language": lang,
                        "categories": categories,
                        "selected_category": None,
                        "selected_subcategory": None,
                        "predicted_subcategory": subcategory,
                        "category_page": 0,
                    },
                )

                await message.answer(
                    {
                        "uk": (
                            "🤖 Я не до кінця зрозумів, до якої категорії це віднести.\n"
                            f"Текст: '{description}' | Сума: {amount} UAH\n\n"
                            "Можеш обрати категорію вручну, і я запам'ятаю слово,\n"
                            "або сказати, що слово було написано неправильно."
                        ),
                        "ru": (
                            "🤖 Я не совсем понял, к какой категории это отнести.\n"
                            f"Текст: '{description}' | Сумма: {amount} UAH\n\n"
                            "Вы можете выбрать категорию вручную, и я запомню слово,\n"
                            "или сказать, что слово было написано неправильно."
                        ),
                        "en": (
                            "🤖 I am not sure which category this belongs to.\n"
                            f"Text: '{description}' | Amount: {amount} UAH\n\n"
                            "You can choose a category manually and I will remember this word,\n"
                            "or tell me the word was misspelled."
                        ),
                    }.get(lang, ""),
                    reply_markup=_quick_category_keyboard(token, categories, page=0, lang=lang),
                )
                return

            service = RecordService(session, message.from_user.id)  # type: ignore
            record = await service.add(
                RecordCreate(
                    type="expense",
                    category=category,
                    subcategory=subcategory,
                    amount=amount,
                    happened_on=date.today(),
                    description=description,
                )
            )
            await session.commit()
        clear_stats_cache()
        cat_display = f"{record.category}({record.subcategory})" if record.subcategory else record.category
        await message.answer(
            {
                "uk": f"✅ Додав {cat_display}: {record.amount} {record.currency} від {record.happened_on}",
                "ru": f"✅ Добавил {cat_display}: {record.amount} {record.currency} от {record.happened_on}",
                "en": f"✅ Added {cat_display}: {record.amount} {record.currency} on {record.happened_on}",
            }.get(lang, "")
        )
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
    except SQLAlchemyError as e:
        logger.exception(f"Quick expense DB error: {e}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше або /add.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже или /add.",
                "en": "❌ Database error. Try again later or use /add.",
            }.get(await _get_user_language(message.from_user.id), "❌ Database error.")  # type: ignore
        )
    except Exception as e:
        logger.exception(f"Quick expense error: {e}")
        await message.answer(
            {
                "uk": "❌ Не вдалося зберегти. Спробуйте /add або пізніше.",
                "ru": "❌ Не удалось сохранить. Попробуйте /add или позже.",
                "en": "❌ Could not save. Try /add or again later.",
            }.get(await _get_user_language(message.from_user.id), "❌ Could not save.")  # type: ignore
        )


@router.callback_query(F.data.startswith("qcat:"))
async def quick_category_selected(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    token = parts[1]
    pending = pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = _normalize_lang(pending.get("language", "uk"))

    action = "c"
    value_raw = ""
    if len(parts) >= 4:
        action = parts[2]
        value_raw = parts[3]
    else:
        value_raw = parts[2]

    categories = pending.get("categories", [])

    if action == "p":
        try:
            target_page = int(value_raw)
        except ValueError:
            await callback.answer(
                {
                    "uk": "Помилка навігації.",
                    "ru": "Ошибка навигации.",
                    "en": "Navigation error.",
                }.get(lang, "Navigation error."),
                show_alert=True,
            )
            return

        pending["category_page"] = max(0, target_page)
        pending_quick_records.set(token, pending)
        await _safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=_quick_category_keyboard(token, categories, page=pending["category_page"], lang=lang),
        )
        await callback.answer()
        return

    try:
        idx = int(value_raw)
    except ValueError:
        await callback.answer(
            {
                "uk": "Помилка вибору категорії.",
                "ru": "Ошибка выбора категории.",
                "en": "Category selection error.",
            }.get(lang, "Category selection error."),
            show_alert=True,
        )
        return

    if idx < 0 or idx >= len(categories):
        await callback.answer(
            {
                "uk": "Категорію не знайдено.",
                "ru": "Категория не найдена.",
                "en": "Category not found.",
            }.get(lang, "Category not found."),
            show_alert=True,
        )
        return

    selected_category = categories[idx]
    pending["selected_category"] = selected_category
    pending["selected_subcategory"] = None
    pending["category_page"] = idx // QUICK_CATEGORY_PAGE_SIZE
    pending_quick_records.set(token, pending)

    subcats = get_subcategories_for_category(selected_category, pending.get("language", "uk"))
    if subcats:
        await _safe_edit_callback_message(
            callback,
            {
                "uk": f"Ви обрали категорію: {selected_category}\n\nТепер оберіть підкатегорію:",
                "ru": f"Вы выбрали категорию: {selected_category}\n\nТеперь выберите подкатегорию:",
                "en": f"You selected category: {selected_category}\n\nNow choose a subcategory:",
            }.get(lang, ""),
            reply_markup=_quick_subcategory_keyboard(token, subcats, lang=lang),
        )
        await callback.answer()
        return

    await _safe_edit_callback_message(
        callback,
        {
            "uk": (
                f"Ви обрали категорію: {selected_category}\n\n"
                "Слово написано правильно?\n"
                "Якщо так, я запам'ятаю його для наступних записів."
            ),
            "ru": (
                f"Вы выбрали категорию: {selected_category}\n\n"
                "Слово написано правильно?\n"
                "Если да, я запомню его для следующих записей."
            ),
            "en": (
                f"You selected category: {selected_category}\n\n"
                "Is the word spelled correctly?\n"
                "If yes, I will remember it for future entries."
            ),
        }.get(lang, ""),
        reply_markup=_quick_spelling_keyboard(token, lang=lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qsub:"))
async def quick_subcategory_selected(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    token, decision = parts[1], parts[2]
    pending = pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = _normalize_lang(pending.get("language", "uk"))

    if decision == "back":
        categories = pending.get("categories", [])
        if not categories:
            await callback.answer(
                {
                    "uk": "Немає варіантів категорій.",
                    "ru": "Нет вариантов категорий.",
                    "en": "No category options.",
                }.get(lang, "No category options."),
                show_alert=True,
            )
            return

        selected_category = pending.get("selected_category")
        page = pending.get("category_page", 0)
        if selected_category in categories:
            page = categories.index(selected_category) // QUICK_CATEGORY_PAGE_SIZE

        await _safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=_quick_category_keyboard(token, categories, page=page, lang=lang),
        )
        await callback.answer()
        return

    selected_category = pending.get("selected_category")
    if not selected_category:
        await callback.answer(
            {
                "uk": "Спочатку оберіть категорію.",
                "ru": "Сначала выберите категорию.",
                "en": "Select a category first.",
            }.get(lang, "Select a category first."),
            show_alert=True,
        )
        return

    language = pending.get("language", "uk")
    subcats = get_subcategories_for_category(selected_category, language)

    if decision == "none":
        pending["selected_subcategory"] = None
        pending_quick_records.set(token, pending)
    else:
        try:
            idx = int(decision)
        except ValueError:
            await callback.answer(
                {
                    "uk": "Помилка вибору підкатегорії.",
                    "ru": "Ошибка выбора подкатегории.",
                    "en": "Subcategory selection error.",
                }.get(lang, "Subcategory selection error."),
                show_alert=True,
            )
            return

        if idx < 0 or idx >= len(subcats):
            await callback.answer(
                {
                    "uk": "Підкатегорію не знайдено.",
                    "ru": "Подкатегория не найдена.",
                    "en": "Subcategory not found.",
                }.get(lang, "Subcategory not found."),
                show_alert=True,
            )
            return

        pending["selected_subcategory"] = subcats[idx]
        pending_quick_records.set(token, pending)

    subcat_value = pending.get("selected_subcategory")
    subcat_label = subcat_value if subcat_value else _t(lang, "btn_subcat_none")
    await _safe_edit_callback_message(
        callback,
        {
            "uk": (
                f"Ви обрали категорію: {selected_category}\n"
                f"Підкатегорія: {subcat_label}\n\n"
                "Слово написано правильно?\n"
                "Якщо так, я запам'ятаю його для наступних записів."
            ),
            "ru": (
                f"Вы выбрали категорию: {selected_category}\n"
                f"Подкатегория: {subcat_label}\n\n"
                "Слово написано правильно?\n"
                "Если да, я запомню его для следующих записей."
            ),
            "en": (
                f"You selected category: {selected_category}\n"
                f"Subcategory: {subcat_label}\n\n"
                "Is the word spelled correctly?\n"
                "If yes, I will remember it for future entries."
            ),
        }.get(lang, ""),
        reply_markup=_quick_spelling_keyboard(token, lang=lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qspell:"))
async def quick_spelling_confirmed(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    token, decision = parts[1], parts[2]
    pending = pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = _normalize_lang(pending.get("language", "uk"))

    if decision == "back":
        categories = pending.get("categories", [])
        if not categories:
            await callback.answer(
                {
                    "uk": "Немає варіантів категорій.",
                    "ru": "Нет вариантов категорий.",
                    "en": "No category options.",
                }.get(lang, "No category options."),
                show_alert=True,
            )
            return

        selected_category = pending.get("selected_category")
        page = pending.get("category_page", 0)
        if selected_category in categories:
            page = categories.index(selected_category) // QUICK_CATEGORY_PAGE_SIZE

        await _safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=_quick_category_keyboard(token, categories, page=page, lang=lang),
        )
        await callback.answer()
        return

    if decision == "no":
        pending_quick_records.delete(token)
        await _safe_edit_callback_message(
            callback,
            {
                "uk": "Ок, запис не додаю.\nНадішліть витрату ще раз у форматі: опис сума",
                "ru": "Окей, запись не добавляю.\nОтправьте расход заново в формате: описание сумма",
                "en": "Okay, I will not add the record.\nSend expense again in format: description amount",
            }.get(lang, "")
        )
        await callback.answer()
        return

    remember_word = True
    selected_category = pending.get("selected_category")
    if not selected_category:
        await callback.answer(
            {
                "uk": "Спочатку оберіть категорію.",
                "ru": "Сначала выберите категорию.",
                "en": "Select a category first.",
            }.get(lang, "Select a category first."),
            show_alert=True,
        )
        return

    description = pending.get("description")
    amount = pending.get("amount")
    happened_on = pending.get("happened_on", date.today())
    selected_subcategory = pending.get("selected_subcategory")

    try:
        async with get_session() as session:
            service = RecordService(session, callback.from_user.id)  # type: ignore
            record = await service.add(
                RecordCreate(
                    type="expense",
                    category=selected_category,
                    subcategory=selected_subcategory,
                    amount=amount,
                    happened_on=happened_on,
                    description=description,
                )
            )

            remembered = False
            if remember_word and description:
                remembered = await user_classifier.remember_user_phrase(
                    session,
                    callback.from_user.id,
                    description,
                    selected_category,
                    selected_subcategory,
                )

            await session.commit()

        user_classifier._user_history_stats[callback.from_user.id][selected_category] += 1
        pending_quick_records.delete(token)
        clear_stats_cache()

        cat_display = f"{record.category}({record.subcategory})" if record.subcategory else record.category
        if remember_word and description and remembered:
            learn_suffix = {
                "uk": "\n💾 Слово збережено в словник.",
                "ru": "\n💾 Слово сохранено в словарь.",
                "en": "\n💾 Word saved to dictionary.",
            }.get(lang, "")
        elif remember_word and description:
            learn_suffix = {
                "uk": "\n⚠️ Не вдалося зберегти слово у словник.",
                "ru": "\n⚠️ Не удалось сохранить слово в словарь.",
                "en": "\n⚠️ Failed to save word to dictionary.",
            }.get(lang, "")
        else:
            learn_suffix = ""
        await _safe_edit_callback_message(
            callback,
            {
                "uk": f"✅ Додав {cat_display}: {record.amount} {record.currency} від {record.happened_on}{learn_suffix}",
                "ru": f"✅ Добавил {cat_display}: {record.amount} {record.currency} от {record.happened_on}{learn_suffix}",
                "en": f"✅ Added {cat_display}: {record.amount} {record.currency} on {record.happened_on}{learn_suffix}",
            }.get(lang, "")
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f"Quick spelling confirmation error: {e}")
        await callback.answer(
            {
                "uk": "❌ Не вдалося зберегти запис.",
                "ru": "❌ Не удалось сохранить запись.",
                "en": "❌ Failed to save record.",
            }.get(lang, "❌ Failed to save record."),
            show_alert=True,
        )


@router.message(Command("add"))
async def cmd_add(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    parts = message.text.split(maxsplit=5)  # type: ignore
    if len(parts) < 5:
        await message.answer(
            {
                "uk": f"Формат: /add <income|expense> <category> <amount> <{settings.date_format}> [note]",
                "ru": f"Формат: /add <income|expense> <category> <amount> <{settings.date_format}> [note]",
                "en": f"Format: /add <income|expense> <category> <amount> <{settings.date_format}> [note]",
            }.get(lang, "")
        )
        return

    _, type_raw, category_input, amount_raw, date_raw, *rest = parts
    description = rest[0] if rest else None

    try:
        amount = Decimal(amount_raw)
        happened_on = _parse_date(date_raw)
    except (InvalidOperation, ValueError) as exc:
        logger.exception(f"Amount/date parsing error: {exc}")
        await message.answer(
            {
                "uk": "⚠️ Помилка: неправильно вказано суму або дату",
                "ru": "⚠️ Ошибка: неправильно указана сумма или дата",
                "en": "⚠️ Error: invalid amount or date",
            }.get(lang, "⚠️ Error")
        )
        return

    # Validate record type
    if type_raw not in ("income", "expense"):
        await message.answer(
            {
                "uk": "⚠️ Тип має бути income або expense",
                "ru": "⚠️ Тип должен быть income или expense",
                "en": "⚠️ Type must be income or expense",
            }.get(lang, "⚠️ Type error")
        )
        return

    # Try to validate category against all known categories
    lang = "uk"  # Default language for /add command
    try:
        async with get_session() as session:
            user_repo = UserRepository(session)
            lang = (await user_repo.get_language(message.from_user.id) or "uk").lower() # type: ignore
            if lang not in SUPPORTED_LANGUAGES:
                lang = "uk"
    except Exception:
        pass

    # Check if category exists
    if validate_category(category_input, lang):
        # Valid category - proceed to save
        try:
            payload = RecordCreate(
                type=type_raw,  # type: ignore
                category=category_input,
                subcategory=None,
                amount=amount,
                happened_on=happened_on,
                description=description,
            )
            async with get_session() as session:
                service = RecordService(session, message.from_user.id)  # type: ignore
                record = await service.add(payload)
                await session.commit()
            clear_stats_cache()
            await message.answer(
                {
                    "uk": f"✅ Додано {record.type.value}: {record.category} {record.amount} {record.currency} від {record.happened_on}",
                    "ru": f"✅ Добавлено {record.type.value}: {record.category} {record.amount} {record.currency} от {record.happened_on}",
                    "en": f"✅ Added {record.type.value}: {record.category} {record.amount} {record.currency} on {record.happened_on}",
                }.get(lang, "")
            )
        except ValueError as e:
            logger.warning(f"Validation error during add: {e}")
            await message.answer(f"⚠️ {e}")
        except SQLAlchemyError as e:
            logger.exception(f"Database error during add: {e}")
            await message.answer(
                {
                    "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                    "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                    "en": "❌ Database error. Try later.",
                }.get(lang, "❌ Database error.")
            )
        except Exception as e:
            logger.exception(f"Unexpected error during add: {e}")
            await message.answer(
                {
                    "uk": f"❌ Помилка: {e}",
                    "ru": f"❌ Ошибка: {e}",
                    "en": f"❌ Error: {e}",
                }.get(lang, f"❌ Error: {e}")
            )
        return

    # Category not valid - show suggestions or let user choose
    closest_cat, match_score = find_closest_category(category_input, lang)
    
    # Store pending record data
    token = secrets.token_hex(8)
    pending_add_records.set(token, {
        "type": type_raw,
        "amount": amount,
        "happened_on": happened_on,
        "description": description,
        "original_input": category_input,
    })

    # Build keyboard with category suggestions
    kb = InlineKeyboardBuilder()
    
    # Add closest match if found
    if closest_cat and match_score > 0.5:
        kb.button(text=f"✓ {closest_cat} ({int(match_score*100)}%)", callback_data=f"add_cat:{token}:{closest_cat}")
    
    # Add all available categories
    available_cats = get_categories_for_lang(lang)
    for idx, cat in enumerate(available_cats):
        if cat != closest_cat:  # Don't duplicate
            kb.button(text=cat, callback_data=f"add_cat:{token}:{cat}")
    
    kb.adjust(1)
    
    await message.answer(
        {
            "uk": f"❓ Категорію '{category_input}' не знайдено.\n\nОберіть зі списку:",
            "ru": f"❓ Категория '{category_input}' не найдена.\n\nВыберите из списка:",
            "en": f"❓ Category '{category_input}' was not found.\n\nChoose one from the list:",
        }.get(lang, ""),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("add_cat:"))
async def add_category_selected(callback: CallbackQuery):
    """Handle category selection from /add command."""
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    
    token, category = parts[1], parts[2]
    record_data = pending_add_records.get(token)
    
    if not record_data:
        await callback.answer(
            {
                "uk": "Дані застаріли, використайте /add знову.",
                "ru": "Данные устарели, используйте /add снова.",
                "en": "Data expired, use /add again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return
    
    # Get user language
    lang = "uk"
    try:
        async with get_session() as session:
            user_repo = UserRepository(session)
            lang = (await user_repo.get_language(callback.from_user.id) or "uk").lower()
    except Exception:
        pass
    
    # Get subcategories for this category
    subcats = get_subcategories_for_category(category, lang)
    
    if not subcats:
        # No subcategories - save directly
        try:
            payload = RecordCreate(
                type=record_data["type"],  # type: ignore
                category=category,
                subcategory=None,
                amount=record_data["amount"],
                happened_on=record_data["happened_on"],
                description=record_data["description"],
            )
            async with get_session() as session:
                service = RecordService(session, callback.from_user.id)  # type: ignore
                record = await service.add(payload)
                await session.commit()
            clear_stats_cache()
            pending_add_records.delete(token)
            await callback.message.edit_text(  # type: ignore
                {
                    "uk": f"✅ Додано {record.type.value}: {record.category} {record.amount} {record.currency} від {record.happened_on}",
                    "ru": f"✅ Добавлено {record.type.value}: {record.category} {record.amount} {record.currency} от {record.happened_on}",
                    "en": f"✅ Added {record.type.value}: {record.category} {record.amount} {record.currency} on {record.happened_on}",
                }.get(lang, "")
            )
            await callback.answer()
        except Exception as e:
            logger.exception(f"Add category save error: {e}")
            await callback.answer(
                {
                    "uk": f"❌ Помилка: {e}",
                    "ru": f"❌ Ошибка: {e}",
                    "en": f"❌ Error: {e}",
                }.get(lang, f"❌ Error: {e}"),
                show_alert=True,
            )
        return
    
    # Show subcategory selection
    kb = InlineKeyboardBuilder()
    for subcat in subcats:
        kb.button(text=subcat, callback_data=f"add_subcat:{token}:{category}:{subcat}")
    kb.adjust(1)
    
    # Store updated record data with category
    record_data["category"] = category
    pending_add_records.set(token, record_data)
    
    await callback.message.edit_text(  # type: ignore
        {
            "uk": f"Категорія: {category}\n\nОберіть підкатегорію:",
            "ru": f"Категория: {category}\n\nВыберите подкатегорию:",
            "en": f"Category: {category}\n\nChoose a subcategory:",
        }.get(lang, ""),
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_subcat:"))
async def add_subcategory_selected(callback: CallbackQuery):
    """Handle subcategory selection from /add command."""
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    
    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    
    token, category, subcategory = parts[1], parts[2], parts[3]
    record_data = pending_add_records.get(token)
    
    if not record_data:
        await callback.answer(
            {
                "uk": "Дані застаріли, використайте /add знову.",
                "ru": "Данные устарели, используйте /add снова.",
                "en": "Data expired, use /add again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return
    
    # Save the record with category and subcategory
    try:
        payload = RecordCreate(
            type=record_data["type"],  # type: ignore
            category=category,
            subcategory=subcategory,
            amount=record_data["amount"],
            happened_on=record_data["happened_on"],
            description=record_data["description"],
        )
        async with get_session() as session:
            service = RecordService(session, callback.from_user.id)  # type: ignore
            record = await service.add(payload)
            await session.commit()
        clear_stats_cache()
        pending_add_records.delete(token)
        
        cat_display = f"{record.category}({record.subcategory})" if record.subcategory else record.category
        await callback.message.edit_text(  # type: ignore
            {
                "uk": f"✅ Додано {record.type.value}: {cat_display} {record.amount} {record.currency} від {record.happened_on}",
                "ru": f"✅ Добавлено {record.type.value}: {cat_display} {record.amount} {record.currency} от {record.happened_on}",
                "en": f"✅ Added {record.type.value}: {cat_display} {record.amount} {record.currency} on {record.happened_on}",
            }.get(lang, "")
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f"Add subcategory save error: {e}")
        await callback.answer(
            {
                "uk": f"❌ Помилка: {e}",
                "ru": f"❌ Ошибка: {e}",
                "en": f"❌ Error: {e}",
            }.get(lang, f"❌ Error: {e}"),
            show_alert=True,
        )


@router.callback_query(F.data.startswith("select_category:"))
async def select_category_for_unknown_word(callback: CallbackQuery):
    """Handle category selection for unrecognized words from quick expense."""
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    
    try:
        # Parse callback data: select_category:description:amount:category
        parts = callback.data.split(":", 3)
        if len(parts) < 4:
            await callback.answer(_t(lang, "error_data"), show_alert=True)
            return
        
        description = parts[1]
        amount_str = parts[2]
        category = parts[3]
        
        # Validate and parse amount
        try:
            amount = Decimal(amount_str.replace(",", "."))
        except (InvalidOperation, ValueError):
            await callback.answer(
                {
                    "uk": "Помилка суми.",
                    "ru": "Ошибка суммы.",
                    "en": "Invalid amount.",
                }.get(lang, "Invalid amount."),
                show_alert=True,
            )
            return
        
        telegram_id = callback.from_user.id  # type: ignore
        
        # Get subcategory for the selected category
        # Use classifier to find best subcategory
        lang = await _get_user_language(telegram_id)
        
        # Try to predict subcategory
        _, predicted_subcat = user_classifier.predict_with_user_context(
            description, telegram_id, language=lang
        )
        
        # If predicted subcategory doesn't match the selected category, set to None
        async with get_session() as session:
            all_subcats = get_subcategories_for_category(category, lang)
            if predicted_subcat not in all_subcats:
                predicted_subcat = None
        
        # Add record with selected category
        async with get_session() as session:
            service = RecordService(session, telegram_id)  # type: ignore
            record = await service.add(
                RecordCreate(
                    type="expense",
                    category=category,
                    subcategory=predicted_subcat,
                    amount=amount,
                    happened_on=date.today(),
                    description=description,
                )
            )

            await user_classifier.remember_user_phrase(
                session,
                telegram_id,
                description,
                category,
                predicted_subcat,
            )
            
            # Learn this word for future
            # Update history stats for this user
            user_classifier._user_history_stats[telegram_id][category] += 1
            
            await session.commit()
        
        clear_stats_cache()
        
        cat_display = f"{record.category}" 
        if record.subcategory:
            cat_display += f"({record.subcategory})"
        
        await callback.message.edit_text(  # type: ignore
            {
                "uk": (
                    f"✅ Додав {cat_display}: {record.amount} {record.currency} від {record.happened_on}\n"
                    f"💾 Запам'ятав '{description}' -> {category}"
                ),
                "ru": (
                    f"✅ Добавил {cat_display}: {record.amount} {record.currency} от {record.happened_on}\n"
                    f"💾 Запомнил '{description}' -> {category}"
                ),
                "en": (
                    f"✅ Added {cat_display}: {record.amount} {record.currency} on {record.happened_on}\n"
                    f"💾 Remembered '{description}' -> {category}"
                ),
            }.get(lang, "")
        )
        await callback.answer()
        
    except Exception as e:
        logger.exception(f"Select category error: {e}")
        await callback.answer(
            {
                "uk": f"❌ Помилка: {e}",
                "ru": f"❌ Ошибка: {e}",
                "en": f"❌ Error: {e}",
            }.get(lang, f"❌ Error: {e}"),
            show_alert=True,
        )


@router.message(Command("list"))
async def cmd_list(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    if not message.text:
        return
    tokens = message.text.split()[1:]
    filters = _parse_filters(tokens)

    try:
        async with get_session() as session:
            service = RecordService(session, message.from_user.id)  # type: ignore
            records = await service.list(filters, limit=settings.max_list_records)

        if not records:
            await message.answer(
                {
                    "uk": "📭 Немає записів за вибраними фільтрами.",
                    "ru": "📭 Нет записей по выбранным фильтрам.",
                    "en": "📭 No records for selected filters.",
                }.get(lang, "")
            )
            return

        lines = []
        for r in records[:settings.max_list_records]:
            cat_display = f"{r.category}({r.subcategory})" if r.subcategory else r.category
            line = f"{r.happened_on} {r.type.value} {cat_display}: {r.amount} {r.currency}"
            if r.description:
                line += f" - {r.description}"
            lines.append(line)

        if len(records) == settings.max_list_records:
            lines.append(
                {
                    "uk": f"\n(Показано перші {settings.max_list_records} записів)",
                    "ru": f"\n(Показаны первые {settings.max_list_records} записей)",
                    "en": f"\n(Showing first {settings.max_list_records} records)",
                }.get(lang, "")
            )

        await message.answer("\n".join(lines))
    except SQLAlchemyError as e:
        logger.exception(f"Database error in list: {e}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as e:
        logger.exception(f"Unexpected error in list: {e}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {e}",
                "ru": f"❌ Ошибка: {e}",
                "en": f"❌ Error: {e}",
            }.get(lang, f"❌ Error: {e}")
        )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        async with get_session() as session:
            agg = AggregationService(session, message.from_user.id)  # type: ignore
            totals = await agg.totals()
            day_sum = await agg.totals(RecordFilter(date_from=today, date_to=today))
            week_sum = await agg.totals(RecordFilter(date_from=week_start, date_to=today))
            month_sum = await agg.totals(RecordFilter(date_from=month_start, date_to=today))
            avg = await agg.averages()
            max_exp = await agg.max_expense()
            
            # Get detailed monthly breakdown by subcategory
            month_details = await agg.detailed_stats(RecordFilter(date_from=month_start, date_to=today))

        avg_val = f"{avg:.2f}" if avg is not None else "0.00"
        max_val = f"{max_exp:.2f}" if max_exp is not None else "0.00"
        
        # Build detailed breakdown
        breakdown_lines = []
        if month_details.get("by_category"):
            breakdown_lines.append(
                {
                    "uk": "💸 Витрати за категоріями (місяць):",
                    "ru": "💸 Расходы по категориям (месяц):",
                    "en": "💸 Expenses by category (month):",
                }.get(lang, "")
            )
            for cat, details in sorted(month_details["by_category"].items(), key=lambda x: x[1]["total"], reverse=True):
                total = details["total"]
                breakdown_lines.append(f"  {cat}: {total:.2f}")
                # Show subcategories if present
                for item in details.get("items", []):
                    if item["subcategory"]:
                        breakdown_lines.append(f"    └ {item['subcategory']}: {item['amount']:.2f}")
        
        breakdown_text = "\n".join(breakdown_lines) if breakdown_lines else ""
        
        stats_text = (
            {
                "uk": (
                    "📊 Статистика\n"
                    f"💰 Баланс: {totals['balance']:.2f}\n"
                    f"🗓 Витрати сьогодні: {day_sum['expenses']:.2f}\n"
                    f"📆 За тиждень: {week_sum['expenses']:.2f}\n"
                    f"🗓 За місяць: {month_sum['expenses']:.2f}\n"
                    f"📉 Середня витрата: {avg_val}\n"
                    f"🏁 Макс. витрата: {max_val}"
                ),
                "ru": (
                    "📊 Статистика\n"
                    f"💰 Баланс: {totals['balance']:.2f}\n"
                    f"🗓 Расходы сегодня: {day_sum['expenses']:.2f}\n"
                    f"📆 За неделю: {week_sum['expenses']:.2f}\n"
                    f"🗓 За месяц: {month_sum['expenses']:.2f}\n"
                    f"📉 Средний расход: {avg_val}\n"
                    f"🏁 Макс. расход: {max_val}"
                ),
                "en": (
                    "📊 Stats\n"
                    f"💰 Balance: {totals['balance']:.2f}\n"
                    f"🗓 Expenses today: {day_sum['expenses']:.2f}\n"
                    f"📆 This week: {week_sum['expenses']:.2f}\n"
                    f"🗓 This month: {month_sum['expenses']:.2f}\n"
                    f"📉 Average expense: {avg_val}\n"
                    f"🏁 Max expense: {max_val}"
                ),
            }.get(lang, "")
        )
        
        if breakdown_text:
            stats_text += "\n\n" + breakdown_text
        
        await message.answer(stats_text)
    except SQLAlchemyError as e:
        logger.exception(f"Database error in stats: {e}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as e:
        logger.exception(f"Unexpected error in stats: {e}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {e}",
                "ru": f"❌ Ошибка: {e}",
                "en": f"❌ Error: {e}",
            }.get(lang, f"❌ Error: {e}")
        )


@router.message(Command("budget"))
async def cmd_budget(message: Message):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    if not message.text:
        return
    parts = message.text.split()
    sub = parts[1] if len(parts) > 1 else None

    try:
        async with get_session() as session:
            agg = AggregationService(session, message.from_user.id)  # type: ignore

            if sub == "set":
                if len(parts) < 6:
                    await message.answer(
                        {
                            "uk": f"Формат: /budget set <plan_expense> <plan_income> <start={settings.date_format}> <end={settings.date_format}>",
                            "ru": f"Формат: /budget set <plan_expense> <plan_income> <start={settings.date_format}> <end={settings.date_format}>",
                            "en": f"Format: /budget set <plan_expense> <plan_income> <start={settings.date_format}> <end={settings.date_format}>",
                        }.get(lang, "")
                    )
                    return
                _, _, plan_expense, plan_income, start_raw, end_raw = parts[:6]
                try:
                    plan = BudgetPlanCreate(
                        planned_expense=Decimal(plan_expense),
                        planned_income=Decimal(plan_income),
                        period_start=_parse_date(start_raw),
                        period_end=_parse_date(end_raw),
                    )
                except (InvalidOperation, ValueError, ValidationError) as exc:
                    logger.exception(f"Input error in budget set: {exc}")
                    await message.answer(
                        {
                            "uk": f"⚠️ Помилка вводу: {exc}",
                            "ru": f"⚠️ Ошибка ввода: {exc}",
                            "en": f"⚠️ Input error: {exc}",
                        }.get(lang, f"⚠️ Input error: {exc}")
                    )
                    return

                await agg.save_budget(plan)
                await session.commit()
                clear_stats_cache()
                status = await agg.budget_status(plan)
                await message.answer(
                    {
                        "uk": (
                            f"🧾 Бюджет збережено.\nПлан: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Витрачено: {status['spent']} | ✅ Залишилось: {status['remaining']}"
                        ),
                        "ru": (
                            f"🧾 Бюджет сохранен.\nПлан: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Потрачено: {status['spent']} | ✅ Осталось: {status['remaining']}"
                        ),
                        "en": (
                            f"🧾 Budget saved.\nPlan: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Spent: {status['spent']} | ✅ Remaining: {status['remaining']}"
                        ),
                    }.get(lang, "")
                )
                return

            last = await agg.last_budget()
            await session.commit()
            if not last:
                plan = await agg.simple_budget_suggestion()
                await agg.save_budget(plan)
                await session.commit()
                clear_stats_cache()
                status = await agg.budget_status(plan)
                await message.answer(
                    {
                        "uk": (
                            "📑 Створив базовий місячний бюджет.\n"
                            f"💰 План витрат: {plan.planned_expense:.2f}\n"
                            f"✅ Залишилось: {status['remaining']:.2f}"
                        ),
                        "ru": (
                            "📑 Создал базовый месячный бюджет.\n"
                            f"💰 План расходов: {plan.planned_expense:.2f}\n"
                            f"✅ Осталось: {status['remaining']:.2f}"
                        ),
                        "en": (
                            "📑 Created a basic monthly budget.\n"
                            f"💰 Expense plan: {plan.planned_expense:.2f}\n"
                            f"✅ Remaining: {status['remaining']:.2f}"
                        ),
                    }.get(lang, "")
                )
                return

            plan = BudgetPlanCreate(
                planned_expense=last.planned_expense,
                planned_income=last.planned_income,
                period_start=last.period_start,
                period_end=last.period_end,
            )
            status = await agg.budget_status(plan)
            await message.answer(
                {
                    "uk": (
                        f"📊 Поточний бюджет {plan.period_start} - {plan.period_end}\n"
                        f"План: {plan.planned_expense} | 💸 Витрачено: {status['spent']} | ✅ Залишилось: {status['remaining']} ({status['used_percent']}%)"
                    ),
                    "ru": (
                        f"📊 Текущий бюджет {plan.period_start} - {plan.period_end}\n"
                        f"План: {plan.planned_expense} | 💸 Потрачено: {status['spent']} | ✅ Осталось: {status['remaining']} ({status['used_percent']}%)"
                    ),
                    "en": (
                        f"📊 Current budget {plan.period_start} - {plan.period_end}\n"
                        f"Plan: {plan.planned_expense} | 💸 Spent: {status['spent']} | ✅ Remaining: {status['remaining']} ({status['used_percent']}%)"
                    ),
                }.get(lang, "")
            )
    except SQLAlchemyError as e:
        logger.exception(f"Database error in budget: {e}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as e:
        logger.exception(f"Unexpected error in budget: {e}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {e}",
                "ru": f"❌ Ошибка: {e}",
                "en": f"❌ Error: {e}",
            }.get(lang, f"❌ Error: {e}")
        )


# --- OCR receipt flow ---


def _cache_ocr_payload(token: str, payload: dict):
    # Save payload and remember related tokens for easier cleanup.
    pending_receipts.set(token, payload)


def _pop_ocr_payload(token: str) -> dict | None:
    payload = pending_receipts.get(token)
    if payload:
        pending_receipts.delete(token)
        # also drop linked payloads if provided
        cleanup_tokens = payload.get("_cleanup") if isinstance(payload, dict) else None
        if cleanup_tokens:
            for tkn in cleanup_tokens:
                pending_receipts.delete(tkn)
                pending_quick_records.delete(tkn)
    return payload


@router.callback_query(F.data.startswith("ocr_unknown:"))
async def ocr_unknown_start(callback: CallbackQuery):
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return

    token = callback.data.split(":", 1)[1]
    pending = pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть чек знову.",
                "ru": "Данные устарели, отправьте чек снова.",
                "en": "Data expired, send receipt again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = _normalize_lang(pending.get("language", lang))

    categories = pending.get("categories", [])
    if not categories:
        await callback.answer(
            {
                "uk": "Немає варіантів категорій.",
                "ru": "Нет вариантов категорий.",
                "en": "No category options.",
            }.get(lang, "No category options."),
            show_alert=True,
        )
        return

    description = pending.get("description", "")
    amount = pending.get("amount")
    await callback.message.answer(  # type: ignore
        {
            "uk": (
                f"Невідома позиція:\n{description} — {_fmt_amount(amount)} UAH\n\n"
                "Оберіть категорію вручну:"
            ),
            "ru": (
                f"Неизвестная позиция:\n{description} — {_fmt_amount(amount)} UAH\n\n"
                "Выберите категорию вручную:"
            ),
            "en": (
                f"Unknown item:\n{description} — {_fmt_amount(amount)} UAH\n\n"
                "Choose category manually:"
            ),
        }.get(lang, ""),
        reply_markup=_quick_category_keyboard(token, categories, page=0, lang=lang),
    )
    await callback.answer()


@router.message(F.photo)
async def handle_receipt_photo(message: Message, bot: Bot):
    lang = await _get_user_language(message.from_user.id)  # type: ignore
    try:
        photo = message.photo[-1]  # type: ignore
        
        # Download photo using aiogram 3.4.1 API  
        file_info = await bot.get_file(photo.file_id)
        file_bytesio = await bot.download(file_info)
        
        # Ensure we have bytes
        if hasattr(file_bytesio, 'read'):
            file_bytes: bytes = file_bytesio.read()  # type: ignore
        else:
            file_bytes = file_bytesio  # type: ignore
        
        # Write to temporary file (always writable)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(file_bytes)
            path = Path(tmp.name)

        text = await ocr_service.extract_text(path)

        async with get_session() as session:
            lang = await _prepare_classifier(session, message.from_user.id)  # type: ignore

        parsed = receipt_parser.parse(text)
        amount = parsed.amount
        items = parsed.items
        when = parsed.date or date.today()
        description = parsed.description or parsed.merchant or "Чек"

        # Parse items into categories with confidence/source metadata.
        item_rows: list[dict] = []
        for item in items:
            cat, subcat, confidence, source = user_classifier.predict_with_user_context_confidence(
                item.name,
                message.from_user.id,  # type: ignore
                language=lang,
            )
            recognized = _is_item_confidently_recognized(item.name, cat, source, confidence)
            item_rows.append(
                {
                    "name": item.name,
                    "price": item.price,
                    "quantity": item.quantity,
                    "category": cat,
                    "subcategory": subcat,
                    "source": source,
                    "confidence": confidence,
                    "recognized": recognized,
                }
            )

        distinct_cats = {row["category"] for row in item_rows if row.get("category") and row.get("recognized")}
        total_from_items = sum((row["price"] or Decimal("0")) for row in item_rows) if item_rows else None
        if amount is None and total_from_items:
            amount = total_from_items

        if amount is None:
            await message.answer(
                {
                    "uk": "❌ Не вдалося знайти суму на чеку. Спробуйте інше фото.",
                    "ru": "❌ Не удалось найти сумму на чеке. Попробуйте другое фото.",
                    "en": "❌ Could not find total amount on receipt. Try another photo.",
                }.get(lang, "❌ Could not parse amount.")
            )
            path.unlink(missing_ok=True)
            return

        # Build payloads: single-record and per-item variants.
        if lang == "uk":
            uncertain_fallback = "❗ Інше"
        elif lang == "ru":
            uncertain_fallback = "❗ Другое"
        else:
            uncertain_fallback = "Other"

        dominant_cat = _dominant_category(list(distinct_cats), fallback=uncertain_fallback)

        single_token = secrets.token_hex(8)
        single_payload = {
            "records": [
                {
                    "type": "expense",
                    "category": dominant_cat,
                    "amount": str(amount),
                    "currency": "UAH",
                    "happened_on": when.isoformat(),
                    "description": f"{description} (OCR, {len(item_rows) or 1} поз.)",
                }
            ],
            "items": item_rows,
            "_cleanup": [],  # will be filled after second token is known
        }

        split_records = []
        for row in item_rows:
            if row["price"] is None or not row.get("recognized"):
                continue
            split_records.append(
                {
                    "type": "expense",
                    "category": row["category"],
                    "subcategory": row.get("subcategory"),
                    "amount": str(row["price"]),
                    "currency": "UAH",
                    "happened_on": when.isoformat(),
                    "description": row["name"],
                }
            )

        unknown_candidates = [
            row for row in item_rows if row.get("price") is not None and not row.get("recognized")
        ]
        unknown_entries: list[dict] = []
        for row in unknown_candidates:
            token = secrets.token_hex(8)
            categories = _build_quick_category_candidates(
                row["name"],
                message.from_user.id,  # type: ignore
                lang,
                row.get("category") or "Other",
            )
            pending_quick_records.set(
                token,
                {
                    "description": row["name"],
                    "amount": row["price"],
                    "happened_on": when,
                    "language": lang,
                    "categories": categories,
                    "selected_category": None,
                    "selected_subcategory": None,
                    "predicted_subcategory": row.get("subcategory"),
                    "category_page": 0,
                },
            )
            unknown_entries.append(
                {
                    "token": token,
                    "name": row["name"],
                    "price": row["price"],
                    "source": row.get("source"),
                    "confidence": row.get("confidence"),
                }
            )

        split_token = secrets.token_hex(8) if split_records else None
        split_payload = None
        if split_records:
            split_payload = {
                "records": split_records,
                "items": item_rows,
                "unknown_entries": unknown_entries,
                "_cleanup": [],
            }
        single_payload["unknown_entries"] = unknown_entries

        linked_tokens = [single_token]
        if split_token:
            linked_tokens.append(split_token)
        single_payload["_cleanup"] = linked_tokens
        if split_payload:
            split_payload["_cleanup"] = linked_tokens

        _cache_ocr_payload(single_token, single_payload)
        if split_token and split_payload:
            _cache_ocr_payload(split_token, split_payload)

        kb = InlineKeyboardBuilder()
        kb.button(
            text={
                "uk": f"💾 1 запис ({_fmt_amount(amount)})",
                "ru": f"💾 1 запись ({_fmt_amount(amount)})",
                "en": f"💾 1 record ({_fmt_amount(amount)})",
            }.get(lang, f"💾 1 record ({_fmt_amount(amount)})"),
            callback_data=f"ocr_save:{single_token}",
        )
        if split_token:
            kb.button(
                text={
                    "uk": f"💾 За позиціями ({len(split_records)})",
                    "ru": f"💾 По позициям ({len(split_records)})",
                    "en": f"💾 By items ({len(split_records)})",
                }.get(lang, f"💾 By items ({len(split_records)})"),
                callback_data=f"ocr_save:{split_token}",
            )
        kb.button(
            text={"uk": "🗑 Скасувати", "ru": "🗑 Отмена", "en": "🗑 Cancel"}.get(lang, "🗑 Cancel"),
            callback_data=f"ocr_cancel:{single_token}",
        )
        kb.adjust(2 if not split_token else 3)

        grouped = _group_recognized_items(item_rows)
        grouped_lines = []
        for (cat, subcat), details in sorted(grouped.items(), key=lambda x: x[1]["total"], reverse=True):
            cat_display = f"{cat}({subcat})" if subcat else cat
            grouped_lines.append(
                f"- {cat_display}: {_fmt_amount(details['total'])} ({details['count']} поз.)"
            )

        unknown_lines = []
        for idx, row in enumerate(unknown_entries[:6], start=1):
            conf = row.get("confidence")
            conf_txt = f", conf={conf:.2f}" if isinstance(conf, float) else ""
            unknown_lines.append(
                f"{idx}. {row['name']} — {_fmt_amount(row['price'])} [{row.get('source', '?')}{conf_txt}]"
            )

        known_block = "\n".join(grouped_lines) if grouped_lines else {
            "uk": "Немає впевнено розпізнаних позицій.",
            "ru": "Нет уверенно распознанных позиций.",
            "en": "No confidently recognized items.",
        }.get(lang, "No confidently recognized items.")
        unknown_block = "\n".join(unknown_lines) if unknown_lines else {
            "uk": "Немає",
            "ru": "Нет",
            "en": "None",
        }.get(lang, "None")

        await message.answer(
            {
                "uk": (
                    "Знайшов чек:\n"
                    f"Магазин: {parsed.merchant or '-'}\n"
                    f"Сума: {_fmt_amount(amount)}\n"
                    f"Дата: {when}\n"
                    f"\nРозпізнані категорії:\n{known_block}\n"
                    f"\nНевідомі позиції:\n{unknown_block}\n"
                    "\nЩо зберегти?"
                ),
                "ru": (
                    "Нашел чек:\n"
                    f"Магазин: {parsed.merchant or '-'}\n"
                    f"Сумма: {_fmt_amount(amount)}\n"
                    f"Дата: {when}\n"
                    f"\nРаспознанные категории:\n{known_block}\n"
                    f"\nНеизвестные позиции:\n{unknown_block}\n"
                    "\nЧто сохранить?"
                ),
                "en": (
                    "Receipt detected:\n"
                    f"Store: {parsed.merchant or '-'}\n"
                    f"Amount: {_fmt_amount(amount)}\n"
                    f"Date: {when}\n"
                    f"\nRecognized categories:\n{known_block}\n"
                    f"\nUnknown items:\n{unknown_block}\n"
                    "\nWhat should be saved?"
                ),
            }.get(lang, ""),
            reply_markup=kb.as_markup(),
        )
        # Clean up temp file after processing
        path.unlink(missing_ok=True)
    except OCRConfigurationError as e:
        logger.error(f"OCR is not configured: {e}", exc_info=True)
        await message.answer(
            {
                "uk": "OCR не налаштовано: встановіть tesseract-ocr і мовні пакети (eng/rus/ukr).",
                "ru": "OCR не настроен: установите tesseract-ocr и языковые пакеты (eng/rus/ukr).",
                "en": "OCR is not configured: install tesseract-ocr and language packs (eng/rus/ukr).",
            }.get(lang, "OCR is not configured.")
        )
    except Exception as e:
        logger.exception(f"OCR handler error: {e}")
        await message.answer(
            {
                "uk": "❌ Не вдалося обробити фото. Спробуйте ще раз.",
                "ru": "❌ Не удалось обработать фото. Попробуйте еще раз.",
                "en": "❌ Could not process photo. Please try again.",
            }.get(lang, "❌ Could not process photo.")
        )


@router.callback_query(F.data.startswith("ocr_save:"))
async def ocr_save(callback: CallbackQuery):
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    token = callback.data.split(":", 1)[1]  # type: ignore
    payload = _pop_ocr_payload(token)
    if not payload:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть фото ще раз.",
                "ru": "Данные устарели, пришлите фото еще раз.",
                "en": "Data expired, send photo again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    try:
        records_payload = payload.get("records") if isinstance(payload, dict) else None
        if not records_payload:
            records_payload = [payload]

        async with get_session() as session:
            service = RecordService(session, callback.from_user.id)
            saved = []
            for rec in records_payload:
                record = await service.add(
                    RecordCreate(
                        type=rec["type"],
                        category=rec["category"],
                        subcategory=rec.get("subcategory"),
                        amount=Decimal(rec["amount"]),
                        currency=rec.get("currency", "UAH"),
                        happened_on=date.fromisoformat(rec["happened_on"]),
                        description=rec.get("description"),
                    )
                )
                saved.append(record)
            await session.commit()

        unknown_entries = payload.get("unknown_entries", []) if isinstance(payload, dict) else []

        clear_stats_cache()
        if callback.message:
            if len(saved) == 1:
                rec = saved[0]
                await callback.message.answer(  # type: ignore
                    {
                        "uk": f"✅ Збережено {rec.category}: {rec.amount} {rec.currency} від {rec.happened_on}",
                        "ru": f"✅ Сохранил {rec.category}: {rec.amount} {rec.currency} от {rec.happened_on}",
                        "en": f"✅ Saved {rec.category}: {rec.amount} {rec.currency} on {rec.happened_on}",
                    }.get(lang, "")
                )
            else:
                text_lines = [
                    {
                        "uk": "✅ Збережено позиції:",
                        "ru": "✅ Сохранил позиции:",
                        "en": "✅ Saved items:",
                    }.get(lang, "✅ Saved items:"),
                    *[f"- {r.category}: {r.amount} {r.currency}" for r in saved],
                ]
                await callback.message.answer("\n".join(text_lines))  # type: ignore

            if unknown_entries:
                kb = InlineKeyboardBuilder()
                for idx, row in enumerate(unknown_entries, start=1):
                    kb.button(
                        text=f"❓ {idx}. {row['name']} — {_fmt_amount(row['price'])}",
                        callback_data=f"ocr_unknown:{row['token']}",
                    )
                kb.adjust(1)
                await callback.message.answer(  # type: ignore
                    {
                        "uk": "Я не впевнений щодо частини позицій. Натисніть на кожну, щоб обрати категорію та запам'ятати на майбутнє:",
                        "ru": "Я не уверен в части позиций. Нажмите на каждую, чтобы выбрать категорию и запомнить её на будущее:",
                        "en": "I am unsure about some items. Tap each one to choose category and remember it for future:",
                    }.get(lang, ""),
                    reply_markup=kb.as_markup(),
                )

        await callback.answer()
    except ValueError as e:
        logger.warning(f"OCR save validation error: {e}")
        if callback.message:
            await callback.message.answer(f"⚠️ {e}")  # type: ignore
        await callback.answer()
    except SQLAlchemyError as e:
        logger.exception(f"OCR save DB error: {e}")
        if callback.message:
            await callback.message.answer(  # type: ignore
                {
                    "uk": "❌ Помилка бази даних. Спробуйте знову.",
                    "ru": "❌ Ошибка базы данных. Попробуйте снова.",
                    "en": "❌ Database error. Try again.",
                }.get(lang, "❌ Database error.")
            )
        await callback.answer()
    except Exception as e:
        logger.exception(f"OCR save unexpected error: {e}")
        if callback.message:
            await callback.message.answer(  # type: ignore
                {
                    "uk": f"❌ Помилка: {e}",
                    "ru": f"❌ Ошибка: {e}",
                    "en": f"❌ Error: {e}",
                }.get(lang, f"❌ Error: {e}")
            )
        await callback.answer()


@router.callback_query(F.data.startswith("ocr_cancel:"))
async def ocr_cancel(callback: CallbackQuery):
    lang = await _get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:  # type: ignore
        await callback.answer(_t(lang, "error_data"), show_alert=True)
        return
    token = callback.data.split(":", 1)[1]  # type: ignore
    _pop_ocr_payload(token)
    await callback.message.answer(  # type: ignore
        {"uk": "🛑 Скасовано.", "ru": "🛑 Отменено.", "en": "🛑 Cancelled."}.get(lang, "🛑 Cancelled.")
    )
    await callback.answer()
