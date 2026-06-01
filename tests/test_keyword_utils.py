from app.services.category_classifier.keyword_utils import expand_keyword_entries


def test_expand_keyword_entries_splits_compact_bag_line():
    entries = expand_keyword_entries("taxi uber lyft grab gojek cabify bolt")

    assert "taxi uber lyft grab gojek cabify bolt" in entries
    assert "taxi" in entries
    assert "uber" in entries
    assert "bolt" in entries


def test_expand_keyword_entries_keeps_phrase_line():
    entries = expand_keyword_entries("билет на автобус")

    assert entries[0] == "билет на автобус"
    assert "билет" not in entries


def test_expand_keyword_entries_supports_delimiters():
    entries = expand_keyword_entries("coffee, tea; latte")

    assert "coffee" in entries
    assert "tea" in entries
    assert "latte" in entries
