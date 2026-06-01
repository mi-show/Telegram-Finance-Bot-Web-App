import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from sqlalchemy import text

from app.db import get_session

# Single source of truth for categories structure (NOT keywords!)
# Structure: language -> category -> list of subcategories
# Seed keywords/phrases for DB bootstrap are stored in seed_keywords.json
CATEGORIES: Dict[str, Dict[str, List[str]]] = {
    "ru": {
        "🏠 Жильё": [
            "Аренда",
            "Коммунальные услуги",
            "Интернет",
            "Ремонт",
            "Мебель",
            "Бытовая техника",
        ],
        "🍔 Еда и напитки": [
            "Продукты (супермаркет)",
            "Кафе и рестораны",
            "Фастфуд",
            "Кофе/чай",
            "Вкусняшки (сладости)",
            "Доставка еды",
            "Алкоголь",
            "Сигареты",
        ],
        "🚗 Транспорт": [
            "Общественный транспорт",
            "Такси",
            "Топливо",
            "Обслуживание авто",
            "Парковка",
            "Аренда авто",
        ],
        "🛍 Покупки": [
            "Одежда",
            "Обувь",
            "Электроника",
            "Аксессуары",
            "Домашние товары",
        ],
        "🧠 Здоровье": [
            "Аптека",
            "Врачи",
            "Анализы",
            "Страховка",
            "Спортзал",
            "Витамины",
        ],
        "🎮 Развлечения": [
            "Подписки (Netflix, Spotify)",
            "Кино",
            "Игры",
            "Хобби",
            "Мероприятия",
        ],
        "📚 Образование": [
            "Курсы",
            "Книги",
            "Университет",
            "Онлайн обучение",
        ],
        "🧾 Финансы": [
            "Налоги",
            "Комиссии",
            "Кредиты",
            "Инвестиции",
        ],
        "🎁 Подарки и донаты": [
            "Подарки",
            "Благотворительность",
            "Донаты",
        ],
        "🐶 Животные": [
            "Корм",
            "Ветеринар",
            "Уход",
        ],
        "✈️ Путешествия": [
            "Билеты",
            "Отели",
            "Экскурсии",
            "Страховка",
        ],
        "📱 Связь": [
            "Мобильная связь",
            "Интернет (если отдельно)",
        ],
        "❗ Другое": [
            "Непредвиденные расходы",
            "Разное",
        ],
    },
    "uk": {
        "🏠 Житло": [
            "Оренда",
            "Комунальні послуги",
            "Інтернет",
            "Ремонт",
            "Меблі",
            "Побутова техніка",
        ],
        "🍔 Їжа та напої": [
            "Продукти (супермаркет)",
            "Кафе та ресторани",
            "Фастфуд",
            "Кава/чай",
            "Смаколики (солодощі)",
            "Доставка їжі",
            "Алкоголь",
            "Сигарети",
        ],
        "🚗 Транспорт": [
            "Громадський транспорт",
            "Таксі",
            "Паливо",
            "Обслуговування авто",
            "Паркування",
            "Оренда авто",
        ],
        "🛍 Покупки": [
            "Одяг",
            "Взуття",
            "Електроніка",
            "Аксесуари",
            "Товари для дому",
        ],
        "🧠 Здоров'я": [
            "Аптека",
            "Лікарі",
            "Аналізи",
            "Страховка",
            "Спортзал",
            "Вітаміни",
        ],
        "🎮 Розваги": [
            "Підписки",
            "Кіно",
            "Ігри",
            "Хобі",
            "Заходи",
        ],
        "📚 Освіта": [
            "Курси",
            "Книги",
            "Університет",
            "Онлайн навчання",
        ],
        "🧾 Фінанси": [
            "Податки",
            "Комісії",
            "Кредити",
            "Інвестиції",
        ],
        "🎁 Подарунки та донати": [
            "Подарунки",
            "Благодійність",
            "Донати",
        ],
        "🐶 Тварини": [
            "Корм",
            "Ветеринар",
            "Догляд",
        ],
        "✈️ Подорожі": [
            "Квитки",
            "Готелі",
            "Екскурсії",
            "Страховка",
        ],
        "📱 Зв'язок": [
            "Мобільний зв'язок",
            "Інтернет (якщо окремо)",
        ],
        "❗ Інше": [
            "Непередбачені витрати",
            "Різне",
        ],
    },
    "en": {
        "Housing": [
            "Rent",
            "Utilities",
            "Internet",
            "Repair",
            "Furniture",
            "Appliances",
        ],
        "Food & Drinks": [
            "Groceries",
            "Cafes & Restaurants",
            "Fast Food",
            "Coffee & Tea",
            "Sweets (Desserts)",
            "Food Delivery",
            "Alcohol",
            "Cigarettes",
        ],
        "Transport": [
            "Public Transport",
            "Taxi",
            "Fuel",
            "Maintenance",
            "Parking",
            "Rental",
        ],
        "Shopping": [
            "Clothing",
            "Shoes",
            "Electronics",
            "Accessories",
            "Home Goods",
        ],
        "Health": [
            "Pharmacy",
            "Doctors",
            "Tests",
            "Insurance",
            "Gym",
            "Vitamins",
        ],
        "Entertainment": [
            "Subscriptions",
            "Movies",
            "Games",
            "Hobby",
            "Events",
        ],
        "Education": [
            "Courses",
            "Books",
            "University",
            "Online Learning",
        ],
        "Finance": [
            "Taxes",
            "Fees",
            "Loans",
            "Investments",
        ],
        "Gifts": [
            "Presents",
            "Charity",
            "Donations",
        ],
        "Animals": [
            "Pet Food",
            "Veterinarian",
            "Care",
        ],
        "Travel": [
            "Tickets",
            "Hotels",
            "Tours",
            "Insurance",
        ],
        "Communications": [
            "Mobile",
            "Internet (if separate)",
        ],
        "Other": [
            "Unexpected Expenses",
            "Miscellaneous",
        ],
    },
}


SEED_KEYWORDS_PATH = Path(__file__).with_name("seed_keywords.json")


def load_seed_keyword_entries(seed_path: Path = SEED_KEYWORDS_PATH) -> list[dict[str, str | int | None]]:
    """Load and validate seed keyword entries from a repository JSON file."""
    if not seed_path.exists():
        raise RuntimeError(f"Seed keyword file not found: {seed_path}")

    raw_payload = json.loads(seed_path.read_text(encoding="utf-8"))
    raw_entries = raw_payload.get("entries") if isinstance(raw_payload, dict) else None
    if not isinstance(raw_entries, list):
        raise RuntimeError("Invalid seed keyword file format: 'entries' list is required")

    entries: list[dict[str, str | int | None]] = []
    for idx, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise RuntimeError(f"Invalid seed entry at index {idx}: expected object")

        lang = str(raw.get("language") or "").lower().strip()
        category = str(raw.get("category") or "").strip()
        phrase = str(raw.get("phrase") or "").lower().strip()
        subcategory_raw = raw.get("subcategory")
        subcategory = str(subcategory_raw).strip() if isinstance(subcategory_raw, str) and subcategory_raw.strip() else None

        if not lang or not category or not phrase:
            raise RuntimeError(f"Invalid seed entry at index {idx}: language/category/phrase are required")

        weight_raw = raw.get("weight", 2)
        try:
            weight = int(weight_raw) if weight_raw is not None else 2
        except (TypeError, ValueError):
            weight = 2
        if weight <= 0:
            weight = 1

        entries.append(
            {
                "language": lang,
                "category": category,
                "subcategory": subcategory,
                "phrase": phrase,
                "weight": weight,
            }
        )

    return entries


async def ensure_custom_keywords() -> None:
    """
    Sync seed keywords from repository JSON to DB.
    This keeps DB dictionary aligned with source-controlled seed data.
    """
    entries = load_seed_keyword_entries()

    async with get_session() as session:
        # Reset only seed rows so runtime dictionary is deterministic and up-to-date.
        try:
            await session.execute(text("DELETE FROM category_keywords WHERE source = 'seed';"))
        except Exception as exc:
            print(f"Failed to reset seed keywords: {exc}")
            raise

        loaded = 0
        per_language_counts: dict[str, int] = defaultdict(int)
        for entry in entries:
            try:
                stmt = text(
                    "INSERT INTO category_keywords(language, category, subcategory, phrase, source, weight) "
                    "VALUES (:lang, :cat, :subcat, :phrase, 'seed', :weight) "
                    "ON CONFLICT(language, phrase) DO UPDATE SET "
                    "category = EXCLUDED.category, "
                    "subcategory = EXCLUDED.subcategory, "
                    "source = 'seed', "
                    "weight = CASE "
                    "WHEN category_keywords.weight > EXCLUDED.weight THEN category_keywords.weight "
                    "ELSE EXCLUDED.weight END"
                )
                await session.execute(
                    stmt,
                    {
                        "lang": entry["language"],
                        "cat": entry["category"],
                        "subcat": entry["subcategory"],
                        "phrase": entry["phrase"],
                        "weight": entry["weight"],
                    },
                )
                loaded += 1
                per_language_counts[str(entry["language"])] += 1
            except Exception as exc:
                print(f"Error loading phrase '{entry.get('phrase')}': {exc}")
        
        await session.commit()
        for lang in sorted(per_language_counts):
            print(f"[BOOTSTRAP] Loaded {per_language_counts[lang]} keywords for {lang}")
        print(f"[BOOTSTRAP] Total loaded: {loaded} seed keywords from JSON file.")


async def main():
    await ensure_custom_keywords()


if __name__ == "__main__":
    asyncio.run(main())


