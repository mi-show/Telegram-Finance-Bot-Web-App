from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

# Explicit export-contract for route modules.
ROUTE_CONTEXT_EXPORTS = (
    "_answer_chunked",
    "_build_quick_category_candidates",
    "_convert_amount_with_rates",
    "_default_target_currency",
    "_delete_stashed_duplicate_record_payload",
    "_dominant_category",
    "_force_duplicate_add_kb",
    "_fmt_amount",
    "_get_stashed_duplicate_record_payload",
    "_get_live_rates_by_usd",
    "_get_user_language",
    "_group_recognized_items",
    "_is_item_confidently_recognized",
    "_is_duplicate_record_error",
    "_language_changed_text",
    "_language_picker_kb",
    "_looks_like_gibberish",
    "_main_menu_kb",
    "_normalize_currency_code",
    "_normalize_lang",
    "_onboarding_currency_kb",
    "_parse_amount_input",
    "_parse_date",
    "_parse_filters",
    "_parse_quick_expense",
    "_prepare_classifier",
    "_quick_category_keyboard",
    "_quick_spelling_keyboard",
    "_quick_subcategory_keyboard",
    "_resolve_user_currency",
    "_safe_edit_callback_message",
    "_save_start_income_and_currency",
    "_save_start_currency",
    "_stash_duplicate_record_payload",
    "_t",
    "_ui_variants",
    "AggregationService",
    "BudgetPlanCreate",
    "clear_stats_cache",
    "date",
    "find_closest_category",
    "get_categories_for_lang",
    "get_session",
    "get_subcategories_for_category",
    "InlineKeyboardBuilder",
    "logger",
    "MIN_AMOUNT_CONFIDENCE_AUTO",
    "MIN_ITEM_CONFIDENCE_AUTO",
    "MIN_RECEIPT_OVERALL_CONFIDENCE_AUTO",
    "ocr_service",
    "OCRConfigurationError",
    "pending_add_records",
    "pending_quick_records",
    "pending_receipts",
    "pending_start_onboarding",
    "QUICK_CATEGORY_PAGE_SIZE",
    "receipt_parser",
    "RecordCreate",
    "RecordFilter",
    "RecordService",
    "secrets",
    "settings",
    "SUPPORTED_CONVERSION_ORDER",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_ONBOARDING_CURRENCIES",
    "user_classifier",
    "UserRepository",
    "validate_category",
)


def build_route_context(source: Mapping[str, Any]) -> SimpleNamespace:
    missing = sorted(name for name in ROUTE_CONTEXT_EXPORTS if name not in source)
    if missing:
        raise RuntimeError(f"route_ctx contract mismatch; missing={missing}, extra=[]")

    ctx = SimpleNamespace(**{name: source[name] for name in ROUTE_CONTEXT_EXPORTS})

    exported: set[str] = set(vars(ctx))
    expected: set[str] = {name for name in ROUTE_CONTEXT_EXPORTS}
    if exported != expected:
        missing = sorted(expected - exported)
        extra = sorted(exported - expected)
        raise RuntimeError(f"route_ctx contract mismatch; missing={missing}, extra={extra}")

    return ctx


__all__ = ("ROUTE_CONTEXT_EXPORTS", "build_route_context")
