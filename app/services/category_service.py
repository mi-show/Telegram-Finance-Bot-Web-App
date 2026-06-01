"""Category management and validation service."""
import unicodedata
from typing import Dict, List, Tuple

from ..scripts.load_custom import CATEGORIES

_DEFAULT_LANGUAGE = "uk"
_CANONICAL_LANGUAGE = "en" if "en" in CATEGORIES else next(iter(CATEGORIES.keys()), "uk")
_CANONICAL_ORDER = list(CATEGORIES.get(_CANONICAL_LANGUAGE, {}).keys())


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in normalized)
    return " ".join(cleaned.split())


def _build_category_maps() -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    canonical_to_local: dict[str, dict[str, str]] = {canonical: {} for canonical in _CANONICAL_ORDER}
    exact_aliases: dict[str, str] = {}
    normalized_aliases: dict[str, str] = {}

    for lang, categories in CATEGORIES.items():
        labels = list(categories.keys())
        if len(labels) == len(_CANONICAL_ORDER):
            pairs = zip(_CANONICAL_ORDER, labels)
        elif lang == _CANONICAL_LANGUAGE:
            pairs = ((label, label) for label in labels)
        else:
            # Fallback for inconsistent datasets: treat local labels as canonical.
            pairs = ((label, label) for label in labels)

        for canonical, local_label in pairs:
            canonical_to_local.setdefault(canonical, {})[lang] = local_label
            exact_aliases[local_label] = canonical
            exact_aliases[canonical] = canonical
            normalized_aliases[_normalize_label(local_label)] = canonical
            normalized_aliases[_normalize_label(canonical)] = canonical

    return canonical_to_local, exact_aliases, normalized_aliases


def _subcategories_list(value: object) -> list[str]:
    if isinstance(value, dict):
        return list(value.keys())
    if isinstance(value, list):
        return list(value)
    return []


def _build_subcategory_maps() -> tuple[
    dict[str, dict[str, dict[str, str]]],
    dict[tuple[str, str], str],
    dict[tuple[str, str], str],
]:
    canonical_to_local: dict[str, dict[str, dict[str, str]]] = {}
    exact_aliases: dict[tuple[str, str], str] = {}
    normalized_aliases: dict[tuple[str, str], str] = {}

    for canonical_category in _CANONICAL_ORDER:
        local_categories = _CANONICAL_TO_LOCAL.get(canonical_category, {})
        canonical_category_label = local_categories.get(_CANONICAL_LANGUAGE, canonical_category)
        canonical_subcategories = _subcategories_list(
            CATEGORIES.get(_CANONICAL_LANGUAGE, {}).get(canonical_category_label)
        )
        if not canonical_subcategories:
            canonical_subcategories = _subcategories_list(
                CATEGORIES.get(_CANONICAL_LANGUAGE, {}).get(canonical_category)
            )
        if not canonical_subcategories:
            continue

        for lang in CATEGORIES:
            local_category = local_categories.get(lang)
            if not local_category:
                continue

            local_subcategories = _subcategories_list(CATEGORIES.get(lang, {}).get(local_category))
            if not local_subcategories:
                continue

            if len(local_subcategories) == len(canonical_subcategories):
                pairs = zip(canonical_subcategories, local_subcategories)
            elif lang == _CANONICAL_LANGUAGE:
                pairs = ((label, label) for label in canonical_subcategories)
            else:
                # Fallback for inconsistent datasets: treat local labels as canonical.
                pairs = ((label, label) for label in local_subcategories)

            for canonical_subcategory, local_subcategory in pairs:
                canonical_to_local.setdefault(canonical_category, {}).setdefault(canonical_subcategory, {})[lang] = local_subcategory
                exact_aliases[(canonical_category, local_subcategory)] = canonical_subcategory
                exact_aliases[(canonical_category, canonical_subcategory)] = canonical_subcategory
                normalized_aliases[(canonical_category, _normalize_label(local_subcategory))] = canonical_subcategory
                normalized_aliases[(canonical_category, _normalize_label(canonical_subcategory))] = canonical_subcategory

    return canonical_to_local, exact_aliases, normalized_aliases


_CANONICAL_TO_LOCAL, _EXACT_ALIASES, _NORMALIZED_ALIASES = _build_category_maps()
_SUBCATEGORY_CANONICAL_TO_LOCAL, _SUBCATEGORY_EXACT_ALIASES, _SUBCATEGORY_NORMALIZED_ALIASES = _build_subcategory_maps()


def get_all_categories() -> Dict[str, List[str]]:
    """
    Get all main categories by language.
    Returns {lang: [category, category, ...]}
    """
    result = {}
    for lang, cats_dict in CATEGORIES.items():
        result[lang] = list(cats_dict.keys())
    return result


def get_categories_for_lang(language: str) -> List[str]:
    """Get main categories for a specific language."""
    lang = (language or _DEFAULT_LANGUAGE).lower()
    if lang not in CATEGORIES:
        lang = _DEFAULT_LANGUAGE

    localized = [
        _CANONICAL_TO_LOCAL.get(canonical, {}).get(lang)
        for canonical in _CANONICAL_ORDER
    ]
    return [label for label in localized if label]


def canonicalize_category(category: str | None) -> str | None:
    """Map any localized category label to a canonical category key."""
    if not category:
        return category

    exact = _EXACT_ALIASES.get(category)
    if exact:
        return exact

    return _NORMALIZED_ALIASES.get(_normalize_label(category), category)


def localize_category(category: str | None, language: str = _DEFAULT_LANGUAGE) -> str | None:
    """Translate canonical/localized category label to target language."""
    if not category:
        return category

    canonical = canonicalize_category(category)
    localized = _CANONICAL_TO_LOCAL.get(canonical or "", {})
    if not localized:
        return category

    lang = (language or _DEFAULT_LANGUAGE).lower()
    return (
        localized.get(lang)
        or localized.get(_DEFAULT_LANGUAGE)
        or localized.get(_CANONICAL_LANGUAGE)
        or category
    )


def canonicalize_subcategory(category: str | None, subcategory: str | None) -> str | None:
    """Map localized subcategory label to a canonical subcategory key for a given category."""
    if not subcategory:
        return subcategory

    canonical_category = canonicalize_category(category)
    if not canonical_category:
        return subcategory

    exact = _SUBCATEGORY_EXACT_ALIASES.get((canonical_category, subcategory))
    if exact:
        return exact

    normalized = _SUBCATEGORY_NORMALIZED_ALIASES.get((canonical_category, _normalize_label(subcategory)))
    if normalized:
        return normalized

    return subcategory


def localize_subcategory(
    category: str | None,
    subcategory: str | None,
    language: str = _DEFAULT_LANGUAGE,
) -> str | None:
    """Translate canonical/localized subcategory label for the given category and language."""
    if not subcategory:
        return subcategory

    canonical_category = canonicalize_category(category)
    if not canonical_category:
        return subcategory

    canonical_subcategory = canonicalize_subcategory(canonical_category, subcategory)
    localized = _SUBCATEGORY_CANONICAL_TO_LOCAL.get(canonical_category, {}).get(canonical_subcategory or "", {})
    if not localized:
        return subcategory

    lang = (language or _DEFAULT_LANGUAGE).lower()
    return (
        localized.get(lang)
        or localized.get(_DEFAULT_LANGUAGE)
        or localized.get(_CANONICAL_LANGUAGE)
        or subcategory
    )


def expand_category_aliases(categories: list[str] | None) -> list[str] | None:
    """Expand selected categories to all language aliases for cross-language filtering."""
    if not categories:
        return categories

    expanded: set[str] = set()
    for category in categories:
        canonical = canonicalize_category(category)
        if not canonical:
            continue

        aliases = _CANONICAL_TO_LOCAL.get(canonical)
        if aliases:
            expanded.update(aliases.values())
        else:
            expanded.add(category)

    return sorted(expanded)


def get_subcategories_for_category(category: str, language: str) -> List[str]:
    """Get subcategories for a specific category and language."""
    lang = (language or _DEFAULT_LANGUAGE).lower()
    if lang not in CATEGORIES:
        lang = _DEFAULT_LANGUAGE

    canonical = canonicalize_category(category)
    localized_category = localize_category(canonical, lang)

    cats = CATEGORIES.get(lang, {})
    if localized_category in cats:
        subcats = cats[localized_category]
        if isinstance(subcats, dict):
            return list(subcats.keys())
        if isinstance(subcats, list):
            return list(subcats)
    return []


def validate_category(category: str, language: str = "uk") -> bool:
    """Check if category is valid for given language."""
    canonical = canonicalize_category(category)
    if not canonical:
        return False
    localized = localize_category(canonical, language)
    cats = CATEGORIES.get(language, {})
    return bool(localized and localized in cats)


def validate_subcategory(category: str, subcategory: str, language: str = "uk") -> bool:
    """Check if subcategory is valid for given category and language."""
    subcats = get_subcategories_for_category(category, language)
    return subcategory in subcats


def find_closest_category(text: str, language: str = "uk") -> Tuple[str | None, float]:
    """
    Find closest matching category using simple string matching.
    Returns (category, match_ratio) or (None, 0.0) if no match.
    """
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return None, 0.0

    cats = CATEGORIES.get(language, {})
    cat_list = list(cats.keys())
    
    if not cat_list:
        return None, 0.0
    
    match = process.extractOne(
        text.lower(),
        [c.lower() for c in cat_list],
        scorer=fuzz.WRatio,
        score_cutoff=50,
    )
    
    if match:
        _, score, idx = match
        return cat_list[idx], score / 100.0
    return None, 0.0


def get_category_emoji(category: str) -> str:
    """Extract emoji from category if present (first char if emoji)."""
    if category and ord(category[0]) > 127:  # Simple emoji detection
        return category[0]
    return ""


def get_clean_category_name(category: str) -> str:
    """Remove emoji from category name."""
    if category and ord(category[0]) > 127:
        return category[1:].strip()
    return category
