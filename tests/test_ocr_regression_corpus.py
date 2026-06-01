import json
from decimal import Decimal
from math import ceil
from pathlib import Path
from time import perf_counter

import pytest

from app.services.ocr_service import OCRService
from app.services.ocr_quality_targets import QUALITY_TARGETS
from app.services.receipt_parser import ParsedReceipt, ReceiptParser


def _load_payload() -> dict:
    corpus_path = Path(__file__).parent / "fixtures" / "ocr_regression_cases.json"
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("OCR regression corpus payload must be an object")
    if not payload.get("version"):
        raise AssertionError("OCR regression corpus must define version")
    return payload


def _load_cases() -> list[dict]:
    payload = _load_payload()
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AssertionError("OCR regression corpus is empty or invalid")
    return cases


def _parse_quality_score(parsed: ParsedReceipt, expected: dict) -> int:
    score = 0
    expected_amount = Decimal(expected["amount"])
    if parsed.amount == expected_amount:
        score += 3

    merchant_expected = expected.get("merchant_contains")
    if merchant_expected and parsed.merchant and merchant_expected.lower() in parsed.merchant.lower():
        score += 1

    min_items = int(expected.get("min_items", 0))
    if len(parsed.items) >= min_items:
        score += 1

    for token in expected.get("item_tokens", []):
        token_lower = str(token).lower()
        if any(token_lower in (item.name or "").lower() for item in parsed.items):
            score += 1

    return score


def _item_token_matches(parsed: ParsedReceipt, expected: dict) -> tuple[int, int]:
    tokens = [str(token).lower() for token in expected.get("item_tokens", [])]
    if not tokens:
        return 0, 0

    matched = 0
    for token in tokens:
        if any(token in (item.name or "").lower() for item in parsed.items):
            matched += 1
    return matched, len(tokens)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, ceil(len(ordered) * 0.95) - 1))
    return ordered[idx]


def test_ocr_corpus_has_version_groups_and_size_range():
    payload = _load_payload()
    cases = _load_cases()
    groups = payload.get("groups")

    assert isinstance(groups, list)
    assert 60 <= len(cases) <= 100

    required_groups = {
        "normal",
        "low_light",
        "heavy_noise",
        "rotated",
        "mixed_languages",
        "nonstandard_format",
    }
    present_groups = {case.get("group") for case in cases}
    assert required_groups.issubset(present_groups)

    changelog_path = Path(__file__).parent / "fixtures" / "ocr_regression_changelog.md"
    assert changelog_path.exists()
    changelog_text = changelog_path.read_text(encoding="utf-8")
    assert str(payload["version"]) in changelog_text


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_ocr_cleanup_matches_reference_fragments(case: dict):
    service = OCRService(preferred_langs=["eng"])
    cleaned = service._cleanup_text(case["raw_ocr"])

    for fragment in case["expected"].get("cleanup_contains", []):
        assert fragment in cleaned


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_parser_on_cleaned_ocr_meets_expected_and_not_worse_than_raw(case: dict):
    service = OCRService(preferred_langs=["eng"])
    parser = ReceiptParser()

    raw_text = case["raw_ocr"]
    cleaned_text = service._cleanup_text(raw_text)

    parsed_raw = parser.parse(raw_text)
    parsed_clean = parser.parse(cleaned_text)
    expected = case["expected"]

    assert parsed_clean.amount == Decimal(expected["amount"])
    assert len(parsed_clean.items) >= int(expected["min_items"])

    merchant_expected = expected.get("merchant_contains")
    if merchant_expected:
        assert parsed_clean.merchant is not None
        assert merchant_expected.lower() in parsed_clean.merchant.lower()

    for token in expected.get("item_tokens", []):
        token_lower = str(token).lower()
        assert any(token_lower in (item.name or "").lower() for item in parsed_clean.items)

    raw_score = _parse_quality_score(parsed_raw, expected)
    clean_score = _parse_quality_score(parsed_clean, expected)
    assert clean_score >= raw_score


def test_ocr_quality_gate_metrics_on_regression_corpus():
    service = OCRService(preferred_langs=["eng"])
    parser = ReceiptParser()

    cases = _load_cases()
    amount_ok = 0
    matched_tokens = 0
    total_tokens = 0
    false_high_confidence = 0
    latencies: list[float] = []

    for case in cases:
        expected = case["expected"]
        started = perf_counter()
        cleaned = service._cleanup_text(case["raw_ocr"])
        parsed = parser.parse(cleaned)
        elapsed = perf_counter() - started
        latencies.append(elapsed)

        expected_amount = Decimal(expected["amount"])
        amount_is_correct = parsed.amount == expected_amount
        if amount_is_correct:
            amount_ok += 1

        token_hits, token_total = _item_token_matches(parsed, expected)
        matched_tokens += token_hits
        total_tokens += token_total

        min_items = int(expected.get("min_items", 0))
        item_shape_ok = len(parsed.items) >= min_items and (token_hits == token_total)
        if parsed.overall_confidence >= 0.85 and (not amount_is_correct or not item_shape_ok):
            false_high_confidence += 1

    amount_accuracy = amount_ok / len(cases)
    item_extraction_ratio = (matched_tokens / total_tokens) if total_tokens else 1.0
    false_high_confidence_ratio = false_high_confidence / len(cases)
    latency_p95 = _p95(latencies)

    assert amount_accuracy >= QUALITY_TARGETS.amount_accuracy_min
    assert item_extraction_ratio >= QUALITY_TARGETS.item_extraction_ratio_min
    assert false_high_confidence_ratio <= QUALITY_TARGETS.false_high_confidence_max
    assert latency_p95 <= QUALITY_TARGETS.latency_p95_seconds_max
