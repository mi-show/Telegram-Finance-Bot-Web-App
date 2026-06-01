import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from aiogram.utils.keyboard import InlineKeyboardBuilder

from ...services.category_service import get_categories_for_lang
from .constants import QUICK_CATEGORY_PAGE_SIZE
from .i18n import t


def dominant_category(categories: list[str], fallback: str = "Other") -> str:
    if not categories:
        return fallback
    counts = Counter(categories)
    return counts.most_common(1)[0][0]


def parse_quick_expense(text: str) -> tuple[str, Decimal] | None:
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


def looks_like_gibberish(text: str) -> bool:
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


def build_quick_category_candidates(
    user_classifier,
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


def quick_category_keyboard(
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
            kb.button(text=t(lang, "nav_prev"), callback_data=f"qcat:{token}:p:{page - 1}")
        if end < total:
            kb.button(text=t(lang, "nav_next"), callback_data=f"qcat:{token}:p:{page + 1}")

    kb.adjust(2)
    return kb.as_markup()


def quick_spelling_keyboard(token: str, lang: str = "uk"):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_spelling_yes"), callback_data=f"qspell:{token}:yes")
    kb.button(text=t(lang, "btn_spelling_no"), callback_data=f"qspell:{token}:no")
    kb.button(text=t(lang, "btn_spelling_back"), callback_data=f"qspell:{token}:back")
    kb.adjust(1)
    return kb.as_markup()


def quick_subcategory_keyboard(token: str, subcategories: list[str], lang: str = "uk"):
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_subcat_none"), callback_data=f"qsub:{token}:none")
    for idx, subcategory in enumerate(subcategories):
        kb.button(text=subcategory, callback_data=f"qsub:{token}:{idx}")
    kb.button(text=t(lang, "btn_subcat_back"), callback_data=f"qsub:{token}:back")
    kb.adjust(1, 2)
    return kb.as_markup()
