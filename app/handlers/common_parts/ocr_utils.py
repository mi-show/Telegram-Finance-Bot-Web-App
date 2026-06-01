from decimal import Decimal

from .quick_expense import looks_like_gibberish


def is_item_confidently_recognized(
    item_name: str,
    category: str,
    source: str,
    confidence: float,
) -> bool:
    trusted_sources = {"user_exact", "user_fuzzy", "override", "dictionary"}
    if source in trusted_sources:
        return True

    if (
        source == "ml"
        and confidence >= 0.8
        and category not in {"Other", "❗ Інше", "❗ Другое"}
        and not looks_like_gibberish(item_name)
    ):
        return True

    return False


def group_recognized_items(item_rows: list[dict]) -> dict[tuple[str, str], dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for row in item_rows:
        if not row.get("recognized"):
            continue
        price = row.get("price")
        if price is None:
            continue

        category = row.get("category") or "Other"
        subcategory = row.get("subcategory") or ""
        key = (category, subcategory)
        if key not in grouped:
            grouped[key] = {
                "total": Decimal("0"),
                "count": 0,
                "examples": [],
            }

        grouped[key]["total"] += price
        grouped[key]["count"] += 1
        if len(grouped[key]["examples"]) < 3:
            grouped[key]["examples"].append(row.get("name") or "")

    return grouped
