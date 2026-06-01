"""Tests for user classifier confidence behavior."""

from app.services.user_classifier import UserClassifier


def test_predict_with_user_context_confidence_exact_dictionary_match():
    clf = UserClassifier()
    clf.refresh_dynamic({"coffee": ("Food", "Coffee")})

    category, subcategory, confidence, source = clf.predict_with_user_context_confidence(
        "morning coffee",
        telegram_id=1,
        language="en",
    )

    assert category == "Food"
    assert subcategory == "Coffee"
    assert confidence == 1.0
    assert source == "dictionary"


def test_predict_with_user_context_confidence_user_exact_match():
    clf = UserClassifier()
    clf._user_phrase_cache[77]["strangeword"] = ("Other", None)

    category, subcategory, confidence, source = clf.predict_with_user_context_confidence(
        "strangeword",
        telegram_id=77,
        language="en",
    )

    assert category == "Other"
    assert subcategory is None
    assert confidence == 1.0
    assert source == "user_exact"


def test_was_word_recognized_false_for_fallback():
    clf = UserClassifier()

    assert clf.was_word_recognized("qwertyuiop", language="en") is False
