# Telegram Finance Bot + Web App

Мови: [English](README.md) | [Русский](README.ru.md) | [Українська](README.uk.md)

![Python](https://img.shields.io/badge/Python-3.11-blue) ![aiogram](https://img.shields.io/badge/aiogram-3.x-2c2c2c) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![Docker](https://img.shields.io/badge/Docker-ready-2496ED)

> Асинхронний Telegram-бот + Web App для обліку особистих фінансів з OCR чеків, розумною категоризацією, бюджетами й аналітикою.

![Bot preview](content/бот.jpg)

## Чому цей проєкт

Це full-stack портфоліо-проєкт, що демонструє продакшн-рівень Python:

- асинхронний Telegram UX (aiogram) з реальними сценаріями
- FastAPI + PostgreSQL API на SQLAlchemy async
- OCR пайплайн + ML-категоризація
- Web App з графіками, експортом і бюджетами
- Docker-стек і автоматизовані тести

## Демо

- Відеоогляд: [content/видео_работы.MP4](content/видео_работы.MP4)

## Скриншоти

| Dashboard | Operations | Analytics 1 |
| --- | --- | --- |
| ![Dashboard](content/дашборд.png) | ![Operations](content/операции.png) | ![Analytics 1](content/аналитка1.png) |

| Budget | OCR | Settings |
| --- | --- | --- |
| ![Budget](content/бюджет.png) | ![OCR](content/оср.png) | ![Settings](content/настройки.png) |

| Analytics 2 |
| --- |
| ![Analytics 2](content/аналитика2.png) |

## Ключові особливості

- Telegram команди + швидкі витрати + OCR чеків з підтвердженням
- Розумна категоризація: історія -> fuzzy match -> глобальні ключові слова -> TF-IDF модель
- Планування бюджету, ліміти по категоріях, прогнози та рекурентні платежі
- Аналітика з графіками (Chart.js) та експортом у CSV/PDF
- Багатомовний UI: `uk`, `ru`, `en`
- Кешування важких запитів, асинхронний доступ до БД
- Контроль якості OCR + регресійний корпус

## Технології

- Python 3.11, aiogram 3, FastAPI, SQLAlchemy async
- PostgreSQL (Docker), SQLite для локальної розробки
- Tesseract OCR + Pillow, `pytesseract`
- ML: scikit-learn TF-IDF + rapidfuzz
- Web App: vanilla JS, Chart.js, Telegram Web App SDK
- Тести: pytest, pytest-asyncio, Playwright

## Архітектура

```mermaid
flowchart LR
  subgraph Telegram
    U[User]
  end
  U -->|messages / photos| BOT[finance-bot (aiogram)]
  BOT -->|SQLAlchemy async| DB[(PostgreSQL)]
  BOT -->|OCR + parser| OCR[Tesseract + ReceiptParser]
  BOT -->|menu link| WEBAPP[Telegram Web App]

  WEBAPP -->|API /api/webapp/*| API[finance-web (FastAPI)]
  API --> DB
  WEBAPP -->|Charts & UI| UI[Web UI]
```

## Ключові сценарії

- Швидка витрата: "coffee 50" -> пропозиція категорії -> збереження
- OCR чеків: фото -> OCR -> парсинг позицій/суми -> категорія -> підтвердження
- Web App: дашборд, операції, аналітика, бюджет, рекурентні, налаштування
- Експорт: CSV + PDF звіти

## Швидкий старт

### Локально (pip)

1. Створіть `.env` (скопіюйте з `.env.sample`) та вкажіть `BOT_TOKEN` і `DATABASE_URL`.
1. Встановіть залежності:

```bash
pip install -r requirements.txt
```

1. Запустіть бота:

```bash
python -m app.bot
```

1. Запустіть Web App API + UI:

```bash
python -m app.web_main
```

### Docker (повний стек)

```bash
docker compose -p finance-bot up -d --build
```

### Запуск однією командою + tunnel (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_bot_with_tunnel.ps1
```

Цей скрипт:

- запускає `db` і `finance-web`
- чекає `/api/webapp/health`
- створює тимчасовий localhost.run tunnel
- оновлює `WEBAPP_URL` в `.env`
- оновлює кнопку меню Telegram
- запускає `finance-bot`

## Тести

```bash
pip install -r requirements-dev.txt
pytest tests/
```

### E2E (Playwright)

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest tests/e2e/test_webapp_playwright.py -q
```

## Структура проєкту

- `app/bot.py` точка входу Telegram-бота
- `app/web_main.py` точка входу FastAPI Web App
- `app/services/` OCR, парсинг, категоризація, агрегації
- `app/handlers/` маршрути та сценарії бота
- `app/web/` бекенд Web App + статичний UI
- `tests/` unit + e2e

## Документація

- Огляд архітектури: [BOT_OVERVIEW.md](BOT_OVERVIEW.md)
- Покращення категоризації: [IMPROVEMENTS.md](IMPROVEMENTS.md)
- Цілі якості OCR: [OCR_QUALITY_TARGETS.md](OCR_QUALITY_TARGETS.md)

## Примітки

- Для продакшену використовуйте PostgreSQL і налаштуйте `WEBAPP_URL`.
- Бінарний файл Tesseract має бути встановлений на хості/в контейнері.
