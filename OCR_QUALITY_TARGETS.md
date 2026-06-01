# OCR Quality Targets

This document defines objective OCR quality gates for regression tracking.

## Targets

- Total amount accuracy: >= 97%
- Ratio of receipts with correctly extracted items: >= 90%
- False high-confidence ratio: <= 2%
- Processing latency per receipt: p95 <= 2.5 seconds

## Source of Truth

Runtime and test thresholds are defined in `app/services/ocr_quality_targets.py`.

## How It Is Measured

Metrics are computed over the versioned corpus in `tests/fixtures/ocr_regression_cases.json` by `tests/test_ocr_regression_corpus.py`.

- Amount accuracy: exact match of parsed amount vs expected amount.
- Item extraction ratio: matched expected item tokens / total expected tokens.
- False high confidence: cases where parser confidence is high but parsed result is wrong.
- Latency p95: measured for cleanup + parse on each corpus case.
