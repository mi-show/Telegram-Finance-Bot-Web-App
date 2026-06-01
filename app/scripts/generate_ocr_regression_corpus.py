from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


def _fmt_comma(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _make_case(
    *,
    case_id: str,
    group: str,
    merchant: str,
    item_lines: list[str],
    total_label: str,
    total_value: Decimal,
    cash_line: str,
    expected_tokens: list[str],
    cleanup_line: str,
) -> dict:
    raw_lines = [merchant, *item_lines, f"{total_label} {_fmt_comma(total_value)}", cash_line]
    return {
        "id": case_id,
        "group": group,
        "raw_ocr": "\n".join(raw_lines),
        "expected": {
            "amount": f"{total_value:.2f}",
            "merchant_contains": merchant[:6].strip(),
            "min_items": max(2, min(3, len(item_lines))),
            "item_tokens": expected_tokens,
            "cleanup_contains": [cleanup_line, f"{total_label} {_fmt_comma(total_value)}"],
        },
    }


def generate_corpus() -> tuple[dict, str]:
    groups = [
        "normal",
        "low_light",
        "heavy_noise",
        "rotated",
        "mixed_languages",
        "nonstandard_format",
    ]

    cases = []
    for idx in range(12):
        d = Decimal(idx) / Decimal("100")

        a = Decimal("27.05") + d
        b = Decimal("1.45") + d
        c = Decimal("15.92") + d
        total = a + b + c
        cases.append(
            _make_case(
                case_id=f"normal_{idx + 1:02d}",
                group="normal",
                merchant=f"Сільпо {idx + 1}",
                item_lines=[
                    f"Мандарин Пакистан 1гат. 0,820 X 32,99 = {_fmt_comma(a)} A",
                    f"Пакет п/е 40x60 зі святковою с {_fmt_comma(b)} A",
                    f"Банан 1гат 0,724 X 21,99 = {_fmt_comma(c)} A",
                ],
                total_label="Сума",
                total_value=total,
                cash_line=f"ГРОШІ {_fmt_comma(total + Decimal('10.00'))}",
                expected_tokens=["Мандарин", "Банан", "Пакет"],
                cleanup_line=_fmt_comma(a),
            )
        )

        a = Decimal("13.90") + d
        b = Decimal("27.38") + d
        total = a + b
        cases.append(
            _make_case(
                case_id=f"low_light_{idx + 1:02d}",
                group="low_light",
                merchant=f"АТБ {idx + 1}",
                item_lines=[
                    f"@@Майонез 350 г {_fmt_comma(a)} A",
                    f"***Яблуко 1,245 X 21,99 = {_fmt_comma(b)} A",
                ],
                total_label="Всього",
                total_value=total,
                cash_line=f"Картка {_fmt_comma(total)}",
                expected_tokens=["Майонез", "Яблуко"],
                cleanup_line=_fmt_comma(b),
            )
        )

        a = Decimal("79.00") + d
        b = Decimal("45.00") + d
        total = a + b
        cases.append(
            _make_case(
                case_id=f"heavy_noise_{idx + 1:02d}",
                group="heavy_noise",
                merchant=f"Сiльпо ### {idx + 1}",
                item_lines=[
                    f"%%%Кава Лате 1,000 X 79,00 = {_fmt_comma(a)} A",
                    f"!!!Круасан сирний {_fmt_comma(b)} A",
                ],
                total_label="Сумма",
                total_value=total,
                cash_line=f"Нал {_fmt_comma(total + Decimal('76.00'))} | Сдача 76,00",
                expected_tokens=["Кава", "Круасан"],
                cleanup_line=_fmt_comma(a),
            )
        )

        a = Decimal("2.49") + d
        b = Decimal("1.99") + d
        total = a + b
        cases.append(
            _make_case(
                case_id=f"rotated_{idx + 1:02d}",
                group="rotated",
                merchant=f"MARKET PLACE {idx + 1}",
                item_lines=[
                    f"Apple 1,000 x 2,49 = {_fmt_comma(a)} A",
                    f"Bread {_fmt_comma(b)} A",
                ],
                total_label="Total",
                total_value=total,
                cash_line=f"Cash {_fmt_comma(total + Decimal('0.52'))} Change 0,52",
                expected_tokens=["Apple", "Bread"],
                cleanup_line=f"Total {_fmt_comma(total)}",
            )
        )

        a = Decimal("18.40") + d
        b = Decimal("11.60") + d
        total = a + b
        cases.append(
            _make_case(
                case_id=f"mixed_languages_{idx + 1:02d}",
                group="mixed_languages",
                merchant=f"FOOD Маркет {idx + 1}",
                item_lines=[
                    f"Cheese Сир {_fmt_comma(a)} A",
                    f"Milk Молоко {_fmt_comma(b)} A",
                ],
                total_label="Итого",
                total_value=total,
                cash_line=f"Card {_fmt_comma(total)}",
                expected_tokens=["Cheese", "Milk"],
                cleanup_line=f"Итого {_fmt_comma(total)}",
            )
        )

        a = Decimal("27.05") + d
        b = Decimal("9.90") + d
        total = a + b
        raw_lines = [
            f"ЕКО Маркет {idx + 1}",
            "Мандарин Пакистан 1гат.",
            f"0,820 X 32,99 = {_fmt_comma(a)} A",
            f"Йогурт полуничний {_fmt_comma(b)} A",
            f"Сума {_fmt_comma(total)}",
            f"Картка {_fmt_comma(total)}",
        ]
        cases.append(
            {
                "id": f"nonstandard_format_{idx + 1:02d}",
                "group": "nonstandard_format",
                "raw_ocr": "\n".join(raw_lines),
                "expected": {
                    "amount": f"{total:.2f}",
                    "merchant_contains": "ЕКО",
                    "min_items": 2,
                    "item_tokens": ["Мандарин", "Йогурт"],
                    "cleanup_contains": [_fmt_comma(a), f"Сума {_fmt_comma(total)}"],
                },
            }
        )

    payload = {
        "version": "1.1.0",
        "generated_at": "2026-04-13",
        "groups": groups,
        "cases": cases,
    }

    changelog = """# OCR Corpus Changelog

## 1.1.0 - 2026-04-13

- Expanded corpus from 4 to 72 text-based receipt cases.
- Added explicit groups: normal, low_light, heavy_noise, rotated, mixed_languages, nonstandard_format.
- Standardized expected fields for every case: amount, merchant_contains, min_items, item_tokens, cleanup_contains.

## 1.0.0 - 2026-04-13

- Initial bootstrap corpus with 4 regression cases.
"""
    return payload, changelog


def main() -> None:
    fixtures_dir = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    payload, changelog = generate_corpus()

    corpus_path = fixtures_dir / "ocr_regression_cases.json"
    changelog_path = fixtures_dir / "ocr_regression_changelog.md"

    corpus_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    changelog_path.write_text(changelog, encoding="utf-8")

    print(f"Wrote {len(payload['cases'])} cases to {corpus_path}")


if __name__ == "__main__":
    main()
