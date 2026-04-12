# Telegram Finance Bot

Асинхронный Telegram‑бот для учёта личных финансов на aiogram 3.

## Возможности

- Добавление доходов и расходов с валидацией (Pydantic).
- Фильтрация записей: даты, категории, тип (income/expense), сумма (min/max), поиск по описанию.
- Агрегации: суммы по дню/неделе/месяцу, баланс, средний и максимальный расход.
- Бюджетный план и расчёт остатка.
- Кэширование дорогих операций.
- Unit-тесты для основных компонентов.
- **Новый OCR-поток:** отправьте фото чека → OCR → сумма + магазин → авто‑категория (словарь + ML) → подтверждение перед сохранением.
- **Telegram Web App:** dashboard, операции, аналитика, бюджет, настройки, экспорт CSV/PDF и редактирование записей внутри мини‑приложения.

## Быстрый старт (локально)

1. Создайте `.env`:

```bash
cp .env.sample .env
# пропишите BOT_TOKEN и при необходимости DATABASE_URL
```

1. Установите зависимости и запустите бота:

```bash
pip install -r requirements.txt
python -m app.bot
```

1. Запустите Web App API + UI:

```bash
python -m app.web_main
```

## Запуск тестов

```bash
pip install pytest pytest-asyncio
pytest tests/
```

## Docker

```bash
docker compose -p finance-bot up -d --build    # прод (bot + web + db)
docker compose -p finance-bot up --build      # разработка с bind-mount
```

## Команды бота

- `/start` или `/help` — подсказки + меню‑кнопки.
- `/add <income|expense> <category> <amount> <YYYY-MM-DD> [note]`
- `/list [from=YYYY-MM-DD to=YYYY-MM-DD type=expense cat=Food,Taxi min=10 max=200 q=coffee]`
- `/stats` — баланс, суммы за день/неделю/месяц, средний и максимальный расход.
- `/budget set <plan_expense> <plan_income> <start> <end>` — сохранить план; без параметров покажет последний или создаст базовый.
- Отправьте **фото чека** — бот распознает сумму и магазин, предложит категорию (расширенный словарь + ML), спросит подтверждение перед сохранением.
- Кнопка **Finance Web App** в меню открывает мини‑приложение Telegram Web App.

## Архитектура

- `app/config.py` — настройки из окружения.
- `app/db.py`, `app/models.py` — SQLAlchemy async (SQLite по умолчанию, готово к Postgres).
- `app/repositories/records.py` — работа с БД, фильтры, агрегаты, бюджеты.
- `app/services/record_service.py`, `app/services/aggregation_service.py` — бизнес‑логика и кэш.
- `app/services/ocr_service.py`, `app/services/receipt_parser.py`, `app/services/category_classifier.py` — OCR и авто‑категоризация чеков.
- `app/handlers/common.py` — Telegram‑handlers, включая фото чеков с подтверждением.
- `app/web/app.py`, `app/web/static/*` — FastAPI backend и фронтенд Telegram Web App.
- `app/cache.py` — простой in-memory кэш с TTL.
- `tests/` — unit‑тесты.

## Переменные окружения (.env)

```dotenv
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
DATABASE_URL=sqlite+aiosqlite:///./finance.db
LOG_LEVEL=INFO
DATE_FORMAT=%Y-%m-%d
MAX_LIST_RECORDS=100
CACHE_TTL=300
WEBAPP_URL=https://your-domain.example/webapp
WEBAPP_HOST=0.0.0.0
WEBAPP_PORT=8000
WEBAPP_INITDATA_TTL=86400
# для локальной отладки вне Telegram (опционально)
# WEBAPP_DEV_TELEGRAM_ID=123456789
```

## Заметки

- Для продакшена замените SQLite на Postgres, обновив `DATABASE_URL`.
- OCR использует `pytesseract`; убедитесь, что двоичный tesseract доступен в PATH контейнера/хоста.
- После добавления записей кэш статистики инвалидируется автоматически.
- Для Telegram Web App укажите публичный `WEBAPP_URL` и добавьте этот URL в настройки кнопки/домена бота в BotFather.
