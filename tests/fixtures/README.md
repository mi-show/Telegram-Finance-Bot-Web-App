# OCR Regression Corpus

This folder stores lightweight, text-only OCR goldens for receipts.

Corpus files:

- `ocr_regression_cases.json` - versioned grouped OCR cases.
- `ocr_regression_changelog.md` - corpus change history.

Why text-only:

- keeps repository size small;
- avoids adding personal data from real photos;
- still validates the critical post-processing + parsing path.

How to add a new case:

1. Copy a real OCR fragment (anonymized) to `ocr_regression_cases.json` as `raw_ocr`.
2. Add expected values under `expected`:
   - `amount` (string decimal, dot separator);
   - `merchant_contains` (substring);
   - `min_items`;
   - `item_tokens` (keywords that should appear in parsed item names);
   - optional `cleanup_contains` (fragments expected after OCR cleanup).
3. Run `pytest -q tests/test_ocr_regression_corpus.py`.

Bulk update/generation:

1. Run `python -m app.scripts.generate_ocr_regression_corpus`.
2. Commit both updated corpus files together.
