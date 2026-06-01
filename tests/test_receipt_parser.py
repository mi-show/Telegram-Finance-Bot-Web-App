from decimal import Decimal

from app.services.receipt_parser import ReceiptParser


def test_receipt_parser_extracts_noisy_item_lines():
    parser = ReceiptParser()
    text = """
    Гаряча лінія
    Мандарин Пакистан 1гат. 0,820 X 32,99 = 27,05 A
    Пакет п/е 40x60 зі святковою с 1,45 A
    Банан 1гат 0,724 X 21,99 = 15,92 A
    Сума 174,02
    """

    parsed = parser.parse(text)

    assert parsed.amount == Decimal("174.02")
    assert len(parsed.items) >= 3

    prices = {item.price for item in parsed.items}
    assert Decimal("27.05") in prices
    assert Decimal("1.45") in prices
    assert Decimal("15.92") in prices


def test_receipt_parser_ignores_total_lines_as_items():
    parser = ReceiptParser()
    text = """
    Майонез 350 г 13,90 A
    Сума 174,02
    Решта -25,98
    """

    parsed = parser.parse(text)

    names = [item.name.lower() for item in parsed.items]
    assert any("майонез" in name for name in names)
    assert all("сума" not in name for name in names)
    assert all("решта" not in name for name in names)


def test_receipt_parser_merges_split_item_and_price_lines():
    parser = ReceiptParser()
    text = """
    Мандарин Пакистан 1гат.
    0,820 X 32,99 = 27,05 A
    Сума 27,05
    """

    parsed = parser.parse(text)

    assert parsed.items
    assert any("мандарин" in item.name.lower() for item in parsed.items)
    assert any(item.price == Decimal("27.05") for item in parsed.items)


def test_receipt_parser_drops_short_artifact_items():
    parser = ReceiptParser()
    text = """
    ки 25,98
    Майонез 350 г 13,90 A
    """

    parsed = parser.parse(text)
    names = [item.name.lower() for item in parsed.items]

    assert any("майонез" in name for name in names)
    assert all(name != "ки" for name in names)


def test_receipt_parser_prefers_total_over_cash_received_line():
    parser = ReceiptParser()
    text = """
    Сума 174,02
    ГРОШІ 200,00
    Решта -25,98
    """

    parsed = parser.parse(text)
    assert parsed.amount == Decimal("174.02")


def test_receipt_parser_reports_high_confidence_on_consistent_totals():
    parser = ReceiptParser()
    text = """
    Сільпо
    Мандарин Пакистан 1гат. 0,820 X 32,99 = 27,05 A
    Йогурт полуничний 9,90 A
    Сума 36,95
    """

    parsed = parser.parse(text)

    assert parsed.amount == Decimal("36.95")
    assert parsed.amount_confidence >= 0.8
    assert parsed.overall_confidence >= 0.65
    assert "total_matches_items" in parsed.quality_flags


def test_receipt_parser_lowers_confidence_on_total_items_mismatch():
    parser = ReceiptParser()
    text = """
    Магазин
    Майонез 350 г 13,90 A
    Банан 0,724 X 21,99 = 15,92 A
    Сума 174,02
    """

    parsed = parser.parse(text)

    assert parsed.amount == Decimal("174.02")
    assert "total_items_mismatch" in parsed.quality_flags
    assert parsed.amount_confidence < 0.8


def test_receipt_parser_prefers_amount_near_total_keyword_not_max_number():
    parser = ReceiptParser()
    text = """
    Сума 174,02
    ПДВ А = 20,00% 29,00
    ГРОШІ 200,00
    """

    parsed = parser.parse(text)

    assert parsed.amount == Decimal("174.02")


def test_receipt_parser_ignores_unrealistic_amount_outlier_in_total_line():
    parser = ReceiptParser()
    text = """
    Сума 174,02 304872,04
    """

    parsed = parser.parse(text)

    assert parsed.amount == Decimal("174.02")


def test_receipt_parser_filters_service_and_tax_lines_from_items():
    parser = ReceiptParser()
    text = """
    ГАРЯЧА ЛІНІЯ 0 800 500 415
    e-mail: info@example.com
    Мандарини Пакистан 1гат. 0,820 X 32,99 = 27,05 A
    Пакет п/е 40x60 зі святковою с 1,45 A
    ПДВ А = 20,00% 29,00
    ГРОШІ 200,00
    Сума 174,02
    """

    parsed = parser.parse(text)
    names = [item.name.lower() for item in parsed.items]

    assert parsed.amount == Decimal("174.02")
    assert any("мандарин" in name for name in names)
    assert all("лінія" not in name for name in names)
    assert all("пдв" not in name for name in names)
    assert all("грош" not in name for name in names)
