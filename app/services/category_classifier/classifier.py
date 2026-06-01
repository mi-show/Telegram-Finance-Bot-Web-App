from __future__ import annotations

import logging
import re
from math import isfinite
from typing import Dict, List, Optional

from ..category_service import localize_category

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
except ImportError:  # pragma: no cover - sklearn is optional at runtime
    TfidfVectorizer = None
    LogisticRegression = None

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover
    fuzz = None
    process = None

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ']+")

class CategoryClassifier:
    """
    Hybrid keyword/ML classifier for merchant strings.
    """

    def __init__(
        self,
        min_per_category: int = 500,
        languages: Optional[List[str]] = None,
        translate_to: Optional[str] = None,
        fuzzy_threshold: int = 72,
    ):
        self.min_per_category = min_per_category
        self.languages = [lang.lower() for lang in languages] if languages else None
        self.translate_to = translate_to
        self.fuzzy_threshold = fuzzy_threshold
        self._keys: List[str] = []
        self._keys_by_token: Dict[str, List[str]] = {}
        self._keys_by_first_char: Dict[str, List[str]] = {}
        self.overrides: Dict[str, str] = {}

        # Base dictionary is sourced from DB-driven extra keywords in runtime.
        self.base_dictionary: Dict[str, str | tuple] = {}

        self.dictionary: Dict[str, str | tuple] = dict(self.base_dictionary)
        # Initialize category-only dictionary for ML training
        self._category_only_dict: Dict[str, str] = {
            k: (v[0] if isinstance(v, tuple) else v) for k, v in self.dictionary.items()
        }

        self.vectorizer = None
        self.model = None
        if TfidfVectorizer and LogisticRegression:
            self._train_model()
        else:  # pragma: no cover
            logger.warning("sklearn not available; CategoryClassifier will use dictionary only.")

    @staticmethod
    def _maybe_fix_mojibake(text: str) -> str:
        """
        Fix UTF-8 strings that were mis-decoded as cp1251 (РџСЂРѕРґСѓРєС‚С‹ -> Продукты).
        """
        if re.search(r"[ÐР]", text):
            try:
                fixed = text.encode("latin1").decode("utf-8")
                return fixed
            except Exception:
                return text
        return text

    def _train_model(self):
        if not TfidfVectorizer or not LogisticRegression:
            return
        # Use only categories for training (extract from tuples if needed)
        category_dict = getattr(self, '_category_only_dict', self.dictionary)
        texts = list(category_dict.keys())
        labels = list(category_dict.values())
        if not texts:
            self.vectorizer = None
            self.model = None
            return
        if len(set(labels)) < 2:
            # LogisticRegression requires at least 2 classes.
            self.vectorizer = None
            self.model = None
            return
        self.vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
        X = self.vectorizer.fit_transform(texts)
        self.model = LogisticRegression(max_iter=300, n_jobs=None)
        self.model.fit(X, labels)
        logger.info("CategoryClassifier model trained on %d keyword phrases.", len(texts))

    def _refresh_dictionary(self, extra_keywords: Optional[Dict] = None):
        """
        Refresh dictionary from base + extra keywords.
        extra_keywords can be:
        - Dict[str, str]: {phrase: category} (legacy)
        - Dict[str, tuple[str, str]]: {phrase: (category, subcategory)} (new format)
        Stores full category or (category, subcategory) tuple internally.
        """
        self.dictionary = dict(self.base_dictionary)
        if extra_keywords:
            for key, value in extra_keywords.items():
                if not key:
                    continue
                normalized_key = self._maybe_fix_mojibake(key.lower())
                # Store full value (category or tuple) to preserve subcategory
                if isinstance(value, tuple):
                    # New format: store tuple (category, subcategory)
                    self.dictionary[normalized_key] = value
                else:
                    # Legacy format: store category string
                    self.dictionary[normalized_key] = value
        self._keys = list(self.dictionary.keys())
        self._keys_by_token = {}
        self._keys_by_first_char = {}

        for key in self._keys:
            tokens = self._extract_tokens(key)
            for token in tokens:
                self._keys_by_token.setdefault(token, []).append(key)

            first_char = ""
            for ch in key:
                if ch.isalnum():
                    first_char = ch.lower()
                    break
            if first_char:
                self._keys_by_first_char.setdefault(first_char, []).append(key)

        # For ML training, extract only categories (first element of tuple if tuple, else value)
        training_labels = []
        for val in self.dictionary.values():
            if isinstance(val, tuple):
                training_labels.append(val[0])
            else:
                training_labels.append(val)
        # Store for later use
        self._category_only_dict = {k: (v[0] if isinstance(v, tuple) else v) for k, v in self.dictionary.items()}
        self._train_model()

    def set_overrides(self, overrides: Dict[str, str]):
        """High-priority substring overrides that win before any model/dictionary."""
        normalized = {}
        for key, value in overrides.items():
            if not key or not value:
                continue
            normalized[self._maybe_fix_mojibake(key.lower())] = value
        self.overrides = normalized

    def set_languages(self, languages: List[str], translate_to: Optional[str] = None, extra_keywords: Optional[Dict] = None):
        """
        Set languages and optional extra keywords.
        extra_keywords can be Dict[str, str] or Dict[str, tuple[str, str]]
        """
        self.languages = [lang.lower() for lang in languages]
        self.translate_to = translate_to or self.translate_to
        self.base_dictionary = {}
        self._refresh_dictionary(extra_keywords)

    def refresh_dynamic(self, extra_keywords: Optional[Dict] = None):
        """Refresh with dynamic keywords. extra_keywords can be Dict[str, str] or Dict[str, tuple[str, str]]"""
        self._refresh_dictionary(extra_keywords)

    def _fuzzy_predict(self, merchant_lower: str) -> Optional[str]:
        match = self._fuzzy_match(merchant_lower)
        if not match:
            return None
        _, _, value = match
        if isinstance(value, tuple):
            return value[0]
        return value

    def _fuzzy_match(self, merchant_lower: str) -> Optional[tuple[str, float, str | tuple]]:
        if not process or not fuzz:
            return None
        if len(merchant_lower) < 3:
            return None
        candidates = self._candidate_keys_for_text(merchant_lower, include_first_char_fallback=True)
        if not candidates:
            return None
        match = process.extractOne(
            merchant_lower,
            candidates,
            scorer=fuzz.WRatio,
            score_cutoff=self.fuzzy_threshold,
        )
        if match:
            keyword, score, _ = match
            value = self.dictionary.get(keyword)
            if value is None:
                return None
            return keyword, float(score), value
        return None

    @staticmethod
    def _extract_tokens(text: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 3]

    def _candidate_keys_for_text(
        self,
        merchant_lower: str,
        include_first_char_fallback: bool = False,
    ) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        for token in self._extract_tokens(merchant_lower):
            for key in self._keys_by_token.get(token, []):
                if key not in seen:
                    seen.add(key)
                    candidates.append(key)

        if include_first_char_fallback and len(candidates) < 200:
            first_char = ""
            for ch in merchant_lower:
                if ch.isalnum():
                    first_char = ch.lower()
                    break
            if first_char:
                for key in self._keys_by_first_char.get(first_char, []):
                    if key not in seen:
                        seen.add(key)
                        candidates.append(key)

        return candidates

    def predict_with_subcategory_confidence(
        self,
        merchant: str | None,
        fallback: str = "Other",
        language: Optional[str] = None,
    ) -> tuple[str, str | None, float, str]:
        """
        Predict category + subcategory with confidence and source label.
        Source can be: override, dictionary, fuzzy, ml, fallback.
        """
        if not merchant:
            return (self._translate(fallback, language), None, 0.0, "fallback")

        merchant_lower = merchant.lower().strip()
        if not merchant_lower:
            return (self._translate(fallback, language), None, 0.0, "fallback")

        for key, category in self.overrides.items():
            if key in merchant_lower:
                return (self._translate(category, language), None, 1.0, "override")

        exact_value = self.dictionary.get(merchant_lower)
        if exact_value is not None:
            if isinstance(exact_value, tuple):
                cat, subcat = exact_value
                return (self._translate(cat, language), subcat, 1.0, "dictionary")
            return (self._translate(exact_value, language), None, 1.0, "dictionary")

        for key in self._candidate_keys_for_text(merchant_lower):
            value = self.dictionary.get(key)
            if value is None:
                continue
            if key in merchant_lower:
                if isinstance(value, tuple):
                    cat, subcat = value
                    return (self._translate(cat, language), subcat, 1.0, "dictionary")
                return (self._translate(value, language), None, 1.0, "dictionary")

        fuzzy_match = self._fuzzy_match(merchant_lower)
        if fuzzy_match:
            _, score, value = fuzzy_match
            confidence = max(0.0, min(float(score) / 100.0, 0.99))
            if isinstance(value, tuple):
                cat, subcat = value
                return (self._translate(cat, language), subcat, confidence, "fuzzy")
            return (self._translate(value, language), None, confidence, "fuzzy")

        if self.model and self.vectorizer:
            try:
                vec = self.vectorizer.transform([merchant_lower])
                category = self.model.predict(vec)[0]
                confidence = 0.5
                if hasattr(self.model, "predict_proba"):
                    probs = self.model.predict_proba(vec)[0]
                    confidence = max(float(p) for p in probs)
                    if not isfinite(confidence):
                        confidence = 0.5
                confidence = max(0.0, min(confidence, 0.99))
                return (self._translate(category, language), None, confidence, "ml")
            except Exception as exc:  # pragma: no cover
                logger.warning("ML prediction failed, fallback to default: %s", exc)

        return (self._translate(fallback, language), None, 0.0, "fallback")

    def get_ml_category_candidates(
        self,
        merchant: str | None,
        limit: int = 4,
        language: Optional[str] = None,
    ) -> list[tuple[str, float]]:
        """Return top-N ML categories with probabilities for manual suggestion UI."""
        if not merchant or not self.model or not self.vectorizer or limit <= 0:
            return []

        merchant_lower = merchant.lower().strip()
        if not merchant_lower:
            return []

        if not hasattr(self.model, "predict_proba") or not hasattr(self.model, "classes_"):
            return []

        try:
            vec = self.vectorizer.transform([merchant_lower])
            probs = self.model.predict_proba(vec)[0]
            classes = list(self.model.classes_)
            pairs = sorted(
                ((classes[idx], float(prob)) for idx, prob in enumerate(probs)),
                key=lambda x: x[1],
                reverse=True,
            )
            result: list[tuple[str, float]] = []
            for category, prob in pairs:
                if prob <= 0:
                    continue
                result.append((self._translate(category, language), prob))
                if len(result) >= limit:
                    break
            return result
        except Exception:
            return []

    def _translate(self, category: str, language: Optional[str]) -> str:
        lang = language or self.translate_to
        if not lang:
            return category
        translated = localize_category(category, lang)
        return translated or category

    def predict(self, merchant: str | None, fallback: str = "Other", language: Optional[str] = None) -> str:
        if not merchant:
            return self._translate(fallback, language)
        merchant_lower = merchant.lower()

        # 1) High-priority overrides
        for key, category in self.overrides.items():
            if key in merchant_lower:
                return self._translate(category, language)

        exact_value = self.dictionary.get(merchant_lower)
        if exact_value is not None:
            category = exact_value[0] if isinstance(exact_value, tuple) else exact_value
            return self._translate(category, language)

        for key in self._candidate_keys_for_text(merchant_lower):
            value = self.dictionary.get(key)
            if value is None:
                continue
            if key in merchant_lower:
                # Extract category (first element if tuple, else value)
                category = value[0] if isinstance(value, tuple) else value
                return self._translate(category, language)

        fuzzy_cat = self._fuzzy_predict(merchant_lower)
        if fuzzy_cat:
            return self._translate(fuzzy_cat, language)

        if self.model and self.vectorizer:
            try:
                vec = self.vectorizer.transform([merchant_lower])
                category = self.model.predict(vec)[0]
                return self._translate(category, language)
            except Exception as exc:  # pragma: no cover
                logger.warning("ML prediction failed, fallback to default: %s", exc)

        return self._translate(fallback, language)

    def predict_with_subcategory(self, merchant: str | None, fallback: str = "Other", language: Optional[str] = None) -> tuple[str, str | None]:
        """
        Predict category and subcategory.
        Returns tuple (category, subcategory) where subcategory can be None.
        """
        category, subcategory, _confidence, _source = self.predict_with_subcategory_confidence(
            merchant,
            fallback=fallback,
            language=language,
        )
        return (category, subcategory)
