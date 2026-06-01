from app.services.category_service import (
    canonicalize_category,
    canonicalize_subcategory,
    expand_category_aliases,
    get_categories_for_lang,
    localize_category,
    localize_subcategory,
)


def test_category_canonical_roundtrip_across_languages():
    en_category = get_categories_for_lang("en")[0]
    ru_category = localize_category(en_category, "ru")
    uk_category = localize_category(en_category, "uk")

    assert canonicalize_category(en_category) == canonicalize_category(ru_category)
    assert canonicalize_category(en_category) == canonicalize_category(uk_category)


def test_expand_category_aliases_returns_cross_language_values():
    en_category = get_categories_for_lang("en")[0]
    aliases = expand_category_aliases([en_category])

    assert aliases is not None
    assert en_category in aliases
    assert len(aliases) >= 2


def test_subcategory_canonical_roundtrip_across_languages():
    en_category = "Food & Drinks"
    en_subcategory = "Groceries"

    ru_category = localize_category(en_category, "ru")
    uk_category = localize_category(en_category, "uk")
    ru_subcategory = localize_subcategory(en_category, en_subcategory, "ru")
    uk_subcategory = localize_subcategory(en_category, en_subcategory, "uk")

    assert ru_category
    assert uk_category
    assert ru_subcategory
    assert uk_subcategory

    assert canonicalize_subcategory(en_category, en_subcategory) == en_subcategory
    assert canonicalize_subcategory(ru_category, ru_subcategory) == en_subcategory
    assert canonicalize_subcategory(uk_category, uk_subcategory) == en_subcategory

    assert localize_subcategory(ru_category, en_subcategory, "ru") == ru_subcategory
    assert localize_subcategory(uk_category, en_subcategory, "uk") == uk_subcategory