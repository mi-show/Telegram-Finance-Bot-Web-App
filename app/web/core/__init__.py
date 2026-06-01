from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from sqlalchemy import delete, func, select

from ...models import AuditLog, BudgetPlan, CategoryBudgetLimit, Record, RecordType, RecurringEntry, User, UserSettings
from ...schemas import BudgetPlanCreate, RecordCreate, RecordFilter
from ...scripts.load_custom import CATEGORIES
from ...services.aggregation_service import AggregationService, clear_stats_cache
from ...services.category_service import (
    canonicalize_category,
    canonicalize_subcategory,
    expand_category_aliases,
    get_categories_for_lang,
    get_subcategories_for_category,
    localize_category,
    localize_subcategory,
)
from ...services.record_service import RecordService
from .base import (
    _learn_from_description,
    _localize_category_amounts,
    _normalize_setting_tokens,
    _record_audit_payload,
    _safe_lang,
    _serialize_audit_item,
    _serialize_record,
    _serialize_settings,
    _to_ascii,
    _to_float,
    _write_audit,
)
from .budget import (
    _auto_apply_recurring_for_current_month,
    _budget_snapshot,
    _build_filters,
    _carry_over_category_limits_from_previous_month,
    clear_limit_series_cache,
    _date_bounds,
    _due_date_for_period,
    _get_recurring_entry,
    get_limit_series_cache,
    _month_bounds,
    _month_shift,
    _pct_change,
    _prev_bounds,
    _recurring_income_delta_for_period,
    _recurring_income_expected_for_period,
    _recurring_income_spikes_in_actual_records,
    _recommendations,
    _serialize_recurring_entry,
    set_limit_series_cache,
)
from .currency import _convert_user_amounts_to_currency, clear_user_currency_conversion_anchors

ALLOWED_HIDDEN_BLOCKS = {
    "dashboardPie",
    "dashboardLine",
    "dashboardBar",
    "dashboardRecent",
}

AUDIT_DEFAULT_ACTIONS = (
    "record.create",
    "record.update",
    "record.delete",
    "budget.month.update",
    "budget.category_limits.update",
)

__all__ = (
    "ALLOWED_HIDDEN_BLOCKS",
    "AUDIT_DEFAULT_ACTIONS",
    "AggregationService",
    "AuditLog",
    "BudgetPlan",
    "BudgetPlanCreate",
    "CATEGORIES",
    "CategoryBudgetLimit",
    "Decimal",
    "FPDF",
    "Literal",
    "Record",
    "RecordCreate",
    "RecordFilter",
    "RecordService",
    "RecordType",
    "RecurringEntry",
    "User",
    "UserSettings",
    "XPos",
    "YPos",
    "_auto_apply_recurring_for_current_month",
    "_budget_snapshot",
    "_build_filters",
    "_carry_over_category_limits_from_previous_month",
    "clear_limit_series_cache",
    "_convert_user_amounts_to_currency",
    "_date_bounds",
    "_due_date_for_period",
    "_get_recurring_entry",
    "get_limit_series_cache",
    "_learn_from_description",
    "_localize_category_amounts",
    "_month_bounds",
    "_month_shift",
    "_normalize_setting_tokens",
    "_pct_change",
    "_prev_bounds",
    "_recurring_income_delta_for_period",
    "_recurring_income_expected_for_period",
    "_recurring_income_spikes_in_actual_records",
    "_recommendations",
    "_record_audit_payload",
    "_safe_lang",
    "_serialize_audit_item",
    "_serialize_record",
    "_serialize_recurring_entry",
    "_serialize_settings",
    "_to_ascii",
    "_to_float",
    "_write_audit",
    "set_limit_series_cache",
    "canonicalize_category",
    "canonicalize_subcategory",
    "cast",
    "clear_user_currency_conversion_anchors",
    "clear_stats_cache",
    "csv",
    "date",
    "datetime",
    "defaultdict",
    "delete",
    "expand_category_aliases",
    "func",
    "get_categories_for_lang",
    "get_subcategories_for_category",
    "io",
    "json",
    "localize_category",
    "localize_subcategory",
    "select",
    "timedelta",
)
